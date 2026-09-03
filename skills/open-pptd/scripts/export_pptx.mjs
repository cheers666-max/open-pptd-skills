#!/usr/bin/env node
/**
 * Export a PPTD project to an editable .pptx with the bundled local OOXML
 * engine (vendor/open-ppt-engine). Fully local: no browser, no remote editor,
 * no network service. Remote http(s) images referenced by the deck are
 * prefetched into a local cache so they embed as real bytes.
 *
 * Usage:
 *   node export_pptx.mjs <deck.pptd | project-dir> [options]
 *
 * Options:
 *   --output, -o <path>     Output .pptx path (default: <project>/<manifest name>.pptx)
 *   --force                 Overwrite an existing output file
 *   --transition <fade|none>  Slide transition written to every slide (default: fade)
 *   --embed-fonts           Embed font assets when the deck provides them (default: off)
 *   --font-profile <name>   Engine font profile, e.g. "open-source" (Noto Sans SC)
 *   --json                  Print a JSON summary instead of human-readable output
 *   -h, --help              Show this help
 *
 * Dependencies (yaml, sharp, jszip, fontkit) are resolved from the nearest
 * node_modules; on first run inside an installed skill directory they are
 * installed automatically into scripts/node_modules via npm.
 */

import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const SCRIPTS_DIR = path.dirname(fileURLToPath(import.meta.url));
const ADAPTER_URL = pathToFileURL(
  path.join(SCRIPTS_DIR, "vendor", "open-ppt-engine", "adapters", "pptd.mjs"),
).href;

const ENGINE_DEPENDENCIES = {
  yaml: "^2.4.2",
  sharp: "^0.33.2",
  jszip: "^3.10.1",
  fontkit: "^2.0.2",
};

function isModuleNotFound(error) {
  return (
    error &&
    (error.code === "ERR_MODULE_NOT_FOUND" ||
      /Cannot find (package|module)/.test(String(error.message)))
  );
}

function bootstrapDependencies() {
  const nodeModulesPath = path.join(SCRIPTS_DIR, "node_modules");
  if (fs.existsSync(nodeModulesPath)) {
    return; // dependencies already installed
  }
  const pkgPath = path.join(SCRIPTS_DIR, "package.json");
  if (!fs.existsSync(pkgPath)) {
    fs.writeFileSync(
      pkgPath,
      JSON.stringify(
        {
          name: "open-pptd-scripts",
          private: true,
          type: "module",
          dependencies: ENGINE_DEPENDENCIES,
        },
        null,
        2,
      ) + "\n",
    );
  }
  console.error("[export_pptx] installing engine dependencies into scripts/ (first run)…");
  const result = spawnSync(
    "npm",
    ["install", "--no-audit", "--no-fund", "--loglevel=error"],
    { cwd: SCRIPTS_DIR, stdio: "inherit" },
  );
  if (result.error) {
    throw new Error(
      `failed to run npm (${result.error.message}); install Node.js 18+ from https://nodejs.org`,
    );
  }
  if (result.status !== 0) {
    throw new Error("npm install failed inside the skill's scripts/ directory");
  }
}

async function importEngine() {
  try {
    return await import(ADAPTER_URL);
  } catch (error) {
    if (!isModuleNotFound(error)) throw error;
    bootstrapDependencies();
    return await import(ADAPTER_URL);
  }
}

function printHelp() {
  console.log(`Export a PPTD project to .pptx with the local OOXML engine.

Usage:
  node export_pptx.mjs <deck.pptd | project-dir> [options]

Options:
  --output, -o <path>       Output .pptx path (default: <project>/<manifest name>.pptx)
  --force                   Overwrite an existing output file
  --transition <fade|none>  Slide transition for every slide (default: fade)
  --embed-fonts             Embed font assets when available (default: off)
  --font-profile <name>     Engine font profile, e.g. "open-source"
  --json                    Print a JSON summary
  -h, --help                Show this help
`);
}

