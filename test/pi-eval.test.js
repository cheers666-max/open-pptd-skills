import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { checkReadOnlyCall } from '../eval/read_only_guard.js';

test('pi evaluation runner isolates finite runs and distinguishes execution from quality', () => {
  const root = fileURLToPath(new URL('../', import.meta.url));
  const result = spawnSync('python3', ['-m', 'unittest', 'discover', '-s', 'eval', '-p', 'test_*.py', '-v'], {
    cwd: root, encoding: 'utf8', timeout: 60_000,
  });
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stdout + result.stderr);
});

test('independent review guard blocks writes, outside paths and escaping symlinks', () => {
  const parent = mkdtempSync(join(tmpdir(), 'pi-review-guard-'));
  const root = join(parent, 'case');
  mkdirSync(root);
  writeFileSync(join(root, 'page.md'), 'local evidence');
  writeFileSync(join(parent, 'private.md'), 'outside case');
  symlinkSync(join(parent, 'private.md'), join(root, 'escape.md'));
  try {
    assert.equal(checkReadOnlyCall({ toolName: 'read', input: { path: 'page.md' } }, root), undefined);
    for (const event of [
      { toolName: 'write', input: { path: 'page.md' } },
      { toolName: 'read', input: { path: '../private.md' } },
      { toolName: 'read', input: { path: 'escape.md' } },
      { toolName: 'read', input: { path: '~/.pi/agent/auth.json' } },
    ]) assert.equal(checkReadOnlyCall(event, root)?.block, true);
  } finally {
    rmSync(parent, { recursive: true, force: true });
  }
});
