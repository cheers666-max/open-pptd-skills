import fs from "node:fs/promises";
import crypto from "node:crypto";
import JSZip from "jszip";
import sharp from "sharp";
import { resolveDeckLayout } from "../layout/resolve.mjs";
import { walkElements } from "../layout/elements.mjs";
import { collectDeckText } from "../layout/text-content.mjs";
import { normalizeGeometry } from "../ir/geometries.mjs";
import { textStyleLevels } from "../ir/text-styles.mjs";
import { assertChartData } from "../ir/charts.mjs";
import { prepareEmbeddedFonts } from "./embedded-fonts.mjs";
import { resolveAssetReference } from "../assets/refs.mjs";
import { sniffImageType } from "../assets/image-bytes.mjs";
import { transitionXml } from "../ir/transitions.mjs";
import { timingXml } from "../ir/animations.mjs";
import { formulaOmmlXml, formulaPlainText, normalizeFormula } from "../ir/formulas.mjs";
import { DIAGRAM_COLORS_CONTENT_TYPE, DIAGRAM_COLORS_REL, DIAGRAM_DATA_CONTENT_TYPE, DIAGRAM_DATA_REL, DIAGRAM_DRAWING_CONTENT_TYPE, DIAGRAM_DRAWING_REL, DIAGRAM_LAYOUT_CONTENT_TYPE, DIAGRAM_LAYOUT_REL, DIAGRAM_QUICK_STYLE_REL, DIAGRAM_STYLE_CONTENT_TYPE, smartArtColorsXml, smartArtDataXml, smartArtDrawingRelationshipId, smartArtDrawingXml, smartArtFrameXml, smartArtLayoutXml, smartArtQuickStyleXml, smartArtNativePartsAreFresh } from "../ir/smartart.mjs";
import { containPosition, coverCrop, focalPointCrop, normalizeCrop } from "./image-fit.mjs";
import { compileDiagram } from "../layout/diagrams.mjs";

const EMU_PER_PX = 914400 / 96;

function emu(value) {
  return Math.round(Number(value) * EMU_PER_PX);
}

