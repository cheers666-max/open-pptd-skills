#!/usr/bin/env node
/**
 * Build fa-icons.mjs — Font Awesome Free SVG icons → offline icon registry
 *
 * Reads SVG files from @fortawesome/fontawesome-free and emits a single
 * ES module that exports an icon registry for offline use.
 *
 * Usage:
 *   node build-fa-icons.mjs [output-dir]
 *
 * Requires: npm install @fortawesome/fontawesome-free (temp, no-save)
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FA_DIR = fs.existsSync(path.resolve(__dirname, "../../node_modules/@fortawesome/fontawesome-free/svgs"))
  ? path.resolve(__dirname, "../../node_modules/@fortawesome/fontawesome-free/svgs")
  : path.resolve("/tmp/node_modules/@fortawesome/fontawesome-free/svgs");
const OUTPUT_DIR = process.argv[2] || __dirname;

function svgToIcon(svgContent) {
  const vbMatch = svgContent.match(/viewBox="([^"]+)"/);
  const viewBox = vbMatch ? vbMatch[1] : "0 0 512 512";
  let inner = svgContent
    .replace(/<svg[^>]*>/, "")
    .replace(/<\/svg>\s*$/, "")
    .replace(/<!--[\s\S]*?-->/g, "")
    .trim();
  return { viewBox, inner };
}

function collectIcons(subdir, prefix) {
  const dir = path.join(FA_DIR, subdir);
  if (!fs.existsSync(dir)) return {};
  const result = {};
  for (const f of fs.readdirSync(dir)) {
    if (!f.endsWith(".svg")) continue;
    const name = f.replace(".svg", "");
    const id = `${prefix}:${name}`;
    result[id] = svgToIcon(fs.readFileSync(path.join(dir, f), "utf-8"));
  }
  return result;
}

const icons = {
  ...collectIcons("solid", "fas"),
  ...collectIcons("regular", "far"),
  ...collectIcons("brands", "fab"),
};

const keys = Object.keys(icons);

const moduleCode = `/**
 * Font Awesome Free 7.3.1 — offline icon registry
 * ${keys.length} icons
 * License: CC BY 4.0 / SIL OFL 1.1 — https://fontawesome.com/license/free
 *
 * Each icon: { viewBox: "0 0 W H", inner: "<path .../>" }
 *
 * Usage:
 *   import { ICONS, injectSprite, ICON_COUNT } from "./fa-icons.mjs";
 *   injectSprite(document);
 *   // then: <svg class="fa-icon"><use href="#fas:house"/></svg>
 *
 * For self-contained export (no sprite dependency):
 *   inlineIcon("fas:house", "#333") → <svg ...>...</svg>
 */
export const ICON_COUNT = ${keys.length};

export const ICONS = ${JSON.stringify(icons, null, 2)};

let _spriteInjected = false;

export function injectSprite(doc = document) {
  if (_spriteInjected) return;
  const symbols = Object.entries(ICONS)
    .map(([id, v]) => \`<symbol id="\${id}" viewBox="\${v.viewBox}">\${v.inner}</symbol>\`)
    .join("");
  const container = doc.createElement("div");
  container.innerHTML = \`<svg xmlns="http://www.w3.org/2000/svg" style="display:none">\${symbols}</svg>\`;
  doc.body.appendChild(container.firstElementChild);
  _spriteInjected = true;
}

export function inlineIcon(name, color = "currentColor") {
  const icon = ICONS[name];
  if (!icon) return \`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="24" height="24"><text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" font-size="10">?</text></svg>\`;
  return \`<svg xmlns="http://www.w3.org/2000/svg" viewBox="\${icon.viewBox}" fill="\${color}" width="24" height="24">\${icon.inner}</svg>\`;
}
`;

const outPath = path.join(OUTPUT_DIR, "fa-icons.mjs");
fs.writeFileSync(outPath, moduleCode, "utf-8");
const stats = fs.statSync(outPath);
console.log(`✅ fa-icons.mjs written → ${outPath}`);
console.log(`   ${keys.length} icons, ${(stats.size / 1024 / 1024).toFixed(2)} MB`);
