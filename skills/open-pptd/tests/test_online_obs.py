"""OBS config/transfer regression tests; never read the user's real credentials."""
import hashlib
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import export_online as online


@unittest.skipUnless(importlib.util.find_spec('boto3'), 'OBS tests require optional boto3 dependency')
class OBSExportTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((SCRIPTS / 'obs_upload.py').exists(), 'OBS backend is not implemented')
        import obs_upload
        import boto3
        from botocore.stub import Stubber
        self.obs = obs_upload
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'protected.yaml'
        self.raw = {'endpoint': 'https://objects.example.com', 'region': 'cn-north-4',
                    'bucket': 'test-bucket', 'access_key_id': 'test-only-ak',
                    'access_key_secret': 'test-only-sk'}
        self.config.write_text(yaml.safe_dump({'profiles': {'default': self.raw}}))
        self.sdk = boto3.client('s3', endpoint_url=self.raw['endpoint'], region_name=self.raw['region'],
                                aws_access_key_id='test-only-ak', aws_secret_access_key='test-only-sk')
        self.stub = Stubber(self.sdk)
        self.stub.activate()
        self.addCleanup(self.stub.deactivate)
        self.session_patch = patch('boto3.Session')
        self.session = self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.session.return_value.client.return_value = self.sdk

    def client(self, **kwargs):
        return self.obs.OBSClient(self.config, prefix='open-pptd/test', **kwargs)

    def expect_upload(self, name, payload, content_type):
        key = 'open-pptd/test/' + ('assets/' if not name.endswith('.html') else '') + name
        digest = hashlib.sha256(payload).hexdigest()
        request = {'Bucket': 'test-bucket', 'Key': key}
        metadata = {'sha256': digest, 'publisher': 'open-pptd-online'}
        self.stub.add_client_error('head_object', service_error_code='404', http_status_code=404,
                                   expected_params=request)
        self.stub.add_response('put_object', {}, {**request, 'Body': payload, 'ContentType': content_type,
                               'CacheControl': 'no-cache' if name.endswith('.html') else 'public, max-age=31536000, immutable',
                               'Metadata': metadata})
        self.stub.add_response('head_object', {'ContentLength': len(payload), 'Metadata': metadata}, request)
        self.stub.add_response('get_object', {'Body': BytesIO(payload)}, request)
        return key

    def test_existing_zhengzhou_shape_and_legacy_config(self):
        for shape in [{'obs': self.raw}, {'profiles': {'default': self.raw}}, {'targets': {'zz': self.raw}}]:
            self.config.write_text(yaml.safe_dump(shape))
            self.client()
            kw = self.session.return_value.client.call_args.kwargs
            self.assertEqual(kw['region_name'], 'cn-north-4')
            self.assertEqual(kw['aws_secret_access_key'], 'test-only-sk')
            self.assertEqual(kw['config'].s3['addressing_style'], 'path')

    def test_explicit_env_credentials_override_legacy_values(self):
        self.raw.update(access_key_env='TEST_OBS_AK', secret_key_env='TEST_OBS_SK')
        self.config.write_text(yaml.safe_dump({'obs': self.raw}))
        with patch.dict(os.environ, {'TEST_OBS_AK': 'env-only-ak', 'TEST_OBS_SK': 'env-only-sk'}, clear=True):
            self.client()
            self.assertEqual(self.session.return_value.client.call_args.kwargs['aws_access_key_id'], 'env-only-ak')
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(self.obs.ObsError, 'environment'):
            self.client()

    def test_ambiguous_profiles_and_missing_credentials_fail_before_sdk(self):
        self.config.write_text(yaml.safe_dump({'profiles': {'one': self.raw, 'two': self.raw}}))
        with self.assertRaisesRegex(self.obs.ObsError, 'profile'):
            self.client()
        self.client(profile='two')
        self.session.reset_mock()
        del self.raw['access_key_secret']
        self.config.write_text(yaml.safe_dump({'obs': self.raw}))
        with self.assertRaises(self.obs.ObsError):
            self.client()
        self.session.assert_not_called()

    def test_upload_sets_mime_hash_and_verifies_object_before_url(self):
        key = self.expect_upload('photo.png', b'image bytes', 'image/png')
        client = self.client()
        url = client.upload(b'image bytes', 'photo.png', 'image/png')
        self.assertEqual(url, 'https://objects.example.com/test-bucket/' + key)
        self.assertEqual(client.report()['objects'][0]['action'], 'create')
        self.stub.assert_no_pending_responses()

    def test_existing_identical_object_is_read_back_without_overwrite(self):
        payload = b'old image'
        request = {'Bucket': 'test-bucket', 'Key': 'open-pptd/test/assets/photo.png'}
        self.stub.add_response('head_object', {'ContentLength': len(payload), 'Metadata': {
            'sha256': hashlib.sha256(payload).hexdigest()}}, request)
        self.stub.add_response('get_object', {'Body': BytesIO(payload)}, request)
        client = self.client()
        client.upload(payload, 'photo.png', 'image/png')
        self.assertEqual(client.report()['objects'][0]['action'], 'skip')
        self.stub.assert_no_pending_responses()

    def test_conflicting_object_and_forbidden_head_never_write(self):
        request = {'Bucket': 'test-bucket', 'Key': 'open-pptd/test/index.html'}
        self.stub.add_response('head_object', {'ContentLength': 999, 'Metadata': {}}, request)
        with self.assertRaisesRegex(self.obs.ObsError, 'conflict'):
            self.client().upload(b'new page', 'index.html', 'text/html')
        self.stub.add_client_error('head_object', service_error_code='AccessDenied', http_status_code=403,
                                  service_message='SECRET from server', expected_params=request)
        with self.assertRaises(self.obs.ObsError) as caught:
            self.client().upload(b'new page', 'index.html', 'text/html')
        self.assertNotIn('SECRET', str(caught.exception))
        self.stub.assert_no_pending_responses()

    def test_corrupt_remote_object_is_failure_even_with_matching_metadata(self):
        payload = b'expected'
        request = {'Bucket': 'test-bucket', 'Key': 'open-pptd/test/assets/photo.png'}
        self.stub.add_response('head_object', {'ContentLength': len(payload), 'Metadata': {
            'sha256': hashlib.sha256(payload).hexdigest()}}, request)
        self.stub.add_response('get_object', {'Body': BytesIO(b'corrupt!')}, request)
        with self.assertRaisesRegex(self.obs.ObsError, 'verification'):
            self.client().upload(payload, 'photo.png', 'image/png')

    def test_partial_failure_reports_completed_and_failed_keys(self):
        completed = self.expect_upload('photo.png', b'image', 'image/png')
        client = self.client()
        client.upload(b'image', 'photo.png', 'image/png')
        failed = 'open-pptd/test/page_01.html'
        self.stub.add_client_error('head_object', service_error_code='AccessDenied', http_status_code=403,
                                  expected_params={'Bucket': 'test-bucket', 'Key': failed})
        with self.assertRaises(self.obs.ObsError) as caught:
            client.upload(b'page', 'page_01.html', 'text/html')
        self.assertTrue(hasattr(caught.exception, 'details'), 'Partial transfers need an object report')
        self.assertEqual(caught.exception.details['failed_key'], failed)
        self.assertEqual(caught.exception.details['objects'][0]['key'], completed)
        self.assertFalse(caught.exception.details['write_succeeded'])

    def test_unreadable_public_url_reports_partial_upload(self):
        key = self.expect_upload('photo.png', b'image', 'image/png')
        self.assertTrue(hasattr(online, 'upload_verified'), 'Public verification must report OBS partial uploads')
        with patch.object(online, 'download', side_effect=online.OnlineError('Asset download failed')):
            with self.assertRaises(self.obs.ObsError) as caught:
                online.upload_verified(self.client(), b'image', 'photo.png', 'image/png', 3, 'Uploaded image')
        self.assertEqual(caught.exception.details['failed_key'], key)
        self.assertTrue(caught.exception.details['objects'][0]['verified'])
        self.assertFalse(caught.exception.details['objects'][0]['public_verified'])

    def test_config_and_prefix_validation_and_unique_default(self):
        for prefix in ['../outside', 'a/../b', '/absolute', 'a//b', 'a\\b']:
            with self.subTest(prefix=prefix), self.assertRaises(self.obs.ObsError):
                self.obs.OBSClient(self.config, prefix=prefix)
        first = self.obs.OBSClient(self.config)
        second = self.obs.OBSClient(self.config)
        self.assertNotEqual(first.report()['prefix'], second.report()['prefix'])
        self.raw['endpoint'] = 'https://user:SECRET@objects.example.com'
        self.config.write_text(yaml.safe_dump({'obs': self.raw}))
        with self.assertRaises(self.obs.ObsError) as caught:
            self.client()
        self.assertNotIn('SECRET', str(caught.exception))

    def test_cdn_base_and_encoded_prefix(self):
        self.raw.update(public_base_url='https://cdn.example.com/ppt', addressing_style='virtual')
        self.config.write_text(yaml.safe_dump({'obs': self.raw}))
        request = {'Bucket': 'test-bucket', 'Key': 'deck demo/assets/photo.png'}
        self.stub.add_response('head_object', {'ContentLength': 1, 'Metadata': {
            'sha256': hashlib.sha256(b'x').hexdigest()}}, request)
        self.stub.add_response('get_object', {'Body': BytesIO(b'x')}, request)
        client = self.obs.OBSClient(self.config, prefix='deck demo')
        self.assertEqual(client.upload(b'x', 'photo.png', 'image/png'),
                         'https://cdn.example.com/ppt/deck%20demo/assets/photo.png')

    def test_export_uses_obs_without_attachment_key_and_publishes_index_last(self):
        import base64
        import zipfile
        (self.root / 'deck.pptd').write_text('pages: [1.page]\nsize: [960, 540]\n')
        picture = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
        (self.root / 'pic.svg').write_bytes(picture)
        (self.root / '1.page').write_text('elements: [{elementType: image, src: pic.svg}]')
        data_uri = 'data:image/svg+xml;base64,' + base64.b64encode(picture).decode()
        original_html = '<html><img src="' + data_uri + '"></html>'
        stream = BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name in ['index.html', 'page_01.html']:
                archive.writestr(name, original_html)
        filename = hashlib.sha256(picture).hexdigest() + '.svg'
        key = self.expect_upload(filename, picture, 'image/svg+xml')
        url = 'https://objects.example.com/test-bucket/' + key
        final_html = original_html.replace(data_uri, url).encode()
        self.expect_upload('page_01.html', final_html, 'text/html; charset=utf-8')
        self.expect_upload('index.html', final_html, 'text/html; charset=utf-8')
        with patch.dict(os.environ, {}, clear=True), patch.object(online, 'find_chrome'), \
             patch.object(online, 'run_viewer_export', return_value=stream.getvalue()), \
             patch.object(online, 'download', side_effect=[picture, final_html, final_html]) as public:
            report = online.run(str(self.root / 'deck.pptd'), obs_config=str(self.config),
                                obs_prefix='open-pptd/test', publish=True)
        self.assertTrue(report['ok'])
        self.assertEqual(report['upload_backend'], 'obs')
        self.assertEqual(public.call_count, 3)
        self.assertEqual(len(report['storage']['objects']), 3)
        self.assertIn(url, (self.root / 'html-online/page_01.html').read_text())
        self.assertNotIn('test-only-', json.dumps(report))
        self.assertNotIn('protected.yaml', json.dumps(report))
        self.stub.assert_no_pending_responses()


if __name__ == '__main__':
    unittest.main()
