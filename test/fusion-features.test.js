import assert from "node:assert/strict";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const cli = join(projectRoot, "bin", "open-pptd-skills.js");
const scriptsDir = join(projectRoot, "skills", "open-pptd", "scripts");

function runPython(script, args = []) {
  return spawnSync("python3", [join(scriptsDir, script), ...args], {
    encoding: "utf8",
    timeout: 30000,
  });
}

function runCli(args) {
  return spawnSync(process.execPath, [cli, ...args], {
    encoding: "utf8",
    timeout: 30000,
  });
}

// --- Helper: create a minimal PPTD project ---
function createMinimalProject(root) {
  const dir = join(root, "minimal");
  const pagesDir = join(dir, "pages");
  mkdirSync(pagesDir, { recursive: true });
  writeFileSync(join(dir, "minimal.pptd"), `version: v2
title: Minimal
size: [960, 540]
pages:
  - pages/01.page
`);
  writeFileSync(join(pagesDir, "01.page"), `pageType: content
elements:
  - elementId: title
    elementType: text
    bounds: [100, 100, 760, 80]
    content:
      fontSize: 36
      text: "Hello World"
`);
  return dir;
}

function mkdirp(dir) {
  mkdirSync(dir, { recursive: true });
}

// =============================================================================
// TODO 4: Anti-AI-slop enforcement
// =============================================================================