function escapeXml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function bytesDigest(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function hex(value, fallback = "FFFFFF") {
  const raw = typeof value === "object" ? (value?.color ?? value?.value ?? fallback) : value;
  const normalized = String(raw ?? fallback).replace(/^#/, "");
  return normalized.length >= 6 ? normalized.slice(0, 6).toUpperCase() : fallback;
}

const DEFAULT_TABLE_STYLE_ID = "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}";
const TABLE_STYLE_SCHEME_COLORS = new Set([
  "dk1", "lt1", "dk2", "lt2", "tx1", "tx2", "bg1", "bg2",
  "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink",
]);
const TABLE_STYLE_CONFIG_KEYS = new Set([
  "tableStyle",
  "tableStyleId",
  "tableStyleName",
  "headerFill",
  "bandFill",
  "band2Fill",
  "bandColumn",
  "bandCol",
  "band1V",
  "band2V",
  "firstColumn",
  "firstColumnFill",
  "firstColumnStyle",
  "lastColumn",
  "lastColumnFill",
  "lastColumnStyle",
  "firstRowStyle",
  "headerStyle",
  "lastRow",
  "lastRowStyle",
  "fillRef",
  "bodyStyles",
]);

function stableTableStyleValue(value) {
  if (Array.isArray(value)) return `[${value.map(stableTableStyleValue).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableTableStyleValue(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function normalizeGuid(value) {
  const raw = String(value ?? "").replace(/[{}-]/gu, "").toUpperCase();
  if (!/^[0-9A-F]{32}$/u.test(raw)) return null;
  return `{${raw.slice(0, 8)}-${raw.slice(8, 12)}-${raw.slice(12, 16)}-${raw.slice(16, 20)}-${raw.slice(20)}}`;
}

function generatedTableStyleId(value) {
  const digest = bytesDigest(Buffer.from(stableTableStyleValue(value), "utf8"));
  return normalizeGuid(digest.slice(0, 32));
}

export function tableStyleBase(style = {}) {
  return Object.fromEntries(Object.entries(style).filter(([key]) => !TABLE_STYLE_CONFIG_KEYS.has(key)));
}

export function tableStyleDefinitionFor(style = {}) {
  const explicit = style.tableStyle && typeof style.tableStyle === "object" ? style.tableStyle : {};
  const explicitRegions = explicit.regions && typeof explicit.regions === "object" ? explicit.regions : explicit;
  const hasSemanticStyle = Object.keys(explicit).length > 0 || [
    "headerFill", "bandFill", "band2Fill", "bandColumn", "bandCol", "band1V", "band2V",
    "firstColumn", "firstColumnFill", "firstColumnStyle", "lastColumn", "lastColumnFill", "lastColumnStyle",
    "firstRowStyle", "headerStyle", "lastRow", "lastRowStyle", "fillRef", "bodyStyles",
  ].some((key) => style[key] !== undefined);
  if (!hasSemanticStyle) return null;
  const seed = {
    ...Object.fromEntries(Object.entries(style).filter(([key]) => TABLE_STYLE_CONFIG_KEYS.has(key) && key !== "tableStyleId" && key !== "tableStyleName")),
    base: tableStyleBase({ fontFamily: "Aptos", fontSize: 16, color: "#1E1E1E", ...style }),
    ...(explicitRegions && typeof explicitRegions === "object" ? { regions: explicitRegions } : {}),
  };
  const id = normalizeGuid(style.tableStyleId ?? explicit.id) ?? generatedTableStyleId(seed);
  const bodyStyles = Array.isArray(style.bodyStyles) ? style.bodyStyles : [];
  const firstRow = explicitRegions.firstRow ?? {
    ...(style.headerFill ? { fill: style.headerFill } : {}),
    ...(style.headerStyle && typeof style.headerStyle === "object" ? style.headerStyle : {}),
    ...(style.firstRowStyle && typeof style.firstRowStyle === "object" ? style.firstRowStyle : {}),
  };
  const lastRow = explicitRegions.lastRow ?? style.lastRowStyle;
  const firstColumn = explicitRegions.firstCol ?? explicitRegions.firstColumn ?? {
    ...(style.firstColumnFill ? { fill: style.firstColumnFill } : {}),
    ...(style.firstColumnStyle && typeof style.firstColumnStyle === "object" ? style.firstColumnStyle : {}),
  };
  const lastColumn = explicitRegions.lastCol ?? explicitRegions.lastColumn ?? {
    ...(style.lastColumnFill ? { fill: style.lastColumnFill } : {}),
    ...(style.lastColumnStyle && typeof style.lastColumnStyle === "object" ? style.lastColumnStyle : {}),
  };
  const regions = {
    wholeTbl: explicitRegions.wholeTbl ?? explicitRegions.wholeTable ?? tableStyleBase({ fontFamily: "Aptos", fontSize: 16, color: "#1E1E1E", ...style }),
    ...(firstRow ? { firstRow } : {}),
    ...(lastRow ? { lastRow } : {}),
    ...(firstColumn ? { firstCol: firstColumn } : {}),
    ...(lastColumn ? { lastCol: lastColumn } : {}),
    ...(explicitRegions.band1H ? { band1H: explicitRegions.band1H } : (style.bandFill ? { band1H: { fill: style.bandFill } } : {})),
    ...(explicitRegions.band2H ? { band2H: explicitRegions.band2H } : (style.band2Fill ? { band2H: { fill: style.band2Fill } } : (bodyStyles[0] ? { band1H: bodyStyles[0] } : {}))),
    ...(explicitRegions.band1V ? { band1V: explicitRegions.band1V } : (style.band1V ? { band1V: style.band1V } : {})),
    ...(explicitRegions.band2V ? { band2V: explicitRegions.band2V } : (style.band2V ? { band2V: style.band2V } : {})),
    ...(explicitRegions.nwCell ? { nwCell: explicitRegions.nwCell } : {}),
    ...(explicitRegions.neCell ? { neCell: explicitRegions.neCell } : {}),
    ...(explicitRegions.swCell ? { swCell: explicitRegions.swCell } : {}),
    ...(explicitRegions.seCell ? { seCell: explicitRegions.seCell } : {}),
  };
  const corner = (row, column, key) => {
    if (regions[key]) return;
    const rowStyle = regions[row] ?? {};
    const columnStyle = regions[column] ?? {};
    if (Object.keys(rowStyle).length || Object.keys(columnStyle).length) regions[key] = mergeTableStyleValues(rowStyle, columnStyle);
  };
  corner("firstRow", "firstCol", "nwCell");
  corner("firstRow", "lastCol", "neCell");
  corner("lastRow", "firstCol", "swCell");
  corner("lastRow", "lastCol", "seCell");
  return {
    id,
    name: String(style.tableStyleName ?? explicit.name ?? "Open PPT Table Style"),
    regions: Object.fromEntries(Object.entries(regions).filter(([, region]) => region && typeof region === "object" && Object.keys(region).length > 0)),
  };
}

export function tableStyleIdFor(style = {}) {
  return tableStyleDefinitionFor(style)?.id ?? null;
}

function mergeTableStyleValues(base = {}, override = {}) {
  const result = { ...(base ?? {}), ...(override ?? {}) };
  if (base?.border || override?.border) {
    const baseBorder = typeof base?.border === "object" ? base.border : {};
    const overrideBorder = typeof override?.border === "object" ? override.border : {};
    result.border = { ...baseBorder, ...overrideBorder };
    for (const side of ["left", "right", "top", "bottom", "insideH", "insideV"]) {
      if (baseBorder[side] && overrideBorder[side] && typeof baseBorder[side] === "object" && typeof overrideBorder[side] === "object") {
        result.border[side] = { ...baseBorder[side], ...overrideBorder[side] };
      }
    }
  }
  return result;
}

export function tableStyleRegionStyle(definition, rowIndex, columnIndex, rowCount, columnCount, toggles = {}) {
  if (!definition?.regions) return {};
  const regions = definition.regions;
  const result = { ...(regions.wholeTbl ?? {}) };
  const apply = (key) => Object.assign(result, mergeTableStyleValues(result, regions[key] ?? {}));
  if (toggles.bandRow && rowIndex > 0 && rowIndex < rowCount - 1) apply((rowIndex - 1) % 2 === 0 ? "band1H" : "band2H");
  if (toggles.bandColumn) apply(columnIndex % 2 === 0 ? "band1V" : "band2V");
  if (toggles.lastCol && columnIndex === columnCount - 1) apply("lastCol");
  if (toggles.firstCol && columnIndex === 0) apply("firstCol");
  if (toggles.lastRow && rowIndex === rowCount - 1) apply("lastRow");
  if (rowIndex === rowCount - 1 && columnIndex === columnCount - 1) apply("seCell");
  if (rowIndex === rowCount - 1 && columnIndex === 0) apply("swCell");
  if (toggles.firstRow && rowIndex === 0) apply("firstRow");
  if (rowIndex === 0 && columnIndex === columnCount - 1) apply("neCell");
  if (rowIndex === 0 && columnIndex === 0) apply("nwCell");
  return result;
}

function colorTransformXml(value) {
  if (!value || typeof value !== "object") return "";
  const transforms = [];
  for (const key of ["tint", "shade", "lumMod", "lumOff", "satMod", "satOff", "alpha"]) {
    if (value[key] === undefined) continue;
    const raw = Number(value[key]);
    if (!Number.isFinite(raw)) continue;
    const normalized = raw <= 1 ? raw * 100000 : raw <= 100 ? raw * 1000 : raw;
    transforms.push(`<a:${key} val="${Math.round(Math.max(0, Math.min(100000, normalized)))}"/>`);
  }
  return transforms.join("");
}

function colorChoiceXml(value, fallback = "000000", fallbackScheme = null) {
  const objectValue = value && typeof value === "object" ? value : null;
  const raw = objectValue?.scheme ?? objectValue?.color ?? objectValue?.value ?? value;
  const normalizeScheme = (candidate) => {
    if (candidate === undefined || candidate === null || candidate === "") return null;
    const normalized = String(candidate).replace(/^#/u, "").toLowerCase();
    return TABLE_STYLE_SCHEME_COLORS.has(normalized) ? normalized : null;
  };
  // A fallback scheme applies only when the caller did not provide a color.
  // Applying it unconditionally would silently turn explicit RGB values such
  // as #FFFFFF into tx1/accent1, which is especially damaging for table
  // header/corner overrides.
  const scheme = normalizeScheme(objectValue?.scheme)
    ?? normalizeScheme(raw)
    ?? ((raw === undefined || raw === null || raw === "") ? normalizeScheme(fallbackScheme) : null);
  if (scheme && TABLE_STYLE_SCHEME_COLORS.has(scheme)) return `<a:schemeClr val="${escapeXml(scheme)}">${colorTransformXml(objectValue)}</a:schemeClr>`;
  const colorValue = raw === undefined || raw === null || raw === "" ? fallback : raw;
  return `<a:srgbClr val="${hex(colorValue, fallback)}">${alphaXml(objectValue ?? colorValue)}${colorTransformXml(objectValue)}</a:srgbClr>`;
}

function tableStyleColorXml(value, fallback = "tx1") {
  return colorChoiceXml(value, fallback === "tx1" ? "1E1E1E" : "FFFFFF", fallback);
}

function tableStyleTextXml(style = {}) {
  const hasText = ["fontFamily", "fontRef", "color", "fontSize", "bold", "italic"].some((key) => style[key] !== undefined);
  if (!hasText) return "";
  const attrs = [
    style.bold !== undefined ? `b="${style.bold ? "on" : "off"}"` : "",
    style.italic !== undefined ? `i="${style.italic ? "on" : "off"}"` : "",
  ].filter(Boolean).join(" ");
  const fontFamily = style.fontFamily;
  const fontXml = fontFamily
    ? `<a:font><a:latin typeface="${escapeXml(fontFamily)}"/><a:ea typeface="${escapeXml(style.eastAsiaFontFamily ?? fontFamily)}"/><a:cs typeface="${escapeXml(style.complexScriptFontFamily ?? fontFamily)}"/></a:font>`
    : "";
  const fontRef = style.fontRef ?? (style.fontFamily ? "minor" : "minor");
  const color = style.color ?? "tx1";
  return `<a:tcTxStyle${attrs ? ` ${attrs}` : ""}>${fontXml}<a:fontRef idx="${escapeXml(fontRef)}">${tableStyleColorXml(color)}</a:fontRef>${tableStyleColorXml(color)}</a:tcTxStyle>`;
}

function tableStyleReferenceXml(name, value, fallbackColor = null) {
  if (value === undefined || value === null || value === false) return "";
  const normalized = typeof value === "object" ? value : typeof value === "number" ? { idx: value } : { idx: 0, color: value };
  const idx = Math.max(0, Math.round(Number(normalized.idx ?? normalized.index ?? 0) || 0));
  const colorValue = normalized.color ?? normalized.scheme ?? normalized.value ?? fallbackColor;
  const colorXml = colorValue ? colorChoiceXml(colorValue, "000000", normalized.scheme ?? null) : "";
  return `<a:${name} idx="${idx}">${colorXml}</a:${name}>`;
}

function tableStyleBorderXml(style = {}) {
  const border = typeof style.border === "object" ? style.border : {};
  const sides = {
    left: border.left ?? { color: style.borderColor, width: style.borderWidth },
    right: border.right ?? { color: style.borderColor, width: style.borderWidth },
    top: border.top ?? { color: style.borderColor, width: style.borderWidth },
    bottom: border.bottom ?? { color: style.borderColor, width: style.borderWidth },
    insideH: border.insideH,
    insideV: border.insideV,
  };
  const entries = Object.entries(sides).filter(([, value]) => value !== undefined && value !== null && value !== false);
  if (!entries.length) return "";
  const nodes = entries.map(([side, value]) => {
    const normalized = typeof value === "object" ? value : typeof value === "number" ? { width: value } : { color: value };
    const width = Math.max(0, Number(normalized.width ?? 1) || 0);
    const lineAttrs = [
      normalized.cap ? `cap="${escapeXml(normalized.cap)}"` : "",
      normalized.cmpd || normalized.compound ? `cmpd="${escapeXml(normalized.cmpd ?? normalized.compound)}"` : "",
      normalized.algn ? `algn="${escapeXml(normalized.algn)}"` : "",
    ].filter(Boolean).join(" ");
    const dash = normalized.dash ? `<a:prstDash val="${escapeXml(normalized.dash)}"/>` : "";
    const lineReference = normalized.lineRef ?? normalized.lnRef;
    const line = lineReference !== undefined
      ? tableStyleReferenceXml("lnRef", lineReference, normalized.color ?? "tx1")
      : width > 0
        ? `<a:ln w="${Math.max(1, emu(width))}"${lineAttrs ? ` ${lineAttrs}` : ""}>${solidFill(normalized.color ?? "#D3CEC3")}${dash}</a:ln>`
        : '<a:ln w="0"><a:noFill/></a:ln>';
    return `<a:${side}>${line}</a:${side}>`;
  }).join("");
  return `<a:tcBdr>${nodes}</a:tcBdr>`;
}

function tableStyleRegionXml(name, region = {}) {
  const text = tableStyleTextXml(region);
  const border = tableStyleBorderXml(region);
  const fillRef = region.fillRef !== undefined ? tableStyleReferenceXml("fillRef", region.fillRef, "accent1") : "";
  const fill = !fillRef && region.fill !== undefined ? `<a:fill>${solidFill(region.fill)}</a:fill>` : "";
  if (!text && !border && !fillRef && !fill) return "";
  return `<a:${name}>${text}<a:tcStyle>${border}${fillRef}${fill}</a:tcStyle></a:${name}>`;
}

export function tableStylesXmlForDeck(deck) {
  const definitions = new Map();
  for (const definition of Array.isArray(deck.tableStyles) ? deck.tableStyles : []) {
    if (definition?.id && definition?.regions) definitions.set(definition.id, definition);
  }
  for (const slide of deck.slides ?? []) {
    walkElements(slide.elements, (element) => {
      if (element.type !== "table") return;
      const definition = tableStyleDefinitionFor(element.style ?? {});
      if (definition) definitions.set(definition.id, definition);
    });
  }
  const styles = [...definitions.values()].map((definition) => {
    const regions = Object.entries(definition.regions ?? {}).map(([name, region]) => tableStyleRegionXml(name, region)).filter(Boolean).join("");
    return `<a:tblStyle styleId="${escapeXml(definition.id)}" styleName="${escapeXml(definition.name ?? "Open PPT Table Style")}">${regions}</a:tblStyle>`;
  }).join("");
  const defaultId = [...definitions.keys()][0] ?? DEFAULT_TABLE_STYLE_ID;
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" def="${escapeXml(defaultId)}">${styles}</a:tblStyleLst>`;
}

function alpha(value) {
  if (typeof value === "number") return Math.max(0, Math.min(1, value));
  const raw = String(value ?? "").replace(/^#/, "");
  if (/^[0-9a-f]{8}$/iu.test(raw)) return parseInt(raw.slice(6), 16) / 255;
  if (typeof value === "object" && value?.alpha !== undefined) return Math.max(0, Math.min(1, Number(value.alpha)));
  if (typeof value === "object" && value?.opacity !== undefined) return Math.max(0, Math.min(1, Number(value.opacity)));
  return 1;
}

function alphaXml(value) {
  const amount = Math.round(alpha(value) * 100000);
  return amount < 100000 ? `<a:alpha val="${amount}"/>` : "";
}

function solidFill(value) {
  if (!value || value === "none" || value === "transparent") return "<a:noFill/>";
  if (typeof value === "object" && (value.type === "gradient" || Array.isArray(value.stops))) {
    const stops = (value.stops ?? []).map((stop) => {
      const rawPosition = Number(stop.position ?? stop.offset ?? 0);
      const normalizedPosition = rawPosition <= 1 ? rawPosition * 100000 : rawPosition <= 100 ? rawPosition * 1000 : rawPosition;
      const position = Math.round(Math.max(0, Math.min(100000, normalizedPosition)));
      return `<a:gs pos="${position}">${colorChoiceXml(stop.color ?? "#000000", "000000")}</a:gs>`;
    }).join("");
    const angle = Math.round(Number(value.angle ?? 0) * 60000);
    return `<a:gradFill rotWithShape="${value.rotateWithShape === false ? 0 : 1}"><a:gsLst>${stops}</a:gsLst><a:lin ang="${angle}" scaled="0"/></a:gradFill>`;
  }
  return `<a:solidFill>${colorChoiceXml(value, "000000")}</a:solidFill>`;
}

function lineXml(line = {}) {
  const width = Number(line.width ?? 0);
  if (!width) return `<a:ln w="0"><a:noFill/></a:ln>`;
  const dash = line.dash ? `<a:prstDash val="${escapeXml(line.dash)}"/>` : '<a:prstDash val="solid"/>';
  const beginArrowType = line.beginArrowType ?? line.headEnd ?? line.lineHead;
  const endArrowType = line.endArrowType ?? line.tailEnd ?? line.lineTail;
  const beginArrow = beginArrowType && beginArrowType !== "none" ? `<a:headEnd type="${escapeXml(beginArrowType)}"/>` : "";
  const endArrow = endArrowType && endArrowType !== "none" ? `<a:tailEnd type="${escapeXml(endArrowType)}"/>` : "";
  return `<a:ln w="${Math.max(1, emu(width))}">${solidFill(line.color ?? "#000000")}${dash}${beginArrow}${endArrow}</a:ln>`;
}

function effectsXml(style = {}) {
  const shadow = style.shadow;
  if (!shadow || shadow === "none") return "";
  const value = typeof shadow === "object" ? shadow : {};
  const blur = Math.max(0, emu(Number(value.blur ?? value.blurRadius ?? 3)));
  const distance = Math.max(0, emu(Number(value.distance ?? value.dist ?? 4)));
  const direction = Math.round(Number(value.angle ?? value.direction ?? 45) * 60000);
  const color = hex(value.color ?? "#000000");
  const opacity = Math.round(Math.max(0, Math.min(1, Number(value.opacity ?? 0.25))) * 100000);
  return `<a:effectLst><a:outerShdw blurRad="${blur}" dist="${distance}" dir="${direction}" rotWithShape="0"><a:srgbClr val="${color}"><a:alpha val="${opacity}"/></a:srgbClr></a:outerShdw></a:effectLst>`;
}

function transformXml(position, options = {}) {
  const rotation = Number(options.rotation ?? 0);
  const attrs = [
    rotation ? `rot="${Math.round(rotation * 60000)}"` : "",
    options.flipH ? `flipH="1"` : "",
    options.flipV ? `flipV="1"` : "",
  ].filter(Boolean).join(" ");
  return `<a:xfrm${attrs ? ` ${attrs}` : ""}><a:off x="${emu(position.left)}" y="${emu(position.top)}"/><a:ext cx="${emu(position.width)}" cy="${emu(position.height)}"/></a:xfrm>`;
}

function textStyle(run, baseStyle = {}) {
  return {
    fontFamily: run?.fontFamily ?? baseStyle.fontFamily ?? "Aptos",
    eastAsiaFontFamily: run?.eastAsiaFontFamily ?? baseStyle.eastAsiaFontFamily ?? undefined,
    fontSize: Number(run?.fontSize ?? baseStyle.fontSize ?? 16),
    color: run?.color ?? baseStyle.color ?? "#1E1E1E",
    bold: run?.bold ?? baseStyle.bold ?? false,
    italic: run?.italic ?? baseStyle.italic ?? false,
    underline: run?.underline ?? baseStyle.underline ?? false,
    strike: run?.strike ?? baseStyle.strike ?? false,
    superscript: run?.superscript ?? baseStyle.superscript ?? false,
    subscript: run?.subscript ?? baseStyle.subscript ?? false,
    baseline: run?.baseline ?? baseStyle.baseline ?? null,
    highlight: run?.highlight ?? baseStyle.highlight ?? null,
    lang: run?.lang ?? baseStyle.lang ?? "zh-CN",
    hyperlink: run?.hyperlink ?? run?.link ?? baseStyle.hyperlink ?? baseStyle.link ?? null,
  };
}

function underlineValue(value) {
  if (!value) return null;
  if (value === true) return "sng";
  return typeof value === "object" ? value.style ?? "sng" : String(value);
}

function strikeValue(value) {
  if (!value) return null;
  if (value === true) return "sngStrike";
  return String(value);
}

function baselineValue(style) {
  if (style.baseline !== null && style.baseline !== undefined && style.baseline !== "") {
    if (style.baseline === "superscript") return 30000;
    if (style.baseline === "subscript") return -40000;
    const numeric = Number(style.baseline);
    if (Number.isFinite(numeric)) return Math.round(numeric);
  }
  if (style.superscript) return 30000;
  if (style.subscript) return -40000;
  return null;
}

function highlightXml(value) {
  if (!value || value === "none" || value === "transparent") return "";
  return `<a:highlight><a:srgbClr val="${hex(value, "FFF2CC")}">${alphaXml(value)}</a:srgbClr></a:highlight>`;
}

function hyperlinkTarget(value) {
  if (value === undefined || value === null || value === "") return null;
  const target = String(value).trim();
  let parsed;
  try { parsed = new URL(target); } catch {
    const error = new Error(`Invalid hyperlink target: ${target}`);
    error.code = "invalid-hyperlink";
    throw error;
  }
  if (!["http:", "https:", "mailto:"].includes(parsed.protocol)) {
    const error = new Error(`Hyperlink protocol is not allowed: ${parsed.protocol}`);
    error.code = "invalid-hyperlink";
    throw error;
  }
  return target;
}

function runXml(run, baseStyle = {}, hyperlinkId = null) {
  const style = textStyle(run, baseStyle);
  const fontSize = Math.round(style.fontSize * 72 / 96 * 100);
  const face = escapeXml(style.fontFamily ?? themeFontTypeface(style.fontRef, "lt", "Aptos"));
  const eastAsiaFace = escapeXml(style.eastAsiaFontFamily ?? style.fontFamily ?? themeFontTypeface(style.fontRef, "ea", "Aptos"));
  const complexScriptFace = escapeXml(style.complexScriptFontFamily ?? style.fontFamily ?? themeFontTypeface(style.fontRef, "cs", "Aptos"));
  const underline = underlineValue(style.underline);
  const strike = strikeValue(style.strike);
  const baseline = baselineValue(style);
  const runAttrs = [
    `lang="${escapeXml(style.lang)}"`,
    `sz="${fontSize}"`,
    `b="${style.bold ? 1 : 0}"`,
    `i="${style.italic ? 1 : 0}"`,
    underline ? `u="${escapeXml(underline)}"` : "",
    strike ? `strike="${escapeXml(strike)}"` : "",
    baseline === null ? "" : `baseline="${baseline}"`,
  ].filter(Boolean).join(" ");
  const hyperlink = hyperlinkId ? `<a:hlinkClick r:id="${escapeXml(hyperlinkId)}"/>` : "";
  return `<a:r><a:rPr ${runAttrs}><a:solidFill><a:srgbClr val="${hex(style.color, "1E1E1E")}"/></a:solidFill>${highlightXml(style.highlight)}<a:latin typeface="${face}"/><a:ea typeface="${eastAsiaFace}"/><a:cs typeface="${complexScriptFace}"/>${hyperlink}</a:rPr><a:t>${escapeXml(run?.text ?? "")}</a:t></a:r>`;
}

function paragraphRuns(element, baseStyle = {}) {
  const source = Array.isArray(element?.runs) && element.runs.length
    ? element.runs
    : [{ text: String(element?.text ?? ""), ...baseStyle }];
  const paragraphs = [[]];
  for (const run of source) {
    const parts = String(run?.text ?? "").split("\n");
    parts.forEach((part, index) => {
      if (part) paragraphs[paragraphs.length - 1].push({ ...run, text: part });
      if (index < parts.length - 1) paragraphs.push([]);
    });
  }
  return paragraphs;
}

function integer(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number) : fallback;
}

function paragraphProperties(style = {}) {
  const bullet = style.bullet ?? style.listStyle;
  const bulletXml = bullet === true || bullet === "bullet" || bullet === "disc"
    ? `<a:buChar char="${escapeXml(style.bulletChar ?? "•")}"/>`
    : bullet === "number" || bullet === "numbered" || bullet === "decimal"
      ? `<a:buAutoNum type="arabicPeriod"/>`
      : "";
  const level = Math.max(0, Math.min(8, integer(style.bulletLevel ?? style.level, 0)));
  const defaultIndent = bulletXml ? 24 * (level + 1) : 0;
  const marginLeft = Math.max(0, Number(style.indent ?? style.marginLeft ?? defaultIndent) || 0);
  const hanging = bulletXml ? Math.max(0, Number(style.hanging ?? 12) || 0) : 0;
  const lineHeight = Number(style.lineHeight);
  const lineSpacing = Number.isFinite(lineHeight) && lineHeight > 0
    ? `<a:lnSpc><a:spcPct val="${Math.round(lineHeight * 100000)}"/></a:lnSpc>`
    : "";
  const spaceAfter = Number(style.spaceAfter ?? style.paragraphSpaceAfter);
  const after = Number.isFinite(spaceAfter) && spaceAfter > 0
    ? `<a:spcAft><a:spcPts val="${Math.round(spaceAfter * 100)}"/></a:spcAft>`
    : "";
  const attrs = [`algn="${style.align === "center" ? "ctr" : style.align === "right" ? "r" : style.align === "justify" ? "just" : "l"}"`];
  if (bulletXml || level > 0) attrs.push(`lvl="${level}"`);
  if (marginLeft > 0) attrs.push(`marL="${emu(marginLeft)}"`);
  if (hanging > 0) attrs.push(`indent="-${emu(hanging)}"`);
  if (style.defTabSz !== undefined || style.defaultTabSize !== undefined) attrs.push(`defTabSz="${emu(Number(style.defTabSz ?? style.defaultTabSize) || 0)}"`);
  if (style.rtl !== undefined) attrs.push(`rtl="${style.rtl ? 1 : 0}"`);
  if (style.eaLnBrk !== undefined) attrs.push(`eaLnBrk="${style.eaLnBrk ? 1 : 0}"`);
  if (style.latinLnBrk !== undefined) attrs.push(`latinLnBrk="${style.latinLnBrk ? 1 : 0}"`);
  if (style.hangingPunct !== undefined) attrs.push(`hangingPunct="${style.hangingPunct ? 1 : 0}"`);
  return `<a:pPr ${attrs.join(" ")}>${lineSpacing}${after}${bulletXml}</a:pPr>`;
}

function paragraphXml(runs, style = {}, hyperlinkMap = new Map()) {
  const size = Math.round(Number(style.fontSize ?? 16) * 72 / 96 * 100);
  return `<a:p>${paragraphProperties(style)}${runs.map((run) => {
    const target = hyperlinkTarget(run?.hyperlink ?? run?.link ?? style.hyperlink ?? style.link);
    return runXml(run, style, target ? hyperlinkMap.get(target) : null);
  }).join("")}<a:endParaRPr lang="zh-CN" sz="${size}"/></a:p>`;
}

function textStyleDirect(bucket) {
  if (!bucket || typeof bucket !== "object" || Array.isArray(bucket)) return {};
  if (bucket.style && typeof bucket.style === "object" && !Array.isArray(bucket.style)) return bucket.style;
  if (bucket.levels || bucket.rawXml) return {};
  return Object.fromEntries(Object.entries(bucket).filter(([key]) => key !== "style"));
}

function preservedTextStyleRootXml(bucket = {}) {
  if (!bucket || typeof bucket !== "object" || typeof bucket.rawXml !== "string" || typeof bucket.rawSnapshot !== "string") return null;
  return JSON.stringify(textStyleLevels(bucket)) === bucket.rawSnapshot ? bucket.rawXml : null;
}

function textStyleColorXml(style = {}) {
  if (style.color === undefined || style.color === null || style.color === "") return "";
  return `<a:solidFill>${colorChoiceXml(style.color, "1E1E1E", typeof style.color === "string" ? null : style.color?.scheme ?? null)}</a:solidFill>`;
}

function themeFontTypeface(fontRef, script, fallback) {
  const normalized = String(fontRef ?? "").toLowerCase();
  if (normalized === "major" || normalized === "minor") return `+${normalized === "major" ? "mj" : "mn"}-${script}`;
  return fallback;
}

function textStyleRunPropertiesXml(style = {}) {
  const fontSize = Number(style.fontSize);
  const fontSizePt = Number(style.fontSizePt ?? (Number.isFinite(fontSize) ? fontSize * 72 / 96 : NaN));
  const attrs = [
    Number.isFinite(fontSizePt) ? `sz="${Math.round(fontSizePt * 100)}"` : "",
    style.lang ? `lang="${escapeXml(style.lang)}"` : "",
    style.bold === undefined ? "" : `b="${style.bold ? 1 : 0}"`,
    style.italic === undefined ? "" : `i="${style.italic ? 1 : 0}"`,
    style.underline ? `u="${escapeXml(underlineValue(style.underline))}"` : "",
    style.strike ? `strike="${escapeXml(strikeValue(style.strike))}"` : "",
    baselineValue(style) === null ? "" : `baseline="${baselineValue(style)}"`,
  ].filter(Boolean).join(" ");
  const latin = style.fontFamily ?? style.latinFontFamily ?? themeFontTypeface(style.fontRef, "lt", null);
  const eastAsia = style.eastAsiaFontFamily ?? style.fontFamily ?? (style.latinFontFamily ? style.latinFontFamily : themeFontTypeface(style.fontRef, "ea", latin));
  const complexScript = style.complexScriptFontFamily ?? style.fontFamily ?? (style.latinFontFamily ? style.latinFontFamily : themeFontTypeface(style.fontRef, "cs", latin));
  const fonts = [
    latin ? `<a:latin typeface="${escapeXml(latin)}"/>` : "",
    eastAsia ? `<a:ea typeface="${escapeXml(eastAsia)}"/>` : "",
    complexScript ? `<a:cs typeface="${escapeXml(complexScript)}"/>` : "",
  ].filter(Boolean).join("");
  return `<a:defRPr${attrs ? ` ${attrs}` : ""}>${textStyleColorXml(style)}${fonts}</a:defRPr>`;
}

function textStyleParagraphPropertiesXml(style = {}, tagName = "a:lvl1pPr") {
  const attrs = [
    style.align ? `algn="${style.align === "center" ? "ctr" : style.align === "right" ? "r" : style.align === "justify" ? "just" : "l"}"` : "",
    style.indent === undefined && style.marginLeft === undefined ? "" : `marL="${emu(Number(style.marginLeft ?? style.indent) || 0)}"`,
    style.hanging === undefined ? "" : `indent="-${emu(Math.max(0, Number(style.hanging) || 0))}"`,
    style.defTabSz === undefined && style.defaultTabSize === undefined ? "" : `defTabSz="${emu(Number(style.defTabSz ?? style.defaultTabSize) || 0)}"`,
    style.rtl === undefined ? "" : `rtl="${style.rtl ? 1 : 0}"`,
    style.eaLnBrk === undefined ? "" : `eaLnBrk="${style.eaLnBrk ? 1 : 0}"`,
    style.latinLnBrk === undefined ? "" : `latinLnBrk="${style.latinLnBrk ? 1 : 0}"`,
    style.hangingPunct === undefined ? "" : `hangingPunct="${style.hangingPunct ? 1 : 0}"`,
  ].filter(Boolean).join(" ");
  const lineHeight = Number(style.lineHeight);
  const lineHeightPoints = Number(style.lineHeightPoints);
  const lineSpacing = Number.isFinite(lineHeightPoints) && lineHeightPoints > 0
    ? `<a:lnSpc><a:spcPts val="${Math.round(lineHeightPoints * 100)}"/></a:lnSpc>`
    : Number.isFinite(lineHeight) && lineHeight > 0
      ? `<a:lnSpc><a:spcPct val="${Math.round(lineHeight * 100000)}"/></a:lnSpc>`
      : "";
  const spaceBefore = Number(style.spaceBefore ?? style.paragraphSpaceBefore);
  const spacingBefore = Number.isFinite(spaceBefore) && spaceBefore > 0 ? `<a:spcBef><a:spcPts val="${Math.round(spaceBefore * 100)}"/></a:spcBef>` : "";
  const spaceAfter = Number(style.spaceAfter ?? style.paragraphSpaceAfter);
  const spacingAfter = Number.isFinite(spaceAfter) && spaceAfter > 0 ? `<a:spcAft><a:spcPts val="${Math.round(spaceAfter * 100)}"/></a:spcAft>` : "";
  const bullet = style.bullet === true || style.bullet === "bullet" || style.bullet === "disc"
    ? `<a:buChar char="${escapeXml(style.bulletChar ?? "•")}"/>`
    : style.bullet === "number" || style.bullet === "numbered" || style.bullet === "decimal"
      ? `<a:buAutoNum type="arabicPeriod"/>`
      : "";
  return `<${tagName}${attrs ? ` ${attrs}` : ""}>${lineSpacing}${spacingBefore}${spacingAfter}${bullet}${textStyleRunPropertiesXml(style)}</${tagName}>`;
}

function textStyleRootXml(bucket = {}, defaultTag = "a:defPPr") {
  const preserved = preservedTextStyleRootXml(bucket);
  if (preserved) return preserved;
  const direct = textStyleDirect(bucket);
  const levels = textStyleLevels(bucket);
  const defaultParagraph = Object.keys(direct).length > 0 ? textStyleParagraphPropertiesXml(direct, defaultTag) : `<${defaultTag}/>`;
  const levelXml = Object.entries(levels)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([level, style]) => textStyleParagraphPropertiesXml(style, `a:lvl${Math.max(1, Number(level) + 1)}pPr`))
    .join("");
  return `${defaultParagraph}${levelXml}`;
}

function presentationDefaultTextStyleXml(theme = {}, textStyles = {}) {
  const fonts = theme.fonts ?? {};
  const customLevels = textStyleLevels(textStyles.default);
  const custom = {
    ...textStyleDirect(textStyles.default),
    ...(customLevels["0"] ?? {}),
  };
  const defaults = {
    fontFamily: fonts.body ?? "Aptos",
    eastAsiaFontFamily: fonts.cjk ?? fonts.body ?? "Aptos",
    complexScriptFontFamily: fonts.body ?? "Aptos",
    fontSize: theme.type?.body ?? 16,
    fontSizePt: theme.type?.body ?? 16,
    color: theme.colors?.ink ?? "#1E1E1E",
    ...custom,
  };
  if (custom.fontSize !== undefined && custom.fontSizePt === undefined) delete defaults.fontSizePt;
  // `defaultTextStyle` is allowed to define all nine paragraph levels, not
  // only the level-0 fallback. Keep the level map alongside the resolved
  // defPPr so a default style does not silently lose nested-list semantics.
  const root = preservedTextStyleRootXml(textStyles.default) ?? textStyleRootXml({ style: defaults, levels: customLevels }, "a:defPPr");
  return `<p:defaultTextStyle>${root}</p:defaultTextStyle>`;
}

function masterTextStylesXml(textStyles = {}) {
  return `<p:txStyles><p:titleStyle>${textStyleRootXml(textStyles.title)}</p:titleStyle><p:bodyStyle>${textStyleRootXml(textStyles.body)}</p:bodyStyle><p:otherStyle>${textStyleRootXml(textStyles.other)}</p:otherStyle></p:txStyles>`;
}

function textBodyXml(element, hyperlinkMap = new Map()) {
  const style = {
    ...(element.style ?? {}),
    ...(element.bullet !== undefined ? { bullet: element.bullet } : {}),
    ...(element.bulletChar !== undefined ? { bulletChar: element.bulletChar } : {}),
    ...(element.bulletLevel !== undefined ? { bulletLevel: element.bulletLevel } : {}),
  };
  const paragraphs = paragraphRuns(element, style).map((runs) => paragraphXml(runs, style, hyperlinkMap)).join("");
  const margin = (side) => Number(style[`${side}Margin`] ?? (typeof style.margin === "object" ? style.margin?.[side] : style.margin) ?? 0) || 0;
  const bodyPr = `<a:bodyPr wrap="square" anchor="${style.valign === "middle" ? "ctr" : style.valign === "bottom" ? "b" : "t"}" lIns="${emu(Math.max(0, margin("left")))}" tIns="${emu(Math.max(0, margin("top")))}" rIns="${emu(Math.max(0, margin("right")))}" bIns="${emu(Math.max(0, margin("bottom")))}">${element.autoFit ? "<a:normAutofit/>" : ""}</a:bodyPr>`;
  return `<p:txBody>${bodyPr}<a:lstStyle/>${paragraphs || paragraphXml([], style)}</p:txBody>`;
}

function tableCell(cell, tableStyle = {}) {
  if (typeof cell === "string" || typeof cell === "number") return { text: String(cell), style: tableStyle };
  return { ...cell, text: cell?.text ?? "", style: { ...tableStyle, ...(cell?.style ?? {}) } };
}

function tableCellXml(cell, tableStyle, colWidth, rowHeight, merge = {}) {
  const normalized = tableCell(cell, tableStyle);
  const cellStyle = normalized.style ?? tableStyle;
  const fill = normalized.fill ?? cellStyle.fill ?? cellStyle.fillRef ?? "#FFFFFF";
  const runs = normalized.runs ?? [{ text: normalized.text ?? "" }];
  const body = textBodyXml({ text: normalized.text, runs, style: cellStyle }).replace("<p:txBody>", "<a:txBody>").replace("</p:txBody>", "</a:txBody>");
  const border = typeof cellStyle.border === "object" ? cellStyle.border : {};
  const globalBorder = {
    width: Math.max(0, Number(cellStyle.borderWidth ?? border.width ?? 1) || 0),
    color: cellStyle.borderColor ?? border.color ?? "#D3CEC3",
  };
  const sideBorder = (side) => {
    const value = typeof border[side] === "object" ? border[side] : {};
    const lineReference = value.lineRef ?? value.lnRef;
    const referenceColor = typeof lineReference === "object" ? lineReference.color ?? lineReference.scheme ?? lineReference.value : lineReference;
    return {
      width: Math.max(0, Number(value.width ?? globalBorder.width) || 0),
      color: value.color ?? referenceColor ?? globalBorder.color,
      dash: value.dash ?? globalBorder.dash ?? "solid",
    };
  };
  const marginValue = (side) => Number(cellStyle[`${side}Margin`] ?? (typeof cellStyle.margin === "object" ? cellStyle.margin?.[side] : cellStyle.margin) ?? 6) || 0;
  const borderXml = (side) => {
    const value = sideBorder({ L: "left", R: "right", T: "top", B: "bottom" }[side]);
    return value.width > 0
      ? `<a:ln${side} w="${Math.max(1, emu(value.width))}"><a:solidFill><a:srgbClr val="${hex(value.color)}"/></a:solidFill><a:prstDash val="${value.dash === "dash" ? "dash" : value.dash === "dot" ? "dot" : "solid"}"/></a:ln${side}>`
      : `<a:ln${side} w="0"><a:noFill/></a:ln${side}>`;
  };
  const attrs = [
    (merge.gridSpan ?? merge.colSpan) > 1 ? `gridSpan="${merge.gridSpan ?? merge.colSpan}"` : "",
    merge.rowSpan > 1 ? `rowSpan="${merge.rowSpan}"` : "",
    merge.hMerge ? `hMerge="1"` : "",
    merge.vMerge ? `vMerge="1"` : "",
  ].filter(Boolean).join(" ");
  return `<a:tc${attrs ? ` ${attrs}` : ""}>${body}<a:tcPr marL="${emu(marginValue("left"))}" marR="${emu(marginValue("right"))}" marT="${emu(marginValue("top"))}" marB="${emu(marginValue("bottom"))}">${solidFill(fill)}${borderXml("L")}${borderXml("R")}${borderXml("T")}${borderXml("B")}</a:tcPr></a:tc>`;
}

function normalizedTableGrid(rows) {
  const grid = [];
  let columnCount = 0;
  for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
    grid[rowIndex] ??= [];
    let cursor = 0;
    for (const cell of (Array.isArray(rows[rowIndex]) ? rows[rowIndex] : [])) {
      while (grid[rowIndex][cursor]) cursor += 1;
      const normalized = tableCell(cell);
      const colSpan = Math.max(1, Number(normalized.colSpan ?? normalized.colspan ?? 1));
      const rowSpan = Math.max(1, Number(normalized.rowSpan ?? normalized.rowspan ?? 1));
      for (let y = 0; y < rowSpan; y += 1) {
        grid[rowIndex + y] ??= [];
        for (let x = 0; x < colSpan; x += 1) {
          const targetRow = grid[rowIndex + y];
          const targetColumn = cursor + x;
          if (targetRow[targetColumn]) throw new Error(`Table merge overlaps an existing cell at row ${rowIndex}, column ${targetColumn}`);
          targetRow[targetColumn] = {
            cell: y === 0 && x === 0 ? cell : "",
            merge: {
              ...(y === 0 && x === 0 ? { colSpan, rowSpan } : {}),
              hMerge: x > 0,
              vMerge: y > 0,
            },
          };
        }
      }
      cursor += colSpan;
      columnCount = Math.max(columnCount, cursor);
    }
  }
  return { rows: grid.map((row) => Array.from({ length: columnCount }, (_, column) => row?.[column] ?? { cell: "", merge: {} })), columnCount };
}

