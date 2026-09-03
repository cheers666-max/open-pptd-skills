import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { create } from "fontkit";
import { assetIdFrom, assetUri } from "../assets/refs.mjs";

const execFileAsync = promisify(execFile);

function dataUrlBytes(source) {
  const match = String(source ?? "").match(/^data:([^;,]+)?;base64,(.+)$/u);
  return match ? Buffer.from(match[2], "base64") : null;
}

function normalizeStyle(value, subfamily = "") {
  if (value) return String(value);
  const name = String(subfamily).toLowerCase();
  const bold = /bold|black|heavy|semibold|demibold/u.test(name);
  const italic = /italic|oblique/u.test(name);
  if (bold && italic) return "boldItalic";
  if (bold) return "bold";
  if (italic) return "italic";
  return "regular";
}

function digest(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

async function subsetFontBytes(bytes, {
  text = "",
  command = "pyftsubset",
  strict = false,
  extension = ".ttf",
} = {}) {
  const value = String(text ?? "");
  if (!value) {
    const error = new Error("Font subsetting requires the text used by the deck");
    error.code = "font-subset-text-empty";
    if (strict) throw error;
    return { bytes, applied: false, warning: error.code, command };
  }
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), "open-ppt-font-subset-"));
  const inputPath = path.join(temporary, `input${extension === ".otf" ? ".otf" : ".ttf"}`);
  const outputPath = path.join(temporary, "subset.ttf");
  try {
    await fs.writeFile(inputPath, bytes);
    const args = [
      inputPath,
      `--output-file=${outputPath}`,
      `--text=${value}`,
      "--layout-features=*",
      "--name-IDs=*",
      "--name-languages=*",
      "--glyph-names",
      "--symbol-cmap",
      "--legacy-cmap",
      "--notdef-glyph",
      "--notdef-outline",
    ];
    let version = null;
    try {
      const versionResult = await execFileAsync(command, ["--version"], { maxBuffer: 1024 * 1024 });
      version = String(versionResult.stdout ?? versionResult.stderr ?? "").trim().slice(0, 200) || null;
    } catch {
      // The actual invocation below provides the authoritative failure.
    }
    await execFileAsync(command, args, { maxBuffer: 8 * 1024 * 1024 });
    const subset = await fs.readFile(outputPath);
    if (subset.length < 32) throw new Error("pyftsubset produced an invalid font file");
    return { bytes: subset, applied: true, command, version };
  } catch (error) {
    const wrapped = new Error(`Font subsetting failed: ${error.message}`);
    wrapped.code = "font-subset-failed";
    wrapped.cause = error;
    if (strict) throw wrapped;
    return { bytes, applied: false, warning: wrapped.code, command, error: wrapped.message };
  } finally {
    await fs.rm(temporary, { recursive: true, force: true });
  }
}