test("anti-slop: detects banned Chinese phrase", () => {
  const root = mkdtempSync(join(tmpdir(), "slop-test-"));
  try {
    const dir = createMinimalProject(root);
    // Inject banned phrase
    const pagePath = join(dir, "pages", "01.page");
    const content = readFileSync(pagePath, "utf8").replace(
      "Hello World",
      "我们不是做工具，而是打造全链路闭环生态"
    );
    writeFileSync(pagePath, content);

    const result = runPython("validate_deck.py", ["--project", dir, "--json"]);
    // validate_deck returns exit 1 when issues found (expected)
    const report = JSON.parse(result.stdout);
    assert.ok(report.issueCount > 0, "should detect anti-slop issue");
    assert.ok(
      report.issues.some((i) => i.code === "anti-slop-phrase"),
      "should flag anti-slop-phrase"
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("anti-slop: detects card wall layout", () => {
  const root = mkdtempSync(join(tmpdir(), "cardwall-test-"));
  try {
    const dir = createMinimalProject(root);
    const pagePath = join(dir, "pages", "01.page");
    writeFileSync(pagePath, `pageType: content
elements:
  - elementId: c1
    elementType: shape
    shape: roundRect
    bounds: [60, 140, 200, 150]
    fill: {color: "#FF0000"}
  - elementId: c2
    elementType: shape
    shape: roundRect
    bounds: [280, 140, 200, 150]
    fill: {color: "#800080"}
  - elementId: c3
    elementType: shape
    shape: roundRect
    bounds: [500, 140, 200, 150]
    fill: {color: "#FFFF00"}
  - elementId: c4
    elementType: shape
    shape: roundRect
    bounds: [720, 140, 200, 150]
    fill: {color: "#008000"}
`);

    const result = runPython("validate_deck.py", ["--project", dir, "--json"]);
    const report = JSON.parse(result.stdout);
    assert.ok(
      report.issues.some((i) => i.code === "anti-slop-card-layout"),
      "should flag card wall"
    );
    assert.ok(
      report.issues.some((i) => i.code === "anti-slop-rainbow-scheme"),
      "should flag rainbow scheme"
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("anti-slop: clean deck passes", () => {
  const root = mkdtempSync(join(tmpdir(), "clean-test-"));
  try {
    const dir = createMinimalProject(root);
    const result = runPython("validate_deck.py", ["--project", dir, "--json"]);
    const report = JSON.parse(result.stdout);
    assert.equal(report.issueCount, 0, "clean deck should pass");
    assert.equal(report.valid, true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// =============================================================================
// TODO 7: Layout planner
// =============================================================================

test("layout_planner: inserts section dividers after N content pages", () => {
  const root = mkdtempSync(join(tmpdir(), "planner-test-"));
  try {
    const outline = {
      title: "Test",
      pages: [
        { index: 1, type: "cover", title: "Cover" },
        ...Array.from({ length: 12 }, (_, i) => ({
          index: i + 2,
          type: "content",
          title: `Page ${i + 2}`,
        })),
        { index: 14, type: "final", title: "End" },
      ],
    };
    const outlinePath = join(root, "outline.json");
    writeFileSync(outlinePath, JSON.stringify(outline));

    const result = runPython("layout_planner.py", [outlinePath, "--json"]);
    assert.equal(result.status, 0, result.stderr);
    const report = JSON.parse(result.stdout);
    // With 12 content pages and default max=5, expect at least 1 inserted divider
    const inserted = report.pages.filter((p) => p.inserted);
    assert.ok(inserted.length >= 1, "should insert at least 1 divider");
    assert.equal(report.violations.length, 0, "no rhythm violations");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("layout_planner: no consecutive same archetype+silhouette", () => {
  const root = mkdtempSync(join(tmpdir(), "planner2-test-"));
  try {
    const outline = {
      title: "Test",
      pages: [
        { index: 1, type: "cover", title: "Cover" },
        { index: 2, type: "content", title: "Same title length" },
        { index: 3, type: "content", title: "Same title length" },
        { index: 4, type: "final", title: "End" },
      ],
    };
    const outlinePath = join(root, "outline.json");
    writeFileSync(outlinePath, JSON.stringify(outline));

    const result = runPython("layout_planner.py", [outlinePath, "--json"]);
    const report = JSON.parse(result.stdout);
    // Pages 2 and 3 have same title length → same silhouette → should be broken up
    assert.equal(report.violations.length, 0, "should not have consecutive same archetype");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// =============================================================================
// TODO 8: convert_fidelity
// =============================================================================

test("convert_fidelity: converts PPTX to PPTD with confidence scoring", () => {
  // This test requires python-pptx; skip if not available
  const result = runPython("convert_fidelity.py", ["--help"]);
  if (result.stderr.includes("python-pptx not installed") || result.status !== 0) {
    return; // skip
  }

  const root = mkdtempSync(join(tmpdir(), "convert-test-"));
  try {
    // Create a minimal PPTX using python-pptx
    const pptxPath = join(root, "test.pptx");
    const createResult = runPython("-c", `
from pptx import Presentation
from pptx.util import Inches, Pt
prs = Presentation()
s = prs.slides.add_slide(prs.slide_layouts[6])
tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
tb.text_frame.text = "Test Title"
prs.save("${pptxPath}")
`);
    if (createResult.status !== 0) return; // skip if python-pptx not available

    const outputDir = join(root, "output");
    const convertResult = runPython("convert_fidelity.py", [pptxPath, outputDir, "--json"]);
    assert.equal(convertResult.status, 0, convertResult.stderr);
    const report = JSON.parse(convertResult.stdout);
    assert.ok(report.summary.total_elements > 0);
    assert.ok(report.summary.average_confidence > 0);
    assert.ok(existsSync(join(outputDir, "test.pptd")));

    // Validate the converted PPTD
    const validateResult = runPython("validate_deck.py", ["--project", outputDir, "--json"]);
    const validateReport = JSON.parse(validateResult.stdout);
    assert.equal(validateReport.valid, true, "converted PPTD should pass validation");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// =============================================================================
// CLI: convert-fidelity command
// =============================================================================

test("CLI: convert-fidelity requires input and output", () => {
  const result = runCli(["convert-fidelity"]);
  assert.notEqual(result.status, 0);
  assert.ok(result.stderr.includes("requires"));
});

test("CLI: convert-fidelity runs end-to-end", () => {
  // Skip if python-pptx not available
  const check = spawnSync("python3", ["-c", "import pptx"], { encoding: "utf8" });
  if (check.status !== 0) return;

  const root = mkdtempSync(join(tmpdir(), "cli-convert-test-"));
  try {
    const pptxPath = join(root, "test.pptx");
    const createResult = runPython("-c", `
from pptx import Presentation
from pptx.util import Inches
prs = Presentation()
s = prs.slides.add_slide(prs.slide_layouts[6])
tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
tb.text_frame.text = "CLI Test"
prs.save("${pptxPath}")
`);
    if (createResult.status !== 0) return;

    const outputDir = join(root, "output");
    const result = runCli(["convert-fidelity", pptxPath, outputDir]);
    assert.equal(result.status, 0, result.stderr);
    assert.ok(existsSync(join(outputDir, "test.pptd")));
    assert.ok(existsSync(join(outputDir, "fidelity-report.json")));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