function normalizedDimensionList(values, total, count) {
  const fallback = Math.max(0, Number(total) || 0) / Math.max(1, count);
  if (!Array.isArray(values) || values.length < count) return Array.from({ length: count }, () => fallback);
  const normalized = values.slice(0, count).map((value) => Math.max(0, Number(value) || 0));
  const sum = normalized.reduce((result, value) => result + value, 0);
  if (sum <= 0) return Array.from({ length: count }, () => fallback);
  const scale = (Number(total) || 0) / sum;
  return normalized.map((value) => value * scale);
}

function tableXml(element, index) {
  const p = element.position;
  const style = { fontFamily: "Aptos", fontSize: 16, color: "#1E1E1E", ...(element.style ?? {}) };
  const tableStyleDefinition = tableStyleDefinitionFor(style);
  const rows = Array.isArray(element.rows) ? element.rows : [];
  const normalized = normalizedTableGrid(rows.length > 0 ? rows : [[""]]);
  const columnCount = Math.max(1, normalized.columnCount);
  const rowCount = Math.max(1, normalized.rows.length);
  const columnWidths = normalizedDimensionList(element.columnWidths, p.width, columnCount);
  const rowHeights = normalizedDimensionList(element.rowHeights, p.height, rowCount);
  const tableStyleToggles = {
    firstRow: element.header !== false,
    lastRow: Boolean(style.lastRow || style.lastRowStyle || tableStyleDefinition?.regions?.lastRow),
    firstCol: Boolean(style.firstColumn),
    lastCol: Boolean(style.lastColumn),
    bandRow: Boolean(element.banded),
    bandColumn: Boolean(style.bandColumn || style.bandCol),
  };
  const grid = columnWidths.map((width) => `<a:gridCol w="${emu(width)}"/>`).join("");
  const tableBaseStyle = tableStyleBase(style);
  const rowXml = normalized.rows.map((row, rowIndex) => {
    return `<a:tr h="${emu(rowHeights[rowIndex])}">${row.map((slot, columnIndex) => {
      const source = slot.cell && typeof slot.cell === "object"
        ? slot.cell
        : { text: String(slot.cell ?? "") };
      const cell = {
        ...source,
        style: {
          ...tableBaseStyle,
          ...tableStyleRegionStyle(tableStyleDefinition, rowIndex, columnIndex, rowCount, columnCount, tableStyleToggles),
          ...(source.style ?? {}),
        },
      };
      return tableCellXml(cell, tableBaseStyle, columnWidths[columnIndex] ?? columnWidths[0], rowHeights[rowIndex], slot.merge);
    }).join("")}</a:tr>`;
  }).join("");
  const tableStyleIdXml = tableStyleDefinition?.id ? `<a:tableStyleId>${escapeXml(tableStyleDefinition.id)}</a:tableStyleId>` : "";
  const tableProperties = `<a:tblPr firstRow="${element.header === false ? 0 : 1}" bandRow="${element.banded ? 1 : 0}" firstCol="${style.firstColumn ? 1 : 0}" lastCol="${style.lastColumn ? 1 : 0}"${style.bandColumn || style.bandCol ? ` bandCol="1"` : ""}>${tableStyleIdXml}</a:tblPr>`;
  return `<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="${index + 2}" name="${escapeXml(element.name ?? `table-${index}`)}"${roleMetadataXml(element)}/><p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr>${nonVisualPropertiesXml(element)}</p:nvGraphicFramePr><p:xfrm>${`<a:off x="${emu(p.left)}" y="${emu(p.top)}"/><a:ext cx="${emu(p.width)}" cy="${emu(p.height)}"/>`}</p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl>${tableProperties}<a:tblGrid>${grid}</a:tblGrid>${rowXml}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>`;
}