async function bytesFromAsset(asset, assetResolver = null) {
  const assetId = assetIdFrom(asset);
  const resolved = assetId
    ? await (typeof assetResolver === "function" ? assetResolver(assetId) : Promise.reject(new Error(`Font asset reference cannot be resolved without an assetResolver: ${assetId}`)))
    : asset;
  if (Buffer.isBuffer(resolved) || resolved instanceof Uint8Array) return Buffer.from(resolved);
  if (Buffer.isBuffer(resolved?.data) || resolved?.data instanceof Uint8Array) return Buffer.from(resolved.data);
  const source = typeof resolved === "string"
    ? resolved
    : resolved?.absolutePath ?? resolved?.path ?? resolved?.file ?? resolved?.source;
  const dataUrl = dataUrlBytes(source);
  if (dataUrl) return dataUrl;
  if (!source || /^https?:\/\//iu.test(String(source))) throw new Error("Embedded font source must be a local path or data URL");
  return fs.readFile(String(source));
}

function parseFont(bytes, faceIndex = 0) {
  const parsed = create(bytes);
  const font = Array.isArray(parsed?.fonts) ? parsed.fonts[faceIndex] : parsed;
  if (!font?.familyName) throw new Error("Font file does not expose a usable family name");
  return font;
}

/**
 * Load and validate font files for a PowerPoint presentation. PowerPoint
 * expects the font part to contain the TTF/OTF bytes; it does not use the
 * WordprocessingML .odttf obfuscation path for presentation fonts.
 */
export async function prepareEmbeddedFonts(fontAssets = [], {
  allowRestricted = false,
  assetResolver = null,
  subset = false,
  subsetText = "",
  subsetCommand = "pyftsubset",
  strictSubset = false,
} = {}) {
  const prepared = [];
  const seen = new Set();
  for (const [index, asset] of (Array.isArray(fontAssets) ? fontAssets : []).entries()) {
    const bytes = await bytesFromAsset(asset, assetResolver);
    const originalContentHash = digest(bytes);
    const font = parseFont(bytes, Number(asset?.faceIndex ?? 0));
    const family = String(asset?.family ?? font.familyName).trim();
    const style = normalizeStyle(asset?.style, font.subfamilyName);
    const key = `${family.toLowerCase()}\u0000${style}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const fsType = font["OS/2"]?.fsType ?? {};
    const restricted = Boolean(fsType.noEmbedding || fsType.bitmapOnly);
    if (restricted && !allowRestricted) {
      throw new Error(`Font ${family} is marked as non-embeddable by its OS/2 fsType flags`);
    }
    const sourceValue = asset?.path ?? asset?.file ?? asset?.source ?? "";
    const extension = /\.otf(?:$|[?#])/iu.test(String(sourceValue)) ? ".otf" : ".ttf";
    const subsetResult = subset
      ? await subsetFontBytes(bytes, { text: subsetText, command: subsetCommand, strict: strictSubset, extension })
      : { bytes, applied: false, warning: null, command: null, version: null };
    const outputBytes = subsetResult.bytes;
    // Re-parse the emitted bytes so a malformed subset cannot enter a PPTX.
    parseFont(outputBytes, Number(asset?.faceIndex ?? 0));
    prepared.push({
      id: asset?.id ?? `font-${index + 1}`,
      family,
      style,
      bytes: outputBytes,
      contentHash: digest(outputBytes),
      originalContentHash,
      originalSize: bytes.byteLength,
      subset: subsetResult.applied,
      ...(subsetResult.warning ? { subsetWarning: subsetResult.warning } : {}),
      ...(subsetResult.error ? { subsetError: subsetResult.error } : {}),
      ...(subsetResult.command ? { subsetCommand: subsetResult.command } : {}),
      ...(subsetResult.version ? { subsetToolVersion: subsetResult.version } : {}),
      fileName: `font${prepared.length + 1}.fntdata`,
      pitchFamily: String(asset?.pitchFamily ?? "34"),
      charset: String(asset?.charset ?? (/\p{Script=Han}/u.test(family) ? "128" : "0")),
      embeddability: restricted ? "restricted-overridden" : fsType.editable ? "editable" : fsType.viewOnly ? "preview-print" : "unknown",
      source: assetIdFrom(asset) ? assetUri(assetIdFrom(asset)) : asset?.path ?? asset?.file ?? (asset?.source?.startsWith?.("data:") ? "data-url" : asset?.source ?? null),
    });
  }
  return prepared;
}

export function embeddedFontManifest(fonts = []) {
  return fonts.map((font) => ({
    id: font.id,
    family: font.family,
    style: font.style,
    fileName: font.fileName,
    contentHash: font.contentHash,
    originalContentHash: font.originalContentHash,
    originalSize: font.originalSize,
    size: font.bytes.byteLength,
    subset: font.subset === true,
    ...(font.subsetWarning ? { subsetWarning: font.subsetWarning } : {}),
    ...(font.subsetError ? { subsetError: font.subsetError } : {}),
    ...(font.subsetCommand ? { subsetCommand: font.subsetCommand } : {}),
    ...(font.subsetToolVersion ? { subsetToolVersion: font.subsetToolVersion } : {}),
    embeddability: font.embeddability,
    source: font.source,
  }));
}
