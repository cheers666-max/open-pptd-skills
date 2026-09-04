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

Install options:
  --target <directory>  Skills directory (default: ~/.agents/skills)

Re-running install replaces an existing ${SKILL_NAME} installation.
Run "open-pptd-skills serve --help" for server options.
`);
}

function parseArguments(arguments_) {
  const args = [...arguments_];
  const command = args[0] === "install" || args[0] === "serve" || args[0] === "validate" ? args.shift() : "install";
  const options = command === "serve"
    ? { command, open: false, port: 55173 }
    : command === "validate"
    ? { command, project: undefined, manifest: undefined, targetWidth: 1280, minImageScale: 0.6, output: undefined, json: false }
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