function chartTextCache(values, numeric = false) {
  const items = values.map((value, index) => `<c:pt idx="${index}"><c:v>${escapeXml(value)}</c:v></c:pt>`).join("");
  return numeric
    ? `<c:numLit><c:formatCode>General</c:formatCode><c:ptCount val="${values.length}"/>${items}</c:numLit>`
    : `<c:strLit><c:ptCount val="${values.length}"/>${items}</c:strLit>`;
}

const PIE_COLORS = ["#B32635", "#2A2B2E", "#B66B31", "#8E1B27", "#6E6B65", "#D3CEC3"];

function chartSeriesXml(series, categories, index, line = false, pie = false) {
  const values = Array.isArray(series?.values) ? series.values : [];
  const color = hex(series?.color ?? "#B32635");
  const shape = line
    ? `<a:solidFill><a:srgbClr val="${color}"/></a:solidFill><a:ln w="25400"><a:solidFill><a:srgbClr val="${color}"/></a:solidFill><a:prstDash val="solid"/></a:ln>`
    : `<a:solidFill><a:srgbClr val="${color}"/></a:solidFill><a:ln><a:noFill/></a:ln>`;
  const marker = line ? `<c:marker><c:symbol val="circle"/><c:size val="6"/><c:spPr><a:solidFill><a:srgbClr val="${color}"/></a:solidFill><a:ln w="9525"><a:solidFill><a:srgbClr val="${color}"/></a:solidFill><a:prstDash val="solid"/></a:ln></c:spPr></c:marker>` : "";
  const smooth = line ? `<c:smooth val="0"/>` : "";
  const points = pie
    ? values.map((_, pointIndex) => {
      const pointColors = Array.isArray(series?.colors) ? series.colors : PIE_COLORS;
      return `<c:dPt><c:idx val="${pointIndex}"/><c:spPr>${solidFill(pointColors[pointIndex % pointColors.length] ?? PIE_COLORS[pointIndex % PIE_COLORS.length])}<a:ln><a:noFill/></a:ln></c:spPr></c:dPt>`;
    }).join("")
    : "";
  return `<c:ser><c:idx val="${index}"/><c:order val="${index}"/><c:tx><c:v>${escapeXml(series?.name ?? `Series ${index + 1}`)}</c:v></c:tx><c:spPr>${shape}</c:spPr>${marker}${points}<c:cat>${chartTextCache(categories)}</c:cat><c:val>${chartTextCache(values.map((value) => Number(value) || 0), true)}</c:val>${smooth}</c:ser>`;
}

function scatterSeriesXml(series, index, fallbackXValues = []) {
  const values = Array.isArray(series?.values) ? series.values : [];
  const xValues = Array.isArray(series?.xValues) && series.xValues.length ? series.xValues : fallbackXValues;
  const color = hex(series?.color ?? "#B32635");
  const points = (items) => `<c:numLit><c:formatCode>General</c:formatCode><c:ptCount val="${items.length}"/>${items.map((value, pointIndex) => `<c:pt idx="${pointIndex}"><c:v>${escapeXml(Number(value) || 0)}</c:v></c:pt>`).join("")}</c:numLit>`;
  return `<c:ser><c:idx val="${index}"/><c:order val="${index}"/><c:tx><c:v>${escapeXml(series?.name ?? `Series ${index + 1}`)}</c:v></c:tx><c:spPr><a:solidFill><a:srgbClr val="${color}"/></a:solidFill><a:ln w="25400"><a:solidFill><a:srgbClr val="${color}"/></a:solidFill><a:prstDash val="solid"/></a:ln></c:spPr><c:marker><c:symbol val="circle"/><c:size val="6"/><c:spPr><a:solidFill><a:srgbClr val="${color}"/></a:solidFill><a:ln w="9525"><a:solidFill><a:srgbClr val="${color}"/></a:solidFill><a:prstDash val="solid"/></a:ln></c:spPr></c:marker><c:xVal>${points(xValues)}</c:xVal><c:yVal>${points(values)}</c:yVal></c:ser>`;
}

function axisScalingXml(axis = {}) {
  const min = Number.isFinite(Number(axis.min)) ? `<c:min val="${Number(axis.min)}"/>` : "";
  const max = Number.isFinite(Number(axis.max)) ? `<c:max val="${Number(axis.max)}"/>` : "";
  const orientation = axis.reverse ? "maxMin" : "minMax";
  return `<c:scaling><c:orientation val="${orientation}"/>${min}${max}</c:scaling>`;
}