function parseArgs(argv) {
  const options = {
    input: null,
    output: null,
    force: false,
    transition: "fade",
    embedFonts: false,
    fontProfile: undefined,
    json: false,
    help: false,
  };
  const args = [...argv];
  while (args.length > 0) {
    const arg = args.shift();
    switch (arg) {
      case "--output":
      case "-o": {
        const value = args.shift();
        if (!value || value.startsWith("-")) throw new Error("--output requires a path");
        options.output = value;
        break;
      }
      case "--force":
        options.force = true;
        break;
      case "--transition": {
        const value = args.shift();
        if (!value || !["fade", "none"].includes(value)) {
          throw new Error("--transition must be 'fade' or 'none'");
        }
        options.transition = value;
        break;
      }
      case "--embed-fonts":
        options.embedFonts = true;
        break;
      case "--font-profile": {
        const value = args.shift();
        if (!value || value.startsWith("-")) throw new Error("--font-profile requires a name");
        options.fontProfile = value;
        break;
      }
      case "--json":
        options.json = true;
        break;
      case "--help":
      case "-h":
        options.help = true;
        break;
      default:
        if (arg.startsWith("-")) throw new Error(`unknown argument: ${arg}`);
        if (options.input) throw new Error(`unexpected extra argument: ${arg}`);
        options.input = arg;
    }
  }
  return options;
}

function resolveManifest(inputPath) {
  const resolved = path.resolve(inputPath);
  if (!fs.existsSync(resolved)) throw new Error(`deck not found: ${inputPath}`);
  const stat = fs.statSync(resolved);
  if (stat.isFile()) {
    if (!resolved.toLowerCase().endsWith(".pptd")) {
      throw new Error(`expected a .pptd manifest: ${resolved}`);
    }
    return { projectDir: path.dirname(resolved), manifestPath: resolved };
  }
  const candidates = fs
    .readdirSync(resolved)
    .filter((entry) => entry.toLowerCase().endsWith(".pptd"));
  if (candidates.length !== 1) {
    throw new Error(
      `expected exactly one .pptd manifest in ${resolved}, found ${candidates.length}`,
    );
  }
  return { projectDir: resolved, manifestPath: path.join(resolved, candidates[0]) };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    printHelp();
    return;
  }
  if (!options.input) {
    printHelp();
    process.exitCode = 1;
    return;
  }

  const { projectDir, manifestPath } = resolveManifest(options.input);
  const manifestName = path.basename(manifestPath).replace(/\.pptd$/i, "");
  const outputPath = path.resolve(options.output ?? path.join(projectDir, `${manifestName}.pptx`));
  if (fs.existsSync(outputPath) && !options.force) {
    throw new Error(`output already exists (pass --force to replace it): ${outputPath}`);
  }
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });

  const { exportPptdProject } = await importEngine();
  const { report } = await exportPptdProject(manifestPath, outputPath, {
    transition:
      options.transition === "none"
        ? false
        : { type: "fade", speed: "fast", advanceOnClick: true },
    embedFonts: options.embedFonts,
    fontProfile: options.fontProfile,
  });

  const stat = fs.statSync(outputPath);
  const warnings = report?.warnings ?? [];
  const summary = {
    ok: true,
    deck: manifestPath,
    output: outputPath,
    bytes: stat.size,
    warnings: warnings.length,
  };
  if (report?.prefetch) {
    summary.prefetch = {
      total: report.prefetch.total,
      fetched: report.prefetch.fetched,
      reused: report.prefetch.reused,
      failures: report.prefetch.failures.length,
    };
  }

  if (options.json) {
    console.log(JSON.stringify(summary, null, 2));
    return;
  }
  console.log(`✅ PPTX exported → ${outputPath} (${stat.size} bytes)`);
  if (summary.prefetch) {
    const p = summary.prefetch;
    console.log(
      `   remote assets: ${p.fetched} fetched, ${p.reused} cached, ${p.failures} failed (of ${p.total})`,
    );
  }
  if (warnings.length > 0) {
    console.log(`   ⚠ ${warnings.length} engine warning(s); re-run with --json and inspect the report for details`);
  }
}

main().catch((error) => {
  console.error(`❌ PPTX export failed: ${error.message}`);
  process.exitCode = 1;
});
