"""S3-compatible OBS adapter for online export. Read only explicitly selected config.

Credentials stay in memory. Each object is checked before writing and read back
before returning its public URL. The caller also verifies an unauthenticated GET.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from urllib.parse import quote, urlsplit
import uuid


class ObsError(RuntimeError):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def https_base(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or any(ord(c) < 33 for c in value)):
            raise ValueError()
        parsed.port
    except (ValueError, TypeError, AttributeError):
        raise ObsError('OBS URL must be HTTPS without credentials, query or fragment') from None
    return value.rstrip('/')


def load_profile(config, profile):
    if not config:
        raise ObsError('Set OBS_CONFIG or --obs-config to an existing protected OBS YAML file')
    try:
        import yaml
        data = yaml.safe_load(Path(config).expanduser().read_text(encoding='utf-8'))
    except ImportError:
        raise ObsError('OBS config needs PyYAML; install with python3 -m pip install PyYAML') from None
    except Exception:
        raise ObsError('Cannot read or parse OBS config') from None
    if not isinstance(data, dict):
        raise ObsError('OBS config must be a mapping')
    if 'obs' in data:
        if profile or 'profiles' in data or 'targets' in data:
            raise ObsError('Legacy obs config cannot be combined with a profile')
        raw = data['obs']
    else:
        groups = data.get('profiles') or data.get('targets')
        if not isinstance(groups, dict) or not groups:
            raise ObsError('OBS config needs obs, profiles or targets')
        selected = profile or (next(iter(groups)) if len(groups) == 1 else None)
        if selected not in groups:
            raise ObsError('Choose an existing OBS profile with --obs-profile')
        raw = groups[selected]
    if not isinstance(raw, dict):
        raise ObsError('OBS profile must be a mapping')
    return raw


def credential(raw, reference, *fields):
    nested = raw.get('credentials') or {}
    if not isinstance(nested, dict):
        raise ObsError('OBS credentials must be a mapping')
    env_name = nested.get(reference) or raw.get(reference)
    if env_name:
        if not isinstance(env_name, str) or not os.environ.get(env_name, '').strip():
            raise ObsError('Missing configured OBS credential environment variable')
        return os.environ[env_name].strip()
    return next((str(raw[f]).strip() for f in fields if raw.get(f)), None)


class OBSClient:
    def __init__(self, config, profile=None, prefix=None, timeout=30):
        raw = load_profile(config, profile)
        self.endpoint = https_base(raw.get('endpoint'))
        self.bucket = raw.get('bucket') or raw.get('bucket_name')
        region = raw.get('region')
        if not isinstance(self.bucket, str) or not re.fullmatch(r'[a-zA-Z0-9._-]+', self.bucket):
            raise ObsError('OBS config needs a valid bucket')
        if not isinstance(region, str) or not region.strip():
            raise ObsError('OBS config needs its signing region')
        addressing = raw.get('addressing_style') or 'path'
        if addressing not in ('path', 'virtual'):
            raise ObsError('OBS addressing_style must be path or virtual')
        if addressing != 'path' and not raw.get('public_base_url'):
            raise ObsError('Virtual addressing requires public_base_url')
        self.public_base = https_base(raw.get('public_base_url') or self.endpoint + '/' + self.bucket)
        self.prefix = prefix if prefix is not None else 'open-pptd/' + uuid.uuid4().hex
        if (not isinstance(self.prefix, str) or not self.prefix or '\\' in self.prefix
                or any(part in ('', '.', '..') for part in self.prefix.split('/'))
                or any(ord(c) < 32 for c in self.prefix)):
            raise ObsError('OBS prefix must be a safe non-empty relative object path')
        access = credential(raw, 'access_key_env', 'access_key_id')
        secret = credential(raw, 'secret_key_env', 'access_key_secret', 'secret_access_key')
        token = credential(raw, 'session_token_env', 'session_token')
        if not access or not secret:
            raise ObsError('OBS config must declare both access key and secret key, directly or via environment references')
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            raise ObsError('OBS upload needs boto3; install with python3 -m pip install "boto3>=1.36"') from None
        try:
            # Modern SDK optional streaming checksums are not portable to all OBS services.
            self.client = boto3.Session().client(
                's3', endpoint_url=self.endpoint, region_name=region,
                aws_access_key_id=access, aws_secret_access_key=secret, aws_session_token=token,
                config=Config(signature_version='s3v4', s3={'addressing_style': addressing},
                              connect_timeout=timeout, read_timeout=timeout,
                              retries={'mode': 'standard', 'total_max_attempts': 2},
                              request_checksum_calculation='when_required',
                              response_checksum_validation='when_required'))
        except Exception:
            raise ObsError('Cannot initialize OBS client; check config and boto3 version (>=1.36)') from None
        self.objects = []

    def upload(self, data, filename, content_type):
        if not isinstance(filename, str) or not re.fullmatch(r'[a-zA-Z0-9_-][a-zA-Z0-9_.-]*', filename):
            raise ObsError('Invalid OBS upload filename')
        key = self.prefix + '/' + ('' if filename.endswith('.html') else 'assets/') + filename
        url = self.public_base + '/' + quote(key, safe='/')
        digest = hashlib.sha256(data).hexdigest()
        params = {'Bucket': self.bucket, 'Key': key}
        action = 'skip'
        write_succeeded = False
        try:
            try:
                head = self.client.head_object(**params)
            except Exception as exc:
                response = getattr(exc, 'response', {})
                status = (response.get('ResponseMetadata') or {}).get('HTTPStatusCode')
                code = (response.get('Error') or {}).get('Code')
                if status != 404 and code not in ('404', 'NoSuchKey', 'NotFound'):
                    raise
                head = None
            if head is not None:
                if head.get('ContentLength') != len(data) or (head.get('Metadata') or {}).get('sha256') != digest:
                    raise ObsError(f'OBS object conflict at {key}; choose a new --obs-prefix')
            else:
                self.client.put_object(**params, Body=data, ContentType=content_type,
                                       CacheControl='no-cache' if filename.endswith('.html') else 'public, max-age=31536000, immutable',
                                       Metadata={'sha256': digest, 'publisher': 'open-pptd-online'})
                write_succeeded = True
                action = 'create'
                head = self.client.head_object(**params)
            if head.get('ContentLength') != len(data) or (head.get('Metadata') or {}).get('sha256') != digest:
                raise ObsError(f'OBS metadata verification failed at {key}')
            body = self.client.get_object(**params)['Body']
            try:
                returned = body.read(len(data) + 1)
            finally:
                body.close()
            if returned != data:
                raise ObsError(f'OBS content verification failed at {key}')
        except ObsError as exc:
            exc.details = {**self.report(), 'failed_key': key, 'write_succeeded': write_succeeded}
            raise
        except Exception:
            # SDK errors can contain signed requests and service response bodies.
            raise ObsError(f'OBS transfer failed at {key}; check endpoint, signing region and permissions',
                           {**self.report(), 'failed_key': key, 'write_succeeded': write_succeeded}) from None
        self.objects.append({'key': key, 'url': url, 'sha256': digest, 'bytes': len(data),
                             'action': action, 'verified': True, 'public_verified': False})
        return url

    def report(self):
        return {'endpoint': self.endpoint, 'bucket': self.bucket, 'prefix': self.prefix, 'objects': self.objects}
