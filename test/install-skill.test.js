import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const cli = join(projectRoot, "bin", "open-pptd-skills.js");

function runCli(args, env = process.env) {
  return spawnSync(process.execPath, [cli, ...args], {
    encoding: "utf8",
    env,
  });
}

test("installs the packaged skill into a custom skills directory", () => {
  const root = mkdtempSync(join(tmpdir(), "open-pptd-test-"));
  const target = join(root, "skills");

  try {
    const result = runCli(["install", "--target", target]);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(existsSync(join(target, "open-pptd", "SKILL.md")), true);
    assert.equal(existsSync(join(target, "open-pptd", "scripts", "export_pptx.mjs")), true);
    assert.equal(existsSync(join(target, "open-pptd", "_user_meta.json")), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("installs into ~/.agents/skills when no target is provided", () => {
  const root = mkdtempSync(join(tmpdir(), "open-pptd-test-"));

  try {
    const result = runCli([], { ...process.env, HOME: root, USERPROFILE: root, CODEX_HOME: undefined });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(existsSync(join(root, ".agents", "skills", "open-pptd", "SKILL.md")), true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("overwrites an existing installation by default", () => {
  const root = mkdtempSync(join(tmpdir(), "open-pptd-test-"));
  const target = join(root, "skills");
  const skillFile = join(target, "open-pptd", "SKILL.md");

  try {
    assert.equal(runCli(["--target", target]).status, 0);
    writeFileSync(skillFile, "modified", "utf8");

    const result = runCli(["--target", target]);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /Updated open-pptd/);
    assert.match(readFileSync(skillFile, "utf8"), /^---\nname: open-pptd/m);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("accepts legacy --force without changing overwrite behavior", () => {
  const root = mkdtempSync(join(tmpdir(), "open-pptd-test-"));
  const target = join(root, "skills");

  try {
    assert.equal(runCli(["--target", target]).status, 0);
    const result = runCli(["--target", target, "--force"]);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /Updated open-pptd/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("serve command serves viewer.html at the root", async () => {
  const { startEditorServer } = await import("../lib/editor-server.js");
  const { server, url } = await startEditorServer({ port: 0 });
  try {
    const res = await fetch(url);
    assert.equal(res.status, 200);
    assert.match(res.headers.get("content-type"), /text\/html/);
    const html = await res.text();
    assert.match(html, /PPTD Viewer/);
  } finally {
    server.close();
  }
});