function chartLuminance(value) {
  const raw = hex(value, "F7F5F0");
  const channels = [0, 2, 4].map((offset) => parseInt(raw.slice(offset, offset + 2), 16) / 255);
  const linear = channels.map((channel) => channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function chartStyleFor(style = {}, theme = {}) {
  const themeColors = theme.colors ?? {};
  const dark = chartLuminance(themeColors.paper ?? "#F7F5F0") < 0.45;
  return {
    textColor: style.textColor ?? style.chartTextColor ?? (dark ? themeColors.white : themeColors.ink) ?? (dark ? "#FFFFFF" : "#1E1E1E"),
    axisColor: style.axisColor ?? (dark ? themeColors.muted : themeColors.line) ?? (dark ? "#B0A8AC" : "#D3CEC3"),
    gridColor: style.gridColor ?? themeColors.line ?? "#D3CEC3",
    fontFamily: style.fontFamily ?? theme.fonts?.body ?? "Aptos",
    titleFontSize: Number(style.titleFontSize ?? 14),
    axisFontSize: Number(style.axisFontSize ?? 11),
    legendFontSize: Number(style.legendFontSize ?? 11),
    dataLabelFontSize: Number(style.dataLabelFontSize ?? 11),
  };
}

function chartTextPropertiesXml(style = {}, fontSize = 11, { bold = false } = {}) {
  const size = Math.round(Math.max(1, Number(fontSize) || 11) * 100);
  const family = escapeXml(style.fontFamily ?? "Aptos");
  const color = hex(style.textColor ?? "#1E1E1E", "1E1E1E");
  return `<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="${size}" b="${bold ? 1 : 0}" i="0" u="none" strike="noStrike"><a:solidFill><a:srgbClr val="${color}"/></a:solidFill><a:latin typeface="${family}"/><a:ea typeface="${family}"/><a:cs typeface="${family}"/></a:defRPr></a:pPr><a:endParaRPr lang="zh-CN"/></a:p></c:txPr>`;
}

function chartAxisLineXml(colorValue, width = 1) {
  return `<c:spPr><a:ln w="${Math.max(1, emu(width))}"><a:solidFill><a:srgbClr val="${hex(colorValue, "D3CEC3")}"/></a:solidFill><a:prstDash val="solid"/></a:ln></c:spPr>`;
}

function axisTitleXml(title, style = {}) {
  if (!title) return "";
  const size = Math.round(Math.max(1, Number(style.axisTitleFontSize ?? 11) || 11) * 100);
  const color = hex(style.axisTitleColor ?? style.textColor ?? "#1E1E1E", "1E1E1E");
  const family = escapeXml(style.fontFamily ?? "Aptos");
  return `<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="zh-CN" sz="${size}" b="0"><a:solidFill><a:srgbClr val="${color}"/></a:solidFill><a:latin typeface="${family}"/><a:ea typeface="${family}"/><a:cs typeface="${family}"/></a:rPr><a:t>${escapeXml(title)}</a:t></a:r><a:endParaRPr lang="zh-CN"/></a:p></c:rich></c:tx><c:layout/><c:overlay val="0"/>${chartTextPropertiesXml({ ...style, textColor: style.axisTitleColor ?? style.textColor }, style.axisTitleFontSize ?? 11)}</c:title>`;
}

function axisNumberFormatXml(axis = {}) {
  return axis.numberFormat ? `<c:numFmt formatCode="${escapeXml(axis.numberFormat)}" sourceLinked="0"/>` : "";
}

function axisGridlinesXml(axis = {}, defaultVisible = false, style = {}) {
  const visible = axis.showGridlines === undefined ? defaultVisible : Boolean(axis.showGridlines);
  if (!visible) return "";
  const lineColor = axis.gridColor ?? style.gridColor ?? "#D3CEC3";
  const lineWidth = Number(axis.gridWidth ?? style.gridWidth ?? 1) || 1;
  return `<c:majorGridlines>${chartAxisLineXml(lineColor, lineWidth)}</c:majorGridlines>`;
}

function axisMajorUnitXml(axis = {}) {
  return Number.isFinite(Number(axis.majorUnit)) && Number(axis.majorUnit) > 0 ? `<c:majorUnit val="${Number(axis.majorUnit)}"/>` : "";
}

function chartAxesXml(categoryAxisId, valueAxisId, style = {}) {
  const xAxis = style.xAxis ?? style.categoryAxis ?? {};
  const yAxis = style.yAxis ?? style.valueAxis ?? {};
  const chartStyle = chartStyleFor(style, style.theme ?? {});
  const xStyle = { ...chartStyle, textColor: xAxis.labelColor ?? chartStyle.textColor, fontFamily: xAxis.fontFamily ?? chartStyle.fontFamily };
  const yStyle = { ...chartStyle, textColor: yAxis.labelColor ?? chartStyle.textColor, fontFamily: yAxis.fontFamily ?? chartStyle.fontFamily };
  return `<c:catAx><c:axId val="${categoryAxisId}"/>${axisScalingXml(xAxis)}<c:delete val="0"/><c:axPos val="b"/>${axisTitleXml(xAxis.title, { ...xStyle, axisTitleColor: xAxis.titleColor, axisTitleFontSize: xAxis.titleFontSize })}${axisNumberFormatXml(xAxis)}${axisGridlinesXml(xAxis, false, xStyle)}<c:majorTickMark val="out"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="${valueAxisId}"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:noMultiLvlLbl val="1"/>${chartTextPropertiesXml(xStyle, xAxis.fontSize ?? chartStyle.axisFontSize)}${chartAxisLineXml(xAxis.lineColor ?? chartStyle.axisColor, xAxis.lineWidth ?? 1)}</c:catAx><c:valAx><c:axId val="${valueAxisId}"/>${axisScalingXml(yAxis)}<c:delete val="0"/><c:axPos val="l"/>${axisTitleXml(yAxis.title, { ...yStyle, axisTitleColor: yAxis.titleColor, axisTitleFontSize: yAxis.titleFontSize })}${axisNumberFormatXml(yAxis)}${axisGridlinesXml(yAxis, true, yStyle)}${axisMajorUnitXml(yAxis)}<c:majorTickMark val="out"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="${categoryAxisId}"/><c:crosses val="autoZero"/><c:crossBetween val="between"/>${chartTextPropertiesXml(yStyle, yAxis.fontSize ?? chartStyle.axisFontSize)}${chartAxisLineXml(yAxis.lineColor ?? chartStyle.axisColor, yAxis.lineWidth ?? 1)}</c:valAx>`;
}

function scatterAxesXml(xAxisId, yAxisId, style = {}) {
  const xAxis = style.xAxis ?? {};
  const yAxis = style.yAxis ?? {};
  const chartStyle = chartStyleFor(style, style.theme ?? {});
  const xStyle = { ...chartStyle, textColor: xAxis.labelColor ?? chartStyle.textColor, fontFamily: xAxis.fontFamily ?? chartStyle.fontFamily };
  const yStyle = { ...chartStyle, textColor: yAxis.labelColor ?? chartStyle.textColor, fontFamily: yAxis.fontFamily ?? chartStyle.fontFamily };
  return `<c:valAx><c:axId val="${xAxisId}"/>${axisScalingXml(xAxis)}<c:delete val="0"/><c:axPos val="b"/>${axisTitleXml(xAxis.title, { ...xStyle, axisTitleColor: xAxis.titleColor, axisTitleFontSize: xAxis.titleFontSize })}${axisNumberFormatXml(xAxis)}${axisGridlinesXml(xAxis, true, xStyle)}${axisMajorUnitXml(xAxis)}<c:majorTickMark val="out"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="${yAxisId}"/><c:crosses val="autoZero"/><c:crossBetween val="midCat"/>${chartTextPropertiesXml(xStyle, xAxis.fontSize ?? chartStyle.axisFontSize)}${chartAxisLineXml(xAxis.lineColor ?? chartStyle.axisColor, xAxis.lineWidth ?? 1)}</c:valAx><c:valAx><c:axId val="${yAxisId}"/>${axisScalingXml(yAxis)}<c:delete val="0"/><c:axPos val="l"/>${axisTitleXml(yAxis.title, { ...yStyle, axisTitleColor: yAxis.titleColor, axisTitleFontSize: yAxis.titleFontSize })}${axisNumberFormatXml(yAxis)}${axisGridlinesXml(yAxis, true, yStyle)}${axisMajorUnitXml(yAxis)}<c:majorTickMark val="out"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="${xAxisId}"/><c:crosses val="autoZero"/><c:crossBetween val="midCat"/>${chartTextPropertiesXml(yStyle, yAxis.fontSize ?? chartStyle.axisFontSize)}${chartAxisLineXml(yAxis.lineColor ?? chartStyle.axisColor, yAxis.lineWidth ?? 1)}</c:valAx>`;
}

function chartTitleXml(title, style = {}) {
  if (!title) return "";
  const size = Math.round(Math.max(1, Number(style.titleFontSize ?? 14) || 14) * 100);
  const color = hex(style.titleColor ?? style.textColor ?? "#1E1E1E", "1E1E1E");
  const family = escapeXml(style.fontFamily ?? "Aptos");
  return `<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="zh-CN" sz="${size}" b="1"><a:solidFill><a:srgbClr val="${color}"/></a:solidFill><a:latin typeface="${family}"/><a:ea typeface="${family}"/><a:cs typeface="${family}"/></a:rPr><a:t>${escapeXml(title)}</a:t></a:r><a:endParaRPr lang="zh-CN"/></a:p></c:rich></c:tx><c:layout/><c:overlay val="0"/>${chartTextPropertiesXml({ ...style, textColor: style.titleColor ?? style.textColor }, style.titleFontSize ?? 14, { bold: true })}</c:title>`;
}

function chartLegendXml(style = {}, chartStyle = {}) {
  if (!style.legend) return "";
  return `<c:legend><c:legendPos val="${escapeXml(style.legendPosition ?? "r")}"/><c:layout/><c:overlay val="0"/>${chartTextPropertiesXml({ ...chartStyle, textColor: style.legendColor ?? chartStyle.textColor, fontFamily: style.legendFontFamily ?? chartStyle.fontFamily }, style.legendFontSize ?? chartStyle.legendFontSize)}</c:legend>`;
}

function chartDataLabelsXml(style = {}, chartStyle = {}) {
  const labels = style.dataLabels ?? {};
  const showValue = style.showValue ?? labels.showValue;
  const showCatName = style.showCatName ?? labels.showCatName;
  const showPercent = style.showPercent ?? labels.showPercent;
  if (!showValue && !showCatName && !showPercent) return "";
  const position = style.dataLabelPosition ?? (style.chartType === "bar" ? "outEnd" : "bestFit");
  return `<c:dLbls>${chartTextPropertiesXml({ ...chartStyle, textColor: style.dataLabelColor ?? chartStyle.textColor, fontFamily: style.dataLabelFontFamily ?? chartStyle.fontFamily }, style.dataLabelFontSize ?? chartStyle.dataLabelFontSize)}<c:dLblPos val="${escapeXml(position)}"/><c:showLegendKey val="0"/><c:showVal val="${showValue ? 1 : 0}"/><c:showCatName val="${showCatName ? 1 : 0}"/><c:showSerName val="0"/><c:showPercent val="${showPercent ? 1 : 0}"/><c:showBubbleSize val="0"/><c:showLeaderLines val="0"/><c:separator> </c:separator></c:dLbls>`;
}

function chartXml(element, theme = {}) {
  const categories = Array.isArray(element.categories) ? element.categories : [];
  const series = Array.isArray(element.series) ? element.series : [];
  const categoryAxisId = 100001;
  const valueAxisId = 100002;
  const isRadar = element.chartType === "radar";
  const isScatter = element.chartType === "scatter";
  const isLine = element.chartType === "line" || element.chartType === "area" || isRadar;
  const isPie = element.chartType === "pie" || element.chartType === "donut" || element.chartType === "doughnut";
  const chartStyle = chartStyleFor(element.style ?? {}, theme);
  const styled = { ...(element.style ?? {}), theme, textColor: chartStyle.textColor, axisColor: chartStyle.axisColor, gridColor: chartStyle.gridColor, fontFamily: chartStyle.fontFamily };
  const seriesXml = isScatter
    ? series.map((item, index) => scatterSeriesXml(item, index, element.xValues ?? categories)).join("")
    : series.map((item, index) => chartSeriesXml(item, categories, index, isLine, isPie)).join("");
  const dataLabels = chartDataLabelsXml({ ...styled, chartType: element.chartType }, chartStyle);
  const chartBody = isScatter
    ? `<c:scatterChart><c:scatterStyle val="lineMarker"/><c:varyColors val="0"/>${seriesXml}${dataLabels}<c:axId val="${categoryAxisId}"/><c:axId val="${valueAxisId}"/></c:scatterChart>`
    : isPie
    ? `<c:${element.chartType === "donut" || element.chartType === "doughnut" ? "doughnutChart" : "pieChart"}><c:varyColors val="1"/>${seriesXml}${dataLabels}</c:${element.chartType === "donut" || element.chartType === "doughnut" ? "doughnutChart" : "pieChart"}>`
    : element.chartType === "area"
    ? `<c:areaChart><c:grouping val="standard"/><c:varyColors val="0"/>${seriesXml}${dataLabels}<c:axId val="${categoryAxisId}"/><c:axId val="${valueAxisId}"/></c:areaChart>`
    : isRadar
    ? `<c:radarChart><c:radarStyle val="marker"/><c:varyColors val="0"/>${seriesXml}${dataLabels}<c:axId val="${categoryAxisId}"/><c:axId val="${valueAxisId}"/></c:radarChart>`
    : isLine
    ? `<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>${seriesXml}${dataLabels}<c:axId val="${categoryAxisId}"/><c:axId val="${valueAxisId}"/></c:lineChart>`
    : `<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/><c:varyColors val="0"/>${seriesXml}${dataLabels}<c:axId val="${categoryAxisId}"/><c:axId val="${valueAxisId}"/></c:barChart>`;
  const axes = isPie ? "" : isScatter ? scatterAxesXml(categoryAxisId, valueAxisId, styled) : chartAxesXml(categoryAxisId, valueAxisId, styled);
  const decorations = `${chartTitleXml(element.style?.title, styled)}${chartLegendXml(styled, chartStyle)}`;
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><c:date1904 val="0"/><c:roundedCorners val="0"/><c:chart>${element.style?.title ? "" : "<c:autoTitleDeleted val=\"1\"/>"}${decorations}<c:plotArea><c:layout/>${chartBody}${axes}</c:plotArea><c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart><c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr></c:chartSpace>`;
}

function chartFrameXml(element, index, relationshipId) {
  const p = element.position;
  return `<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="${index + 2}" name="${escapeXml(element.name ?? `chart-${index}`)}"${roleMetadataXml(element)}/><p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr>${nonVisualPropertiesXml(element)}</p:nvGraphicFramePr><p:xfrm><a:off x="${emu(p.left)}" y="${emu(p.top)}"/><a:ext cx="${emu(p.width)}" cy="${emu(p.height)}"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" r:id="${relationshipId}"/></a:graphicData></a:graphic></p:graphicFrame>`;
}

function roleMetadataXml(element) {
  const role = String(element?.role ?? "").trim();
  const markers = [];
  if (role) markers.push(`open-ppt-engine-role:${role}`);
  if (element?.allowOverlap === true) markers.push("open-ppt-engine-allow-overlap:1");
  if (element?.hidden === true) markers.push("open-ppt-engine-hidden:1");
  const semantic = markers.length > 0 ? ` title="${escapeXml(markers.join("|"))}"` : "";
  const hidden = element?.hidden === true ? " hidden=\"1\"" : "";
  return `${semantic}${hidden}`;
}

const NATIVE_PLACEHOLDER_TYPES = new Set([
  "title", "body", "ctrTitle", "subTitle", "obj", "chart", "tbl", "clipArt", "dgm", "media", "sldImg", "pic", "dt", "ftr", "hdr", "sldNum",
]);

function placeholderMetadataXml(element) {
  const raw = element?.placeholder;
  const rawType = raw && typeof raw === "object" ? raw.type : raw;
  const candidateType = element?.placeholderType ?? (NATIVE_PLACEHOLDER_TYPES.has(String(rawType ?? "")) ? rawType : null);
  const rawIdx = element?.placeholderIdx ?? (raw && typeof raw === "object" ? raw.idx : undefined);
  if (!candidateType && rawIdx === undefined) return "";
  const type = String(candidateType ?? "body");
  const numericIdx = Number(rawIdx);
  const idx = Number.isFinite(numericIdx) ? Math.round(numericIdx) : 0;
  return `<p:ph type="${escapeXml(type)}" idx="${idx}"/>`;
}

function nonVisualPropertiesXml(element) {
  const placeholder = placeholderMetadataXml(element);
  return placeholder ? `<p:nvPr>${placeholder}</p:nvPr>` : "<p:nvPr/>";
}

function shapeXml(element, index, hyperlinkMap = new Map()) {
  const geometry = normalizeGeometry(element.geometry);
  const p = element.position;
  const style = element.style ?? {};
  const name = escapeXml(element.name ?? `shape-${index}`);
  const hasText = element.type === "text";
  const fill = hasText ? "<a:noFill/>" : solidFill(style.fill);
  const line = hasText ? lineXml({ width: 0 }) : lineXml(style.line);
  return `<p:sp><p:nvSpPr><p:cNvPr id="${index + 2}" name="${name}"${roleMetadataXml(element)}/><p:cNvSpPr/>${nonVisualPropertiesXml(element)}</p:nvSpPr><p:spPr>${transformXml(p, element)}<a:prstGeom prst="${geometry}"><a:avLst/></a:prstGeom>${fill}${line}${effectsXml(style)}</p:spPr>${hasText ? textBodyXml(element, hyperlinkMap) : ""}</p:sp>`;
}

function formulaParagraphXml(element) {
  const style = element.style ?? {};
  const align = style.align === "center" ? "ctr" : style.align === "right" ? "r" : style.align === "justify" ? "just" : "l";
  const size = Math.round(Number(style.fontSize ?? 24) * 72 / 96 * 100);
  const math = formulaOmmlXml(element, style);
  return `<a:p><a:pPr algn="${align}"/><a14:m>${math}</a14:m><a:endParaRPr lang="zh-CN" sz="${size}"/></a:p>`;
}

function formulaTextBodyXml(element, native = true) {
  const style = element.style ?? {};
  const bodyPr = `<a:bodyPr wrap="square" anchor="${style.valign === "middle" ? "ctr" : style.valign === "bottom" ? "b" : "t"}" lIns="0" tIns="0" rIns="0" bIns="0"/>`;
  const paragraph = native
    ? formulaParagraphXml(element)
    : paragraphXml([{ text: formulaPlainText(element) }], style);
  return `<p:txBody>${bodyPr}<a:lstStyle/>${paragraph}</p:txBody>`;
}

function formulaShapeXml(element, index, native) {
  const p = element.position;
  const style = element.style ?? {};
  const name = escapeXml(element.name ?? `formula-${index}`);
  // PowerPoint understands OMML; LibreOffice currently keeps only the
  // fallback text. Preserve the source expression in the standard shape
  // description so a later importer can reconstruct the formula IR even when
  // the foreign writer removes the OMML branch.
  const formulaPayload = JSON.stringify({
    latex: String(element.latex ?? ""),
    ...(typeof element.omml === "string" && element.omml.trim() ? { omml: element.omml } : {}),
  });
  const description = escapeXml(`open-ppt-engine-formula:${Buffer.from(formulaPayload, "utf8").toString("base64")}`);
  const fill = solidFill(style.fill ?? "none");
  const line = lineXml(style.line ?? { width: 0 });
  return `<p:sp><p:nvSpPr><p:cNvPr id="${index + 2}" name="${name}"${roleMetadataXml(element)} descr="${description}"/><p:cNvSpPr/>${nonVisualPropertiesXml(element)}</p:nvSpPr><p:spPr>${transformXml(p, element)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>${fill}${line}${effectsXml(style)}</p:spPr>${formulaTextBodyXml(element, native)}</p:sp>`;
}

function formulaXml(element, index) {
  normalizeFormula(element, element.style ?? {});
  return `<mc:AlternateContent><mc:Choice Requires="a14">${formulaShapeXml(element, index, true)}</mc:Choice><mc:Fallback>${formulaShapeXml(element, index, false)}</mc:Fallback></mc:AlternateContent>`;
}

async function imagePayload(source, { includeSvgFallback = false } = {}) {
  const objectBytes = Buffer.isBuffer(source) || source instanceof Uint8Array
    ? Buffer.from(source)
    : Buffer.isBuffer(source?.data) || source?.data instanceof Uint8Array
      ? Buffer.from(source.data)
      : Buffer.isBuffer(source?.bytes) || source?.bytes instanceof Uint8Array
        ? Buffer.from(source.bytes)
        : null;
  if (objectBytes) {
    const mimeType = String(source?.mimeType ?? source?.contentType ?? "image/png").split(";", 1)[0].toLowerCase();
    const extension = mimeType === "image/jpeg" ? "jpg" : mimeType === "image/svg+xml" ? "svg" : mimeType === "image/gif" ? "gif" : "png";
    return { data: objectBytes, mimeType, extension, ...(await imageDimensions(objectBytes)), ...(includeSvgFallback ? await svgFallback(objectBytes, mimeType) : {}) };
  }
  if (typeof source !== "string") throw new TypeError("OOXML basic image source must be a path, data URL, or artifact bytes");
  const dataUrl = source.match(/^data:([^;,]+)?;base64,(.+)$/u);
  if (dataUrl) {
    const mimeType = dataUrl[1] ?? "image/png";
    const extension = mimeType === "image/jpeg" ? "jpg" : mimeType === "image/svg+xml" ? "svg" : "png";
    const data = Buffer.from(dataUrl[2], "base64");
    return { data, mimeType, extension, ...(await imageDimensions(data)), ...(includeSvgFallback ? await svgFallback(data, mimeType) : {}) };
  }
  const data = await fs.readFile(source);
  // Trust the magic bytes over the filename: downloaded assets (e.g. prefetched
  // remote images) routinely carry a wrong or missing extension.
  const sniffed = sniffImageType(data);
  const declaredExtension = source.split(".").pop()?.toLowerCase() || "png";
  const extension = sniffed?.extension ?? (declaredExtension === "jpeg" ? "jpg" : declaredExtension);
  const mimeType = sniffed?.mimeType ?? (extension === "jpg" ? "image/jpeg" : extension === "svg" ? "image/svg+xml" : extension === "gif" ? "image/gif" : extension === "webp" ? "image/webp" : "image/png");
  return { data, mimeType, extension, ...(await imageDimensions(data)), ...(includeSvgFallback ? await svgFallback(data, mimeType) : {}) };
}

async function imageDimensions(data) {
  try {
    const metadata = await sharp(data).metadata();
    return { width: metadata.width ?? null, height: metadata.height ?? null };
  } catch {
    return { width: null, height: null };
  }
}

async function svgFallback(data, mimeType) {
  if (mimeType !== "image/svg+xml") return {};
  try {
    return { fallbackData: await sharp(data).png().toBuffer(), fallbackExtension: "png" };
  } catch {
    return {};
  }
}

function imageXml(element, index, entry) {
  const payload = entry.payload ?? {};
  const sourceCrop = normalizeCrop(element.crop);
  const crop = sourceCrop ?? (element.fit === "cover" ? (element.focalPoint ? focalPointCrop(payload.width, payload.height, element.position.width, element.position.height, element.focalPoint) : coverCrop(payload.width, payload.height, element.position.width, element.position.height)) : null);
  const p = !crop && element.fit === "contain" ? containPosition(element.position, payload.width, payload.height) : element.position;
  const name = escapeXml(element.name ?? `image-${index}`);
  const description = element.alt ? ` descr="${escapeXml(element.alt)}"` : "";
  const opacity = Math.max(0, Math.min(1, Number(element.opacity ?? 1)));
  const alpha = opacity < 1 ? `<a:alphaModFix amt="${Math.round(opacity * 100000)}"/>` : "";
  const cropValue = (value) => {
    const raw = Number(value ?? 0);
    const normalized = raw <= 1 ? raw * 100000 : raw <= 100 ? raw * 1000 : raw;
    return Math.round(Math.max(0, Math.min(100000, normalized)));
  };
  const srcRect = crop ? `<a:srcRect l="${cropValue(crop.left)}" t="${cropValue(crop.top)}" r="${cropValue(crop.right)}" b="${cropValue(crop.bottom)}"/>` : "";
  const blip = entry.fallbackRelationshipId
    ? `<a:blip r:embed="${entry.fallbackRelationshipId}">${alpha}<a:extLst><a:ext uri="{28A0092B-C50C-407E-A947-70E740481C1C}"><a14:useLocalDpi val="0"/></a:ext><a:ext uri="{96DAC541-7B7A-43D3-8B79-37D633B846F1}"><asvg:svgBlip xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main" r:embed="${entry.relationshipId}"/></a:ext></a:extLst></a:blip>`
    : payload.mimeType === "image/svg+xml"
      ? `<a:blip>${alpha}<a:extLst><a:ext uri="{96DAC541-7B7A-43D3-8B79-37D633B846F1}"><asvg:svgBlip xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main" r:embed="${entry.relationshipId}"/></a:ext></a:extLst></a:blip>`
    : `<a:blip r:embed="${entry.relationshipId}">${alpha}</a:blip>`;
  return `<p:pic><p:nvPicPr><p:cNvPr id="${index + 2}" name="${name}"${roleMetadataXml(element)}${description}/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>${nonVisualPropertiesXml(element)}</p:nvPicPr><p:blipFill>${blip}${srcRect}<a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr>${transformXml(p, element)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>`;
}

function groupTransformXml(position) {
  return `<a:xfrm><a:off x="${emu(position.left)}" y="${emu(position.top)}"/><a:ext cx="${emu(position.width)}" cy="${emu(position.height)}"/><a:chOff x="0" y="0"/><a:chExt cx="${emu(position.width)}" cy="${emu(position.height)}"/></a:xfrm>`;
}

function backgroundXml(color) {
  if (!color) return "";
  return `<p:bg><p:bgPr>${solidFill(color)}<a:effectLst/></p:bgPr></p:bg>`;
}

function elementXml(element, index, imageByElement, chartByElement, counter, hyperlinkMap = new Map(), inheritedHidden = false) {
  const currentIndex = counter.value++;
  const hidden = inheritedHidden || element.hidden === true;
  const effectiveElement = hidden && element.hidden !== true ? { ...element, hidden: true } : element;
  // Relationship-free fragments imported from an OOXML feature we do not yet
  // model are kept as a first-class preservation envelope. This lets the
  // self-controlled writer round-trip extension objects without pretending
  // that their semantics are editable in the IR.
  if (effectiveElement.type === "raw-ooxml" && typeof effectiveElement.rawXml === "string" && effectiveElement.rawXml.trim()) return effectiveElement.rawXml;
  if (effectiveElement.type === "group") {
    if (effectiveElement.smartArt?.native) return "";
    const children = [...(effectiveElement.children ?? [])].sort((a, b) => (a.zIndex ?? 0) - (b.zIndex ?? 0));
    const tree = children.map((child) => elementXml(child, currentIndex, imageByElement, chartByElement, counter, hyperlinkMap, hidden)).join("");
    const name = escapeXml(effectiveElement.name ?? `group-${index}`);
    return `<p:grpSp><p:nvGrpSpPr><p:cNvPr id="${currentIndex + 2}" name="${name}"${roleMetadataXml(effectiveElement)}/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>${groupTransformXml(effectiveElement.position)}</p:grpSpPr>${tree}</p:grpSp>`;
  }
  if (effectiveElement.type === "image") {
    const entry = imageByElement.get(element) ?? imageByElement.get(effectiveElement);
    return imageXml(effectiveElement, currentIndex, entry);
  }
  if (effectiveElement.type === "table") return tableXml(effectiveElement, currentIndex);
  if (effectiveElement.type === "chart") return chartFrameXml(effectiveElement, currentIndex, chartByElement.get(element)?.relationshipId ?? chartByElement.get(effectiveElement).relationshipId);
  if (effectiveElement.type === "formula") return formulaXml(effectiveElement, currentIndex);
  return shapeXml(effectiveElement, currentIndex, hyperlinkMap);
}

function smartArtAlternateXml(entry, index, imageByElement, chartByElement, counter) {
  const element = entry.element;
  const fallbackElement = {
    ...element,
    smartArt: { ...element.smartArt, native: false, nativeOnly: false },
  };
  if (!smartArtNativePartsAreFresh(element.smartArt)) {
    fallbackElement.children = compileDiagram(fallbackElement.smartArt, element.position, {});
  }
  const fallback = elementXml(fallbackElement, index, imageByElement, chartByElement, counter);
  return `<mc:AlternateContent><mc:Choice Requires="dgm">${smartArtFrameXml(element, 1000 + index, entry.dataRelationshipId, entry.layoutRelationshipId, entry.quickStyleRelationshipId, entry.colorsRelationshipId)}</mc:Choice><mc:Fallback>${fallback}</mc:Fallback></mc:AlternateContent>`;
}

function elementSpidMap(elements = []) {
  const map = new Map();
  const counter = { value: 0 };
  const visit = (element) => {
    const spid = counter.value++ + 2;
    if (element?.id !== undefined && element?.id !== null) map.set(String(element.id), spid);
    if (element?.sourceId !== undefined && element?.sourceId !== null && !map.has(String(element.sourceId))) map.set(String(element.sourceId), spid);
    if (element?.type === "group") for (const child of element.children ?? []) visit(child);
  };
  for (const element of [...elements].sort((a, b) => (a.zIndex ?? 0) - (b.zIndex ?? 0))) visit(element);
  return map;
}

function collectHyperlinkTargets(elements = []) {
  const targets = new Set();
  walkElements(elements, (element) => {
    if (element.type !== "text") return;
    const candidates = [element.hyperlink, element.link, element.style?.hyperlink, element.style?.link, ...(element.runs ?? []).flatMap((run) => [run?.hyperlink, run?.link])];
    for (const candidate of candidates) {
      const target = hyperlinkTarget(candidate);
      if (target) targets.add(target);
    }
  });
  return [...targets];
}

function remapRawRelationshipIds(rawXml, relationshipMap = {}) {
  return String(rawXml ?? "").replace(/(\br:(?:id|embed|link)\s*=\s*["'])([^"']+)(["'])/gu, (match, prefix, sourceId, suffix) => {
    const mapped = relationshipMap[sourceId];
    return mapped ? `${prefix}${mapped}${suffix}` : match;
  });
}

function rawPartOverridesForDeck(deck) {
  const entries = [];
  for (const slide of deck?.slides ?? []) {
    walkElements(slide.elements, (element) => {
      for (const relationship of element.type === "raw-ooxml" ? (element.rawRelationships ?? []) : []) {
        if (relationship.part && relationship.contentType) entries.push({ part: relationship.part, contentType: relationship.contentType });
      }
      for (const part of element.type === "raw-ooxml" ? (element.rawPartGraph ?? []) : []) {
        if (part.part && part.contentType && !part.part.endsWith(".rels")) entries.push({ part: part.part, contentType: part.contentType });
      }
    });
  }
  return [...new Map(entries.map((entry) => [entry.part, entry])).values()];
}

function slideXml(slide, index, slideSize, imageEntries = [], chartEntries = [], smartArtEntries = [], hyperlinkEntries = []) {
  const elements = [...slide.elements].sort((a, b) => (a.zIndex ?? 0) - (b.zIndex ?? 0));
  let unsupported = null;
  walkElements(elements, (element) => {
    if (!unsupported && !["text", "shape", "image", "table", "chart", "formula", "group", "raw-ooxml"].includes(element.type)) unsupported = element;
  });
  if (unsupported) throw new Error(`OOXML basic renderer does not support ${unsupported.type}; use the full renderer or add an OOXML adapter.`);
  walkElements(elements, (element) => { if (element.type === "chart") assertChartData(element); });
  const imageByElement = new Map(imageEntries.map((entry) => [entry.element, entry]));
  const chartByElement = new Map(chartEntries.map((entry) => [entry.element, entry]));
  const hyperlinkMap = new Map(hyperlinkEntries.map((entry) => [entry.target, entry.relationshipId]));
  const counter = { value: 0 };
  const tree = elements.map((element, elementIndex) => elementXml(element, elementIndex, imageByElement, chartByElement, counter, hyperlinkMap)).join("");
  const smartArtTree = smartArtEntries.map((entry, smartArtIndex) => entry.element.smartArt?.nativeOnly
    ? smartArtFrameXml(entry.element, 1000 + smartArtIndex, entry.dataRelationshipId, entry.layoutRelationshipId, entry.quickStyleRelationshipId, entry.colorsRelationshipId)
    : smartArtAlternateXml(entry, smartArtIndex, imageByElement, chartByElement, counter)).join("");
  const timing = timingXml(slide, elementSpidMap(elements));
  let hasFormula = false;
  walkElements(elements, (element) => { if (element.type === "formula") hasFormula = true; });
  const extraNamespaces = [
    hasFormula ? `xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main"` : "",
    smartArtEntries.length ? `xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram"` : "",
    hasFormula || smartArtEntries.length ? `xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"` : "",
    hasFormula ? `mc:Ignorable="a14"` : "",
  ].filter(Boolean).join(" ");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"${slide.hidden ? " show=\"0\"" : ""}${extraNamespaces ? ` ${extraNamespaces}` : ""}><p:cSld name="${escapeXml(slide.name ?? `Slide ${index + 1}`)}">${backgroundXml(slide.background)}<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>${groupTransformXml({ left: 0, top: 0, width: slideSize.width, height: slideSize.height })}</p:grpSpPr>${tree}${smartArtTree}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>${transitionXml(slide.transition)}${timing}</p:sld>`;
}

const contentTypes = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Default Extension="jpg" ContentType="image/jpeg"/><Default Extension="jpeg" ContentType="image/jpeg"/><Default Extension="gif" ContentType="image/gif"/><Default Extension="webp" ContentType="image/webp"/><Default Extension="svg" ContentType="image/svg+xml"/><Default Extension="fntdata" ContentType="application/x-fontdata"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/><Override PartName="/ppt/presProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"/><Override PartName="/ppt/viewProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml"/><Override PartName="/ppt/tableStyles.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"/><Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/><Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/><Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>`;

function addSlideContentTypes(slides, chartCount = 0, layoutCount = 1, smartArtCount = 0, smartArtDrawingNumbers = [], rawPartOverrides = []) {
  const charts = Array.from({ length: chartCount }, (_, index) => `<Override PartName="/ppt/charts/chart${index + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>`).join("");
  const diagrams = Array.from({ length: smartArtCount }, (_, index) => `<Override PartName="/ppt/diagrams/data${index + 1}.xml" ContentType="${DIAGRAM_DATA_CONTENT_TYPE}"/><Override PartName="/ppt/diagrams/layout${index + 1}.xml" ContentType="${DIAGRAM_LAYOUT_CONTENT_TYPE}"/><Override PartName="/ppt/diagrams/quickStyle${index + 1}.xml" ContentType="${DIAGRAM_STYLE_CONTENT_TYPE}"/><Override PartName="/ppt/diagrams/colors${index + 1}.xml" ContentType="${DIAGRAM_COLORS_CONTENT_TYPE}"/>`).join("");
  const drawings = smartArtDrawingNumbers.map((number) => `<Override PartName="/ppt/diagrams/drawing${number}.xml" ContentType="${DIAGRAM_DRAWING_CONTENT_TYPE}"/>`).join("");
  const rawParts = [...new Map((rawPartOverrides ?? []).filter((entry) => entry?.part && entry?.contentType).map((entry) => [entry.part, entry])).values()]
    .map((entry) => `<Override PartName="/${escapeXml(entry.part)}" ContentType="${escapeXml(entry.contentType)}"/>`).join("");
  const additionalLayouts = Array.from({ length: Math.max(0, layoutCount - 1) }, (_, index) => `<Override PartName="/ppt/slideLayouts/slideLayout${index + 2}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>`).join("");
  return `${contentTypes}${additionalLayouts}<Override PartName="/ppt/notesMasters/notesMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"/>${charts}${diagrams}${drawings}${rawParts}${slides.map((_, index) => `<Override PartName="/ppt/slides/slide${index + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/><Override PartName="/ppt/notesSlides/notesSlide${index + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>`).join("")}</Types>`;
}

function embeddedFontListXml(fonts, slideCount) {
  if (!fonts.length) return "";
  return `<p:embeddedFontLst>${fonts.map((font, index) => `<p:embeddedFont><p:font typeface="${escapeXml(font.family)}" pitchFamily="${escapeXml(font.pitchFamily)}" charset="${escapeXml(font.charset)}"/><p:${font.style} r:id="rId${slideCount + 7 + index}"/></p:embeddedFont>`).join("")}</p:embeddedFontLst>`;
}

function sectionGuid(sectionId) {
  const digest = crypto.createHash("sha1").update(`open-ppt-engine-section:${String(sectionId)}`).digest("hex").slice(0, 32);
  return `{${digest.slice(0, 8)}-${digest.slice(8, 12)}-${digest.slice(12, 16)}-${digest.slice(16, 20)}-${digest.slice(20)}}`;
}

function presentationSectionsXml(slides = []) {
  const sections = new Map();
  slides.forEach((slide, index) => {
    const sourceId = String(slide.sectionId ?? "").trim();
    if (!sourceId) return;
    const current = sections.get(sourceId) ?? {
      id: sectionGuid(sourceId),
      name: String(slide.sectionName ?? sourceId),
      slideIds: [],
    };
    current.slideIds.push(256 + index);
    if (!current.name || current.name === sourceId) current.name = String(slide.sectionName ?? sourceId);
    sections.set(sourceId, current);
  });
  if (sections.size === 0) return { xml: "", namespaces: "" };
  const sectionXml = [...sections.values()].map((section) => `<p14:section name="${escapeXml(section.name)}" id="${section.id}"><p14:sldIdLst>${section.slideIds.map((id) => `<p14:sldId id="${id}"/>`).join("")}</p14:sldIdLst></p14:section>`).join("");
  return {
    xml: `<p:extLst><p:ext uri="{521415D9-36F7-43E2-AB2F-B90AF26B5E84}"><p14:sectionLst>${sectionXml}</p14:sectionLst></p:ext></p:extLst>`,
    namespaces: ` xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" mc:Ignorable="p14"`,
  };
}

function presentationXml(slides, slideSize, theme = {}, embeddedFonts = [], textStyles = {}) {
  const slideIds = slides.map((_, index) => `<p:sldId id="${256 + index}" r:id="rId${index + 2}"/>`).join("");
  const fonts = theme.fonts ?? {};
  const body = escapeXml(fonts.body ?? "Aptos");
  const cjk = escapeXml(fonts.cjk ?? fonts.fallbacks?.cjk?.[0] ?? body);
  const size = Math.round(Number(theme.type?.body ?? 16) * 100);
  const fontAttributes = embeddedFonts.length ? ` embedTrueTypeFonts="1"` : "";
  const sections = presentationSectionsXml(slides);
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation${fontAttributes} saveSubsetFonts="1" autoCompressPictures="0" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"${sections.namespaces}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>${slideIds}</p:sldIdLst><p:notesMasterIdLst><p:notesMasterId r:id="rId${slides.length + 2}"/></p:notesMasterIdLst>${embeddedFontListXml(embeddedFonts, slides.length)}<p:sldSz cx="${emu(slideSize.width)}" cy="${emu(slideSize.height)}"/><p:notesSz cx="${emu(720)}" cy="${emu(slideSize.width)}"/>${presentationDefaultTextStyleXml({ ...theme, type: { ...theme.type, body: theme.type?.body ?? size / 100 } }, textStyles)}${sections.xml}</p:presentation>`;
}

function presentationRels(slides, embeddedFonts = []) {
  const slideRels = slides.map((_, index) => `<Relationship Id="rId${index + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide${index + 1}.xml"/>`).join("");
  const base = `<Relationship Id="rId${slides.length + 3}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/presProps" Target="presProps.xml"/><Relationship Id="rId${slides.length + 4}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/viewProps" Target="viewProps.xml"/><Relationship Id="rId${slides.length + 5}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/><Relationship Id="rId${slides.length + 6}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/tableStyles" Target="tableStyles.xml"/>`;
  const fontRels = embeddedFonts.map((font, index) => `<Relationship Id="rId${slides.length + 7 + index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/font" Target="fonts/${font.fileName}"/>`).join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>${slideRels}<Relationship Id="rId${slides.length + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster" Target="notesMasters/notesMaster1.xml"/>${base}${fontRels}</Relationships>`;
}

function slideMasterRels(layouts) {
  const layoutRelationships = layouts.map((_, index) => `<Relationship Id="rId${index + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout${index + 1}.xml"/>`).join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${layoutRelationships}<Relationship Id="rId${layouts.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/></Relationships>`;
}

function smartArtDataRels(entry) {
  if (!entry.drawingFileName || !entry.drawingRelationshipId) return null;
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="${entry.drawingRelationshipId}" Type="${DIAGRAM_DRAWING_REL}" Target="${entry.drawingFileName}"/></Relationships>`;
}

function slideLayoutRels() {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>`;
}

function slideRels(imageEntries = [], chartEntries = [], slideIndex = 0, layoutIndex = 0, smartArtEntries = [], hyperlinkEntries = [], rawRelationshipEntries = []) {
  const images = imageEntries.flatMap((entry) => [
    ...(entry.fallbackRelationshipId ? [`<Relationship Id="${entry.fallbackRelationshipId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/${entry.fallbackFileName}"/>`] : []),
    `<Relationship Id="${entry.relationshipId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/${entry.fileName}"/>`,
  ]).join("");
  const charts = chartEntries.map((entry) => `<Relationship Id="${entry.relationshipId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/${entry.fileName}"/>`).join("");
  const smartArts = smartArtEntries.map((entry) => `<Relationship Id="${entry.dataRelationshipId}" Type="${DIAGRAM_DATA_REL}" Target="../diagrams/${entry.dataFileName}"/><Relationship Id="${entry.layoutRelationshipId}" Type="${DIAGRAM_LAYOUT_REL}" Target="../diagrams/${entry.layoutFileName}"/><Relationship Id="${entry.quickStyleRelationshipId}" Type="${DIAGRAM_QUICK_STYLE_REL}" Target="../diagrams/${entry.quickStyleFileName}"/><Relationship Id="${entry.colorsRelationshipId}" Type="${DIAGRAM_COLORS_REL}" Target="../diagrams/${entry.colorsFileName}"/>`).join("");
  const hyperlinks = hyperlinkEntries.map((entry) => `<Relationship Id="${entry.relationshipId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="${escapeXml(entry.target)}" TargetMode="External"/>`).join("");
  const rawRelationships = rawRelationshipEntries.map((entry) => `<Relationship Id="${entry.relationshipId}" Type="${escapeXml(entry.type ?? "http://schemas.openxmlformats.org/officeDocument/2006/relationships/unknown")}" Target="${escapeXml(entry.target)}"${entry.targetMode ? ` TargetMode="${escapeXml(entry.targetMode)}"` : ""}/>`).join("");
  const imageRelationshipCount = imageEntries.reduce((count, entry) => count + 1 + (entry.fallbackRelationshipId ? 1 : 0), 0);
  const smartArtRelationshipCount = smartArtEntries.reduce((count, entry) => count + 2 + (entry.quickStyleRelationshipId ? 1 : 0) + (entry.colorsRelationshipId ? 1 : 0), 0);
  const notesRelationshipId = `rId${imageRelationshipCount + chartEntries.length + smartArtRelationshipCount + hyperlinkEntries.length + rawRelationshipEntries.length + 2}`;
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout${layoutIndex + 1}.xml"/>${images}${charts}${smartArts}${hyperlinks}${rawRelationships}<Relationship Id="${notesRelationshipId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide${slideIndex + 1}.xml"/></Relationships>`;
}

function notesParagraphs(notes) {
  const text = String(notes ?? "");
  return (text ? text.split("\n") : [""]).map((line) => `<a:p><a:r><a:rPr lang="zh-CN"/><a:t>${escapeXml(line)}</a:t></a:r><a:endParaRPr lang="zh-CN"/></a:p>`).join("");
}

function notesSlideXml(slide, index) {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:notes xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>${groupTransformXml({ left: 0, top: 0, width: 720, height: 540 })}</p:grpSpPr><p:sp><p:nvSpPr><p:cNvPr id="2" name="Notes Placeholder"/><p:cNvSpPr/><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>${notesParagraphs(slide.notes)}</p:txBody></p:sp></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>`;
}

function notesSlideRels(slideIndex) {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster" Target="../notesMasters/notesMaster1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="../slides/slide${slideIndex + 1}.xml"/></Relationships>`;
}

const notesStyleXml = Array.from({ length: 9 }, (_, index) => {
  const level = index + 1;
  const margin = index * 457200;
  return `<a:lvl${level}pPr marL="${margin}" algn="l" defTabSz="914400" rtl="0" eaLnBrk="1" latinLnBrk="0" hangingPunct="1"><a:defRPr sz="1200" kern="1200"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/><a:cs typeface="+mn-cs"/></a:defRPr></a:lvl${level}pPr>`;
}).join("");
const notesMasterXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:notesMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>${groupTransformXml({ left: 0, top: 0, width: 720, height: 540 })}</p:grpSpPr></p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/><p:notesStyle>${notesStyleXml}</p:notesStyle></p:notesMaster>`;
const notesMasterRels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/></Relationships>`;

const packageRels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>`;
const presPropsXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentationPr xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>`;
const viewPropsXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:viewPr xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:normalViewPr horzBarState="maximized"><p:restoredLeft sz="15611"/><p:restoredTop sz="94610"/></p:normalViewPr><p:slideViewPr><p:cSldViewPr snapToGrid="0" snapToObjects="1"><p:cViewPr varScale="1"><p:scale><a:sx n="136" d="100"/><a:sy n="136" d="100"/></p:scale><p:origin x="216" y="312"/></p:cViewPr><p:guideLst/></p:cSldViewPr></p:slideViewPr><p:notesTextViewPr><p:cViewPr><p:scale><a:sx n="1" d="1"/><a:sy n="1" d="1"/></p:scale><p:origin x="0" y="0"/></p:cViewPr></p:notesTextViewPr><p:gridSpacing cx="76200" cy="76200"/></p:viewPr>`;

function docPropsAppXml(deck) {
  const slideCount = deck.slides.length;
  const fonts = deck.theme?.fonts ?? {};
  const partTitles = [...new Set([
    fonts.heading ?? "Aptos Display",
    fonts.body ?? "Aptos",
    fonts.cjk ?? "Microsoft YaHei",
    "Open PPT",
    ...deck.slides.map((slide, index) => slide.name ?? `Slide ${index + 1}`),
  ])];
  // TitlesOfParts declares baseType="lpstr"; PowerPoint expects direct
  // <vt:lpstr> children here, not <vt:variant> wrappers.
  const fontTitles = partTitles.map((title) => `<vt:lpstr>${escapeXml(title)}</vt:lpstr>`).join("");
  const headings = `<vt:vector size="6" baseType="variant"><vt:variant><vt:lpstr>Fonts Used</vt:lpstr></vt:variant><vt:variant><vt:i4>${[...new Set([fonts.heading ?? "Aptos Display", fonts.body ?? "Aptos", fonts.cjk ?? "Microsoft YaHei"])].length}</vt:i4></vt:variant><vt:variant><vt:lpstr>Theme</vt:lpstr></vt:variant><vt:variant><vt:i4>1</vt:i4></vt:variant><vt:variant><vt:lpstr>Slide Titles</vt:lpstr></vt:variant><vt:variant><vt:i4>${slideCount}</vt:i4></vt:variant></vt:vector>`;
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><TotalTime>0</TotalTime><Words>0</Words><Application>Open PPT Engine</Application><PresentationFormat>On-screen Show (16:9)</PresentationFormat><Paragraphs>0</Paragraphs><Slides>${slideCount}</Slides><Notes>${slideCount}</Notes><HiddenSlides>0</HiddenSlides><MMClips>0</MMClips><ScaleCrop>false</ScaleCrop><HeadingPairs>${headings}</HeadingPairs><TitlesOfParts><vt:vector size="${partTitles.length}" baseType="lpstr">${fontTitles}</vt:vector></TitlesOfParts><Company>${escapeXml(deck.metadata?.company ?? "")}</Company><LinksUpToDate>false</LinksUpToDate><SharedDoc>false</SharedDoc><HyperlinksChanged>false</HyperlinksChanged><AppVersion>1.0</AppVersion></Properties>`;
}

function docPropsCoreXml(deck, { modifiedAt = new Date() } = {}) {
  const now = (modifiedAt instanceof Date ? modifiedAt : new Date(modifiedAt)).toISOString();
  const title = escapeXml(deck.title ?? "Untitled deck");
  const subject = escapeXml(deck.metadata?.subject ?? deck.title ?? "Untitled deck");
  const author = escapeXml(deck.metadata?.author ?? "Open PPT Engine");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>${title}</dc:title><dc:subject>${subject}</dc:subject><dc:creator>${author}</dc:creator><cp:lastModifiedBy>${author}</cp:lastModifiedBy><cp:revision>1</cp:revision><dcterms:created xsi:type="dcterms:W3CDTF">${now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">${now}</dcterms:modified></cp:coreProperties>`;
}
const slideMasterXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>${groupTransformXml({ left: 0, top: 0, width: 1280, height: 720 })}</p:grpSpPr></p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/><p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>`;
const slideLayoutXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1"><p:cSld name="Blank"><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>${groupTransformXml({ left: 0, top: 0, width: 1280, height: 720 })}</p:grpSpPr></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>`;
const themeFormatSchemeXml = `<a:fmtScheme name="Open"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:gradFill rotWithShape="1"><a:gsLst><a:gs pos="0"><a:schemeClr val="phClr"><a:lumMod val="110000"/><a:satMod val="105000"/><a:tint val="67000"/></a:schemeClr></a:gs><a:gs pos="50000"><a:schemeClr val="phClr"><a:lumMod val="105000"/><a:satMod val="103000"/><a:tint val="73000"/></a:schemeClr></a:gs><a:gs pos="100000"><a:schemeClr val="phClr"><a:lumMod val="105000"/><a:satMod val="109000"/><a:tint val="81000"/></a:schemeClr></a:gs></a:gsLst><a:lin ang="5400000" scaled="0"/></a:gradFill><a:gradFill rotWithShape="1"><a:gsLst><a:gs pos="0"><a:schemeClr val="phClr"><a:satMod val="103000"/><a:lumMod val="102000"/><a:tint val="94000"/></a:schemeClr></a:gs><a:gs pos="50000"><a:schemeClr val="phClr"><a:satMod val="110000"/><a:lumMod val="100000"/><a:shade val="100000"/></a:schemeClr></a:gs><a:gs pos="100000"><a:schemeClr val="phClr"><a:satMod val="120000"/><a:lumMod val="99000"/><a:shade val="78000"/></a:schemeClr></a:gs></a:gsLst><a:lin ang="5400000" scaled="0"/></a:gradFill></a:fillStyleLst><a:lnStyleLst><a:ln w="6350" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/><a:miter lim="800000"/></a:ln><a:ln w="12700" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/><a:miter lim="800000"/></a:ln><a:ln w="19050" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/><a:miter lim="800000"/></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst><a:outerShdw blurRad="57150" dist="19050" dir="5400000" algn="ctr" rotWithShape="0"><a:srgbClr val="000000"><a:alpha val="63000"/></a:srgbClr></a:outerShdw></a:effectLst></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"><a:tint val="95000"/><a:satMod val="170000"/></a:schemeClr></a:solidFill><a:gradFill rotWithShape="1"><a:gsLst><a:gs pos="0"><a:schemeClr val="phClr"><a:tint val="93000"/><a:satMod val="150000"/><a:shade val="98000"/><a:lumMod val="102000"/></a:schemeClr></a:gs><a:gs pos="50000"><a:schemeClr val="phClr"><a:tint val="98000"/><a:satMod val="130000"/><a:shade val="90000"/><a:lumMod val="103000"/></a:schemeClr></a:gs><a:gs pos="100000"><a:schemeClr val="phClr"><a:shade val="63000"/><a:satMod val="120000"/></a:schemeClr></a:gs></a:gsLst><a:lin ang="5400000" scaled="0"/></a:gradFill></a:bgFillStyleLst></a:fmtScheme>`;
const themeXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Open PPT"><a:themeElements><a:clrScheme name="Open"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="1E1E1E"/></a:dk2><a:lt2><a:srgbClr val="F7F5F0"/></a:lt2><a:accent1><a:srgbClr val="B32635"/></a:accent1><a:accent2><a:srgbClr val="2A2B2E"/></a:accent2><a:accent3><a:srgbClr val="D3CEC3"/></a:accent3><a:accent4><a:srgbClr val="FFFFFF"/></a:accent4><a:accent5><a:srgbClr val="6E6B65"/></a:accent5><a:accent6><a:srgbClr val="8E1B27"/></a:accent6><a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme><a:fontScheme name="Open"><a:majorFont><a:latin typeface="Aptos Display"/><a:ea typeface="Microsoft YaHei"/><a:cs typeface="Aptos Display"/></a:majorFont><a:minorFont><a:latin typeface="Aptos"/><a:ea typeface="Microsoft YaHei"/><a:cs typeface="Aptos"/></a:minorFont></a:fontScheme>${themeFormatSchemeXml}<a:objectDefaults/><a:extraClrSchemeLst/></a:themeElements></a:theme>`;

function placeholderXml(placeholder, index, idOffset = 0) {
  const position = placeholder.position ?? { left: 0, top: 0, width: 0, height: 0 };
  const type = escapeXml(placeholder.type ?? "body");
  const idx = Number.isFinite(Number(placeholder.idx)) ? Number(placeholder.idx) : index;
  const text = placeholder.text ? `<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="zh-CN"/><a:t>${escapeXml(placeholder.text)}</a:t></a:r><a:endParaRPr lang="zh-CN"/></a:p></p:txBody>` : "";
  return `<p:sp><p:nvSpPr><p:cNvPr id="${index + idOffset + 2}" name="${escapeXml(placeholder.name ?? `${type}-${idx}`)}"/><p:cNvSpPr/><p:nvPr><p:ph type="${type}" idx="${idx}"/></p:nvPr></p:nvSpPr><p:spPr>${transformXml(position)}</p:spPr>${text}</p:sp>`;
}

function inheritedElementSupported(element) {
  if (["text", "shape", "table", "formula"].includes(element?.type)) return true;
  if (element?.type === "group") return (element.children ?? []).every(inheritedElementSupported);
  return false;
}

function elementTreeXml(elements = []) {
  const counter = { value: 0 };
  const imageByElement = new Map();
  const chartByElement = new Map();
  const tree = [...elements].sort((a, b) => (a.zIndex ?? 0) - (b.zIndex ?? 0)).map((element, index) => elementXml(element, index, imageByElement, chartByElement, counter)).join("");
  return { tree, nextId: counter.value };
}

function buildSlideMasterXml(slideSize, layouts, master = {}, elements = []) {
  const layoutIds = layouts.map((layout, index) => `<p:sldLayoutId id="${2147483649 + index}" r:id="rId${index + 1}"/>`).join("");
  const rendered = elementTreeXml(elements);
  const placeholders = (master.placeholders ?? []).map((placeholder, index) => placeholderXml(placeholder, index, rendered.nextId)).join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld>${backgroundXml(master.background) || `<p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>`}<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>${groupTransformXml({ left: 0, top: 0, width: slideSize.width, height: slideSize.height })}</p:grpSpPr>${rendered.tree}${placeholders}</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/><p:sldLayoutIdLst>${layoutIds}</p:sldLayoutIdLst>${masterTextStylesXml(master.textStyles ?? {})}</p:sldMaster>`;
}

function buildSlideLayoutXml(layout, slideSize, elements = []) {
  const rendered = elementTreeXml(elements);
  const placeholders = (layout.placeholders ?? []).map((placeholder, index) => placeholderXml(placeholder, index, rendered.nextId)).join("");
  const background = backgroundXml(layout.background);
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="${escapeXml(layout.type ?? "blank")}" preserve="1"><p:cSld name="${escapeXml(layout.name ?? "Layout")}">${background || `<p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>`}<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>${groupTransformXml({ left: 0, top: 0, width: slideSize.width, height: slideSize.height })}</p:grpSpPr>${rendered.tree}${placeholders}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>`;
}

function buildThemeXml(theme = {}) {
  const colors = theme.colors ?? {};
  const fonts = theme.fonts ?? {};
  const color = (name, fallback) => hex(colors[name] ?? fallback);
  const heading = escapeXml(fonts.heading ?? "Aptos Display");
  const body = escapeXml(fonts.body ?? "Aptos");
  const cjk = escapeXml(fonts.cjk ?? fonts.fallbacks?.cjk?.[0] ?? body);
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Open PPT"><a:themeElements><a:clrScheme name="Open"><a:dk1><a:sysClr val="windowText" lastClr="${color("ink", "#1E1E1E")}"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="${color("white", "#FFFFFF")}"/></a:lt1><a:dk2><a:srgbClr val="${color("ink", "#1E1E1E")}"/></a:dk2><a:lt2><a:srgbClr val="${color("paper", "#F7F5F0")}"/></a:lt2><a:accent1><a:srgbClr val="${color("accent", "#B32635")}"/></a:accent1><a:accent2><a:srgbClr val="${color("slate", "#2A2B2E")}"/></a:accent2><a:accent3><a:srgbClr val="${color("line", "#D3CEC3")}"/></a:accent3><a:accent4><a:srgbClr val="${color("white", "#FFFFFF")}"/></a:accent4><a:accent5><a:srgbClr val="${color("muted", "#6E6B65")}"/></a:accent5><a:accent6><a:srgbClr val="${color("accentDark", "#8E1B27")}"/></a:accent6><a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme><a:fontScheme name="Open"><a:majorFont><a:latin typeface="${heading}"/><a:ea typeface="${cjk}"/><a:cs typeface="${heading}"/></a:majorFont><a:minorFont><a:latin typeface="${body}"/><a:ea typeface="${cjk}"/><a:cs typeface="${body}"/></a:minorFont></a:fontScheme>${themeFormatSchemeXml}<a:objectDefaults/><a:extraClrSchemeLst/></a:themeElements></a:theme>`;
}

export async function exportOoxmlBasic(deck, outputPath, {
  embedFonts = false,
  subsetFonts = false,
  strictFontSubset = false,
  subsetFontCommand = "pyftsubset",
  fontAssets = deck?.fontAssets ?? [],
  allowRestrictedFonts = false,
  assetResolver = null,
  svgFallback = false,
  reproducible = true,
} = {}) {
  const reproducibleDate = new Date("1980-01-01T00:00:00.000Z");
  const packageDate = reproducible ? reproducibleDate : new Date();
  // Do not materialize implicit directory entries: their generated timestamps
  // otherwise make two byte-identical packages differ at the ZIP central
  // directory level.
  const zipOptions = { date: packageDate, createFolders: false };
  const embeddedFonts = embedFonts ? await prepareEmbeddedFonts(fontAssets, {
    allowRestricted: allowRestrictedFonts,
    assetResolver,
    subset: subsetFonts,
    subsetText: collectDeckText(deck),
    subsetCommand: subsetFontCommand,
    strictSubset: strictFontSubset,
  }) : [];
  const authoredDeck = resolveDeckLayout(deck, { includeInherited: false });
  const visualDeck = resolveDeckLayout(deck, { includeInherited: true });
  const nativeMasterElements = (authoredDeck.master?.elements ?? []).filter(inheritedElementSupported);
  const nativeLayoutElements = new Map((authoredDeck.layouts ?? []).map((layout) => [layout.id, (layout.elements ?? []).filter(inheritedElementSupported)]));
  const nativeInheritedIds = new Set([
    ...nativeMasterElements.map((element) => element.id),
    ...(authoredDeck.layouts ?? []).flatMap((layout) => (nativeLayoutElements.get(layout.id) ?? []).map((element) => element.id)),
  ]);
  const resolvedDeck = structuredClone(authoredDeck);
  resolvedDeck.slides = authoredDeck.slides.map((slide, index) => {
    const fallbackInherited = (visualDeck.slides[index]?.elements ?? []).filter((element) => element.inheritedFrom && !nativeInheritedIds.has(element.sourceId));
    return { ...slide, elements: [...slide.elements, ...fallbackInherited] };
  });
  const zip = new JSZip();
  const writePart = (name, data) => zip.file(name, data, zipOptions);
  const layouts = Array.isArray(resolvedDeck.layouts) && resolvedDeck.layouts.length > 0 ? resolvedDeck.layouts : [{ id: "layout-blank", name: "Blank", type: "blank", background: null, placeholders: [] }];
  const layoutIndexById = new Map(layouts.map((layout, index) => [layout.id, index]));
  const chartCount = resolvedDeck.slides.reduce((count, slide) => {
    let slideCharts = 0;
    walkElements(slide.elements, (element) => { if (element.type === "chart") slideCharts += 1; });
    return count + slideCharts;
  }, 0);
  const smartArtCount = resolvedDeck.slides.reduce((count, slide) => {
    let slideSmartArts = 0;
    walkElements(slide.elements, (element) => { if (element.type === "group" && element.smartArt?.native) slideSmartArts += 1; });
    return count + slideSmartArts;
  }, 0);
  const smartArtDrawingNumbers = [];
  let smartArtNumber = 0;
  for (const slide of resolvedDeck.slides) {
    walkElements(slide.elements, (element) => {
      if (element.type !== "group" || !element.smartArt?.native) return;
      smartArtNumber += 1;
      if (element.smartArt.rawDrawingXml) smartArtDrawingNumbers.push(smartArtNumber);
    });
  }
  const rawPartOverrides = rawPartOverridesForDeck(resolvedDeck);
  writePart("[Content_Types].xml", addSlideContentTypes(resolvedDeck.slides, chartCount, layouts.length, smartArtCount, smartArtDrawingNumbers, rawPartOverrides));
  writePart("_rels/.rels", packageRels);
  writePart("docProps/app.xml", docPropsAppXml(resolvedDeck));
  writePart("docProps/core.xml", docPropsCoreXml(resolvedDeck, { modifiedAt: packageDate }));
  writePart("ppt/presentation.xml", presentationXml(resolvedDeck.slides, resolvedDeck.slideSize, resolvedDeck.theme, embeddedFonts, resolvedDeck.textStyles));
  writePart("ppt/_rels/presentation.xml.rels", presentationRels(resolvedDeck.slides, embeddedFonts));
  for (const font of embeddedFonts) writePart(`ppt/fonts/${font.fileName}`, font.bytes);
  writePart("ppt/slideMasters/slideMaster1.xml", buildSlideMasterXml(resolvedDeck.slideSize, layouts, resolvedDeck.master, nativeMasterElements));
  writePart("ppt/slideMasters/_rels/slideMaster1.xml.rels", slideMasterRels(layouts));
  for (const [layoutIndex, layout] of layouts.entries()) {
    writePart(`ppt/slideLayouts/slideLayout${layoutIndex + 1}.xml`, buildSlideLayoutXml(layout, resolvedDeck.slideSize, nativeLayoutElements.get(layout.id) ?? []));
    writePart(`ppt/slideLayouts/_rels/slideLayout${layoutIndex + 1}.xml.rels`, slideLayoutRels());
  }
  writePart("ppt/theme/theme1.xml", buildThemeXml(resolvedDeck.theme));
  writePart("ppt/presProps.xml", presPropsXml);
  writePart("ppt/viewProps.xml", viewPropsXml);
  writePart("ppt/tableStyles.xml", tableStylesXmlForDeck(resolvedDeck));
  writePart("ppt/notesMasters/notesMaster1.xml", notesMasterXml);
  writePart("ppt/notesMasters/_rels/notesMaster1.xml.rels", notesMasterRels);
  let mediaIndex = 1;
  const mediaByDigest = new Map();
  let chartIndex = 1;
  let smartArtIndex = 1;
  for (const [slideIndex, slide] of resolvedDeck.slides.entries()) {
    const imageEntries = [];
    walkElements(slide.elements, (element) => { if (element.type === "image") imageEntries.push({ element }); });
    let relationshipIndex = 2;
    for (const [imageIndex, entry] of imageEntries.entries()) {
      const source = await resolveAssetReference(entry.element.source ?? entry.element, assetResolver);
      const payload = await imagePayload(source, { includeSvgFallback: svgFallback });
      entry.payload = payload;
      const mediaDigest = `${bytesDigest(payload.data)}:${payload.fallbackData ? bytesDigest(payload.fallbackData) : ""}`;
      const sharedMedia = mediaByDigest.get(mediaDigest) ?? (() => {
        const value = {
          fileName: `image${mediaIndex++}.${payload.extension}`,
          ...(payload.fallbackData ? { fallbackFileName: `image${mediaIndex++}.${payload.fallbackExtension ?? "png"}` } : {}),
        };
        writePart(`ppt/media/${value.fileName}`, payload.data);
        if (value.fallbackFileName) writePart(`ppt/media/${value.fallbackFileName}`, payload.fallbackData);
        mediaByDigest.set(mediaDigest, value);
        return value;
      })();
      entry.fileName = sharedMedia.fileName;
      if (sharedMedia.fallbackFileName) {
        entry.fallbackFileName = sharedMedia.fallbackFileName;
        entry.fallbackRelationshipId = `rId${relationshipIndex++}`;
      }
      // PowerPoint expects the raster fallback relationship to be the base
      // blip and the SVG relationship to be the extLst svgBlip. The IDs are
      // semantically arbitrary in OOXML, but keeping this order matches the
      // structure emitted by PowerPoint and avoids its repair dialog.
      entry.relationshipId = `rId${relationshipIndex++}`;
    }
    const chartEntries = [];
    walkElements(slide.elements, (element) => { if (element.type === "chart") chartEntries.push({ element }); });
    for (const [chartLocalIndex, entry] of chartEntries.entries()) {
      entry.fileName = `chart${chartIndex++}.xml`;
      entry.relationshipId = `rId${relationshipIndex++}`;
      writePart(`ppt/charts/${entry.fileName}`, chartXml(entry.element, resolvedDeck.theme));
    }
    const smartArtEntries = [];
    walkElements(slide.elements, (element) => { if (element.type === "group" && element.smartArt?.native) smartArtEntries.push({ element }); });
    for (const entry of smartArtEntries) {
      const number = smartArtIndex++;
      entry.dataFileName = `data${number}.xml`;
      entry.layoutFileName = `layout${number}.xml`;
      entry.quickStyleFileName = `quickStyle${number}.xml`;
      entry.colorsFileName = `colors${number}.xml`;
      entry.dataRelationshipId = `rId${relationshipIndex++}`;
      entry.layoutRelationshipId = `rId${relationshipIndex++}`;
      entry.quickStyleRelationshipId = `rId${relationshipIndex++}`;
      entry.colorsRelationshipId = `rId${relationshipIndex++}`;
      writePart(`ppt/diagrams/${entry.dataFileName}`, smartArtDataXml(entry.element.smartArt));
      writePart(`ppt/diagrams/${entry.layoutFileName}`, smartArtLayoutXml(entry.element.smartArt));
      writePart(`ppt/diagrams/${entry.quickStyleFileName}`, smartArtQuickStyleXml(entry.element.smartArt));
      writePart(`ppt/diagrams/${entry.colorsFileName}`, smartArtColorsXml(entry.element.smartArt));
      const drawingXml = smartArtDrawingXml(entry.element.smartArt);
      if (drawingXml) {
        entry.drawingFileName = `drawing${number}.xml`;
        entry.drawingRelationshipId = smartArtDrawingRelationshipId(entry.element.smartArt);
        writePart(`ppt/diagrams/${entry.drawingFileName}`, drawingXml);
        writePart(`ppt/diagrams/_rels/${entry.dataFileName}.rels`, smartArtDataRels(entry));
      }
    }
    const hyperlinkEntries = collectHyperlinkTargets(slide.elements).map((target, index) => ({ target, relationshipId: `rId${relationshipIndex + index}` }));
    relationshipIndex += hyperlinkEntries.length;
    const rawRelationshipEntries = [];
    const rawRelationshipIds = new Map();
    const writtenRawParts = new Set();
    walkElements(slide.elements, (element) => {
      if (element.type !== "raw-ooxml" || !Array.isArray(element.rawRelationships) || element.rawRelationships.length === 0) return;
      const relationshipMap = {};
      for (const relationship of element.rawRelationships) {
        const sourceId = String(relationship.sourceId ?? "");
        if (!sourceId) continue;
        let relationshipId = rawRelationshipIds.get(sourceId);
        if (!relationshipId) {
          relationshipId = `rId${relationshipIndex++}`;
          rawRelationshipIds.set(sourceId, relationshipId);
          rawRelationshipEntries.push({ ...relationship, relationshipId });
        }
        relationshipMap[sourceId] = relationshipId;
        if (relationship.part && relationship.dataBase64 && !writtenRawParts.has(relationship.part)) {
          writePart(relationship.part, Buffer.from(relationship.dataBase64, "base64"));
          writtenRawParts.add(relationship.part);
        }
      }
      element.rawXml = remapRawRelationshipIds(element.rawXml, relationshipMap);
      for (const part of element.rawPartGraph ?? []) {
        if (part.part && part.dataBase64 && !writtenRawParts.has(part.part)) {
          writePart(part.part, Buffer.from(part.dataBase64, "base64"));
          writtenRawParts.add(part.part);
        }
      }
    });
    writePart(`ppt/slides/slide${slideIndex + 1}.xml`, slideXml(slide, slideIndex, resolvedDeck.slideSize, imageEntries, chartEntries, smartArtEntries, hyperlinkEntries));
    const layoutIndex = layoutIndexById.get(slide.layoutId) ?? 0;
    writePart(`ppt/slides/_rels/slide${slideIndex + 1}.xml.rels`, slideRels(imageEntries, chartEntries, slideIndex, layoutIndex, smartArtEntries, hyperlinkEntries, rawRelationshipEntries));
    writePart(`ppt/notesSlides/notesSlide${slideIndex + 1}.xml`, notesSlideXml(slide, slideIndex));
    writePart(`ppt/notesSlides/_rels/notesSlide${slideIndex + 1}.xml.rels`, notesSlideRels(slideIndex));
  }
  const data = await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" });
  await fs.writeFile(outputPath, data);
}
