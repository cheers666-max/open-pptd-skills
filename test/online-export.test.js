import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

test('360 online export: local HTTP contract and actual Chrome HTML export', () => {
  const result = spawnSync('python3', ['-m', 'unittest', 'discover', '-s', 'skills/open-pptd/tests', '-p', 'test_online_export.py', '-v'], {encoding: 'utf8', timeout: 180000});
  assert.equal(result.status, 0, result.stdout + result.stderr);
});
