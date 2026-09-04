#!/usr/bin/env node

import { cpSync, existsSync, mkdtempSync, mkdirSync, renameSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { startEditorServer } from "../lib/editor-server.js";

const SKILL_NAME = "open-pptd";
const MIN_NODE_MAJOR = 18;
const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourceDirectory = join(packageRoot, "skills", SKILL_NAME);

function assertNodeVersion() {
  const major = Number.parseInt(process.versions.node.split(".")[0], 10);
  if (!Number.isInteger(major) || major < MIN_NODE_MAJOR) {
    throw new Error(
      `Node.js ${MIN_NODE_MAJOR}+ is required; found ${process.version}. Install from https://nodejs.org`,
    );
  }
}

function printHelp(command) {
  if (command === "serve") {
    console.log(`Start the local PPTD viewer.

Usage:
  open-pptd-skills serve [options]

Options:
  --port <number>  HTTP port (default: 55173)
  --open           Open the viewer in the default browser
  -h, --help       Show this help
`);
    return;
  }

  if (command === "validate") {
    console.log(`Run deterministic hard-issue audit on a PPTD project.

Usage:
  open-pptd-skills validate <project> [options]

Arguments:
  <project>            Path to PPTD project directory

Options:
  --manifest <path>    Explicit .pptd manifest path
  --target-width <n>   Expected rendered width (default: 1280)
  --min-image-scale <f>  Min effective source pixels per rendered pixel (default: 0.6)
  --output <path>      Output JSON path (default: <project>/validate-report.json)
  --json               Print JSON to stdout
  -h, --help           Show this help
`);
    return;
  }

  console.log(`Install ${SKILL_NAME} for your AI coding agent, run its local viewer, or validate a project.

Usage:
  open-pptd-skills [install] [options]
  open-pptd-skills serve [options]
  open-pptd-skills check <project> [options]
  open-pptd-skills screenshot <project> [options]
  open-pptd-skills convert <deck.pptx> [options]
  open-pptd-skills convert-fidelity <deck.pptx> <output_dir> [options]
  open-pptd-skills design <list|get|build-index> [options]

Install options:
  --target <directory>  Skills directory (default: ~/.agents/skills)

Re-running install replaces an existing ${SKILL_NAME} installation.
Run "open-pptd-skills serve --help" for server options.
`);
}

function parseArguments(arguments_) {
  const args = [...arguments_];
  const command = ["install", "serve", "validate", "check", "screenshot", "convert", "convert-fidelity", "design"].includes(args[0]) ? args.shift() : "install";
  const options = command === "serve"
    ? { command, open: false, port: 55173 }
    : command === "validate"
    ? { command, project: undefined, manifest: undefined, targetWidth: 1280, minImageScale: 0.6, output: undefined, json: false }
    : command === "check"
    ? { command, project: undefined, manifest: undefined, page: undefined, severity: "all", level: "keep", output: undefined, json: false }
    : command === "screenshot"
    ? { command, project: undefined, output: undefined, page: undefined }
    : command === "convert"
    ? { command, input: undefined, output: undefined }
    : command === "convert-fidelity"
    ? { command, input: undefined, output: undefined, report: undefined, json: false }
    : command === "design"
    ? { command, action: "list", category: undefined, tag: undefined, name: undefined }
    : { command, target: undefined };

  while (args.length > 0) {
    const argument = args.shift();

    // Accepted for backward compatibility; install always overwrites.
    if (command === "install" && argument === "--force") {
      continue;
    }

    if (command === "install" && argument === "--target") {
      const target = args.shift();
      if (!target || target.startsWith("-")) {
        throw new Error("--target requires a directory");
      }
      options.target = resolve(target);
      continue;
    }

    if (command === "serve" && argument === "--port") {
      const port = Number(args.shift());
      if (!Number.isInteger(port) || port < 1 || port > 65_535) {
        throw new Error("--port must be an integer between 1 and 65535");
      }
      options.port = port;
      continue;
    }

    if (command === "serve" && argument === "--open") {
      options.open = true;
      continue;
    }

    if (command === "validate" && argument === "--manifest") {
      const p = args.shift();
      if (!p || p.startsWith("-")) throw new Error("--manifest requires a path");
      options.manifest = resolve(p);
      continue;
    }
    if (command === "validate" && argument === "--target-width") {
      const n = Number(args.shift());
      if (!Number.isInteger(n) || n < 1) throw new Error("--target-width must be a positive integer");
      options.targetWidth = n;
      continue;
    }
    if (command === "validate" && argument === "--min-image-scale") {
      const f = Number(args.shift());
      if (!Number.isFinite(f) || f <= 0) throw new Error("--min-image-scale must be a positive number");
      options.minImageScale = f;
      continue;
    }
    if (command === "validate" && argument === "--output") {
      const p = args.shift();
      if (!p || p.startsWith("-")) throw new Error("--output requires a path");
      options.output = resolve(p);
      continue;
    }
    if (command === "validate" && argument === "--json") {
      options.json = true;
      continue;
    }

    // --- check ---
    if (command === "check" && argument === "--manifest") {
      const p = args.shift();
      if (!p || p.startsWith("-")) throw new Error("--manifest requires a path");
      options.manifest = resolve(p);
      continue;
    }
    if (command === "check" && (argument === "--page" || argument === "-p")) {
      const p = args.shift();
      if (!p) throw new Error("--page requires a spec");
      options.page = p;
      continue;
    }
    if (command === "check" && (argument === "--severity" || argument === "-s")) {
      const s = args.shift();
      if (!s) throw new Error("--severity requires a spec");
      options.severity = s;
      continue;
    }
    if (command === "check" && argument === "--level") {
      const l = args.shift();
      if (!["keep", "auto"].includes(l)) throw new Error("--level must be keep|auto");
      options.level = l;
      continue;
    }
    if (command === "check" && argument === "--output") {
      const p = args.shift();
      if (!p || p.startsWith("-")) throw new Error("--output requires a path");
      options.output = resolve(p);
      continue;
    }
    if (command === "check" && argument === "--json") {
      options.json = true;
      continue;
    }
    if (command === "check" && !options.project && !argument.startsWith("-")) {
      options.project = resolve(argument);
      continue;
    }

    // --- screenshot ---
    if (command === "screenshot" && (argument === "--output" || argument === "-o")) {
      const p = args.shift();
      if (!p || p.startsWith("-")) throw new Error("--output requires a path");
      options.output = resolve(p);
      continue;
    }
    if (command === "screenshot" && (argument === "--page" || argument === "-p")) {
      const p = args.shift();
      if (!p) throw new Error("--page requires a spec");
      options.page = p;
      continue;
    }
    if (command === "screenshot" && !options.project && !argument.startsWith("-")) {
      options.project = resolve(argument);
      continue;
    }

    // --- convert ---
    if (command === "convert" && (argument === "--output" || argument === "-o")) {
      const p = args.shift();
      if (!p || p.startsWith("-")) throw new Error("--output requires a path");
      options.output = resolve(p);
      continue;
    }
    if (command === "convert" && !options.input && !argument.startsWith("-")) {
      options.input = resolve(argument);
      continue;
    }
    // --- convert-fidelity ---
    if (command === "convert-fidelity" && argument === "--report") {
      const p = args.shift();
      if (!p || p.startsWith("-")) throw new Error("--report requires a path");
      options.report = resolve(p);
      continue;
    }
    if (command === "convert-fidelity" && argument === "--json") {
      options.json = true;
      continue;
    }
    if (command === "convert-fidelity" && !options.input && !argument.startsWith("-")) {
      options.input = resolve(argument);
      continue;
    }
    if (command === "convert-fidelity" && !options.output && !argument.startsWith("-")) {
      options.output = resolve(argument);
      continue;
    }

    // --- design ---
    if (command === "design" && (argument === "list" || argument === "get" || argument === "build-index")) {
      options.action = argument;
      continue;
    }
    if (command === "design" && argument === "--category") {
      options.category = args.shift();
      continue;
    }
    if (command === "design" && argument === "--tag") {
      options.tag = args.shift();
      continue;
    }
    if (command === "design" && !options.name && !argument.startsWith("-")) {
      options.name = argument;
      continue;
    }

    // Positional project path for validate
    if (command === "validate" && !options.project && !argument.startsWith("-")) {
      options.project = resolve(argument);
      continue;
    }

    if (argument === "--help" || argument === "-h") {
      options.help = true;
      continue;
    }

    throw new Error(`unknown argument: ${argument}`);
  }

  if (command === "validate" && !options.project) {
    throw new Error("validate requires a project directory path");
  }
  if (command === "check" && !options.project) {
    throw new Error("check requires a project directory path");
  }
  if (command === "screenshot" && !options.project) {
    throw new Error("screenshot requires a project directory path");
  }
  if (command === "convert" && !options.input) {
    throw new Error("convert requires a PPTX input file path");
  }
  if (command === "convert-fidelity" && !options.input) {
    throw new Error("convert-fidelity requires a PPTX input file path");
  }
  if (command === "convert-fidelity" && !options.output) {
    throw new Error("convert-fidelity requires an output directory");
  }
  if (command === "design" && options.action === "get" && !options.name) {
    throw new Error("design get requires a design system name");
  }

  return options;
}

function openBrowser(url) {
  const command = process.platform === "darwin" ? "open" : process.platform === "win32" ? "cmd" : "xdg-open";
  const args = process.platform === "win32" ? ["/c", "start", "", url] : [url];
  const child = spawn(command, args, { detached: true, stdio: "ignore" });
  child.on("error", (error) => console.warn(`Could not open the browser: ${error.message}`));
  child.unref();
}

function defaultSkillsDirectory() {
  return join(homedir(), ".agents", "skills");
}

function installSkill({ target }) {
  if (!existsSync(join(sourceDirectory, "SKILL.md"))) {
    throw new Error(`packaged skill is incomplete: ${sourceDirectory}`);
  }

  const skillsDirectory = target ?? defaultSkillsDirectory();
  const destination = join(skillsDirectory, SKILL_NAME);
  const replaced = existsSync(destination);

  mkdirSync(skillsDirectory, { recursive: true });
  const stagingRoot = mkdtempSync(join(skillsDirectory, `.${SKILL_NAME}-`));
  const stagedSkill = join(stagingRoot, SKILL_NAME);

  try {
    cpSync(sourceDirectory, stagedSkill, {
      recursive: true,
      filter: (source) => ![".DS_Store", "_user_meta.json"].includes(basename(source)),
    });

    rmSync(destination, { recursive: true, force: true });
    renameSync(stagedSkill, destination);
  } finally {
    rmSync(stagingRoot, { recursive: true, force: true });
  }

  console.log(
    replaced
      ? `Updated ${SKILL_NAME} at ${destination}`
      : `Installed ${SKILL_NAME} to ${destination}`,
  );
}

async function main() {
  assertNodeVersion();
  const options = parseArguments(process.argv.slice(2));
  if (options.help) {
    printHelp(options.command);
    return;
  }

  if (options.command === "install") {
    installSkill(options);
    return;
  }

  if (options.command === "validate") {
    const script = join(sourceDirectory, "scripts", "validate_deck.py");
    const child = spawn("python3", [script, "--project", options.project, ...(options.manifest ? ["--manifest", options.manifest] : []), "--target-width", String(options.targetWidth), "--min-image-scale", String(options.minImageScale), ...(options.output ? ["--output", options.output] : []), ...(options.json ? ["--json"] : [])], { stdio: "inherit" });
    child.on("close", (code) => process.exit(code ?? 0));
    return;
  }

  if (options.command === "check") {
    const script = join(sourceDirectory, "scripts", "validate_deck.py");
    const child = spawn("python3", [
      script, "--project", options.project,
      ...(options.manifest ? ["--manifest", options.manifest] : []),
      ...(options.page ? ["--page", options.page] : []),
      "--severity", options.severity,
      "--level", options.level,
      ...(options.output ? ["--output", options.output] : []),
      ...(options.json ? ["--json"] : []),
    ], { stdio: "inherit" });
    child.on("close", (code) => process.exit(code ?? 0));
    return;
  }

  if (options.command === "screenshot") {
    const script = join(sourceDirectory, "scripts", "export_images.py");
    const child = spawn("python3", [
      script, options.project,
      ...(options.output ? ["--output", options.output] : []),
      ...(options.page ? ["--page", options.page] : []),
    ], { stdio: "inherit" });
    child.on("close", (code) => process.exit(code ?? 0));
    return;
  }

  if (options.command === "convert") {
    const script = join(sourceDirectory, "scripts", "vendor", "open-ppt-engine", "adapters", "pptd.mjs");
    const child = spawn("node", [
      script, options.input,
      ...(options.output ? ["--output", options.output] : []),
    ], { stdio: "inherit" });
    child.on("close", (code) => process.exit(code ?? 0));
    return;
  }

  if (options.command === "convert-fidelity") {
    const script = join(sourceDirectory, "scripts", "convert_fidelity.py");
    const args = [script, options.input, options.output];
    if (options.report) args.push("--report", options.report);
    if (options.json) args.push("--json");
    const child = spawn("python3", args, { stdio: "inherit" });
    child.on("close", (code) => process.exit(code ?? 0));
    return;
  }

  if (options.command === "design") {
    const script = join(sourceDirectory, "scripts", "design_system_loader.py");
    const args = [script, options.action];
    if (options.action === "list") {
      if (options.category) args.push("--category", options.category);
      if (options.tag) args.push("--tag", options.tag);
    } else if (options.action === "get") {
      args.push(options.name);
    }
    const child = spawn("python3", args, { stdio: "inherit" });
    child.on("close", (code) => process.exit(code ?? 0));
    return;
  }

  const { server, url } = await startEditorServer({ port: options.port });
  console.log(`Open PPTD viewer is running at ${url}`);
  console.log("Press Ctrl+C to stop the server.");
  if (options.open) openBrowser(url);

  const shutdown = () => server.close(() => process.exit(0));
  process.once("SIGINT", shutdown);
  process.once("SIGTERM", shutdown);
}

main().catch((error) => {
  console.error(`Error: ${error.message}`);
  process.exitCode = 1;
});
