import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import YAML from "yaml";
import sharp from "sharp";
import { addChart, addElement, addFormula, addGroup, addImage, addShape, addSlide, addTable, addText, createDeck } from "../ir/model.mjs";
import { exportOoxmlBasic } from "../render/ooxml-basic.mjs";
import { isPresetGeometry, normalizeGeometry } from "../ir/geometries.mjs";
import { imageTypeFromContentType, imageTypeFromUrl, sniffImageType } from "../assets/image-bytes.mjs";

/**
 * Adapter for the public PPTD v2 format used by open-pptd.
 *
 * PPTD stays the authoring/import format. The adapter deliberately does not
 * call any remote exporter: it compiles the YAML pages into our common
 * IR and lets the local OOXML writer own the final PPTX.
 */

const DEFAULT_PPTD_SIZE = { width: 960, height: 540 };
const ENGINE_CANVAS = { width: 1280, height: 720 };
const SUPPORTED_CHARTS = new Set(["bar", "line", "area", "radar", "scatter", "pie", "donut", "doughnut"]);
const ICON_FALLBACKS = Object.freeze({
  "fas:arrow-right": "→",
  "fas:arrow-left": "←",
  "fas:arrow-up": "↑",
  "fas:arrow-down": "↓",
  "fas:check": "✓",
  "fas:xmark": "×",
  "fas:circle": "●",
  "fas:star": "★",
  "fas:heart": "♥",
  "fas:lightbulb": "💡",
  "fas:triangle-exclamation": "⚠",
  "fas:play": "▶",
  "fas:house": "⌂",
  "fab:github": "◉",
});

function record(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function number(value, fallback = 0) {
  return Number.isFinite(Number(value)) ? Number(value) : fallback;
}

function clamp(value, min = 0, max = 1) {
  return Math.max(min, Math.min(max, Number(value)));
}

function scaleBounds(bounds, scale) {
  const source = Array.isArray(bounds) ? bounds : [0, 0, 0, 0];
  return {
    left: number(source[0]) * scale,
    top: number(source[1]) * scale,
    width: Math.max(0, number(source[2]) * scale),
    height: Math.max(0, number(source[3]) * scale),
  };
}

function tokenKey(value) {
  return String(value ?? "").trim().replace(/^\$/, "");
}

function resolveColor(value, colors = {}, fallback = "#000000") {
  if (value === undefined || value === null || value === "") return fallback;
  if (typeof value === "object") return resolveColor(value.color ?? value.value, colors, fallback);
  const text = String(value).trim();
  if (text.startsWith("$")) return colors[tokenKey(text)] ?? fallback;
  return text;
}

function colorWithOpacity(value, opacity, colors, fallback = "#000000") {
  const color = resolveColor(value, colors, fallback);
  const amount = clamp(opacity, 0, 1);
  if (amount >= 0.999) return color;
  const raw = String(color).replace(/^#/, "");
  if (!/^[0-9a-f]{6}(?:[0-9a-f]{2})?$/iu.test(raw)) return color;
  const existing = raw.length === 8 ? parseInt(raw.slice(6), 16) / 255 : 1;
  return `#${raw.slice(0, 6)}${Math.round(existing * amount * 255).toString(16).padStart(2, "0")}`;
}

function resolveStyle(value, theme, field = "textStyles") {
  if (typeof value === "string" && value.startsWith("$")) return record(theme?.[field]?.[tokenKey(value)]);
  return record(value);
}

function normalizeFontFamily(value, fallback = "Aptos") {
  if (Array.isArray(value)) return String(value[0] ?? fallback);
  return String(value ?? fallback);
}

function parseCssStyle(value, colors, scale = 1) {
  const result = {};
  for (const declaration of String(value ?? "").split(";")) {
    const [rawKey, ...rawValue] = declaration.split(":");
    if (!rawKey || rawValue.length === 0) continue;
    const key = rawKey.trim().toLowerCase();
    const raw = rawValue.join(":").trim();
    if (key === "color") result.color = resolveColor(raw, colors);
    else if (key === "font-size") {
      const size = number(raw.replace(/px$/iu, ""), undefined);
      if (size !== undefined) result.fontSize = size * scale;
    }
    else if (key === "font-family") result.fontFamily = normalizeFontFamily(raw.replace(/^['"]|['"]$/g, ""));
    else if (key === "font-weight") result.bold = raw === "bold" || number(raw) >= 600;
    else if (key === "font-style") result.italic = raw === "italic";
    else if (key === "text-decoration") result.underline = raw.includes("underline");
    else if (key === "line-height") result.lineHeight = raw.endsWith("px") ? number(raw.slice(0, -2), undefined) : number(raw, undefined);
    else if (key === "letter-spacing") result.letterSpacing = number(raw.replace(/px$/iu, ""), undefined);
    else if (key === "text-align") result.align = raw;
    else if (key === "background-color") result.backgroundColor = resolveColor(raw, colors);
  }
  return result;
}

function decodeEntities(value) {
  return String(value ?? "")
    .replace(/&nbsp;/giu, " ")
    .replace(/&amp;/giu, "&")
    .replace(/&lt;/giu, "<")
    .replace(/&gt;/giu, ">")
    .replace(/&quot;/giu, '"')
    .replace(/&#39;/giu, "'");
}

function richText(value, baseStyle, colors, scale = 1) {
  const source = String(value ?? "");
  const runs = [];
  const stack = [{ tag: "root", style: { ...baseStyle } }];
  let paragraphAlign = null;
  const currentStyle = () => stack[stack.length - 1].style;
  const pushText = (text) => {
    const normalized = decodeEntities(text);
    if (!normalized) return;
    const previous = runs[runs.length - 1];
    const style = { ...currentStyle() };
    if (previous && JSON.stringify({ ...previous, text: undefined }) === JSON.stringify(style)) previous.text += normalized;
    else runs.push({ text: normalized, ...style });
  };
  const pushBreak = () => {
    if (runs.length && !runs[runs.length - 1].text.endsWith("\n")) runs[runs.length - 1].text += "\n";
  };
  const openTag = (tag, attributes = "") => {
    const parent = currentStyle();
    const inline = attributes.match(/\bstyle\s*=\s*["']([^"']*)["']/iu)?.[1] ?? "";
    const style = { ...parent, ...parseCssStyle(inline, colors, scale) };
    const href = attributes.match(/\bhref\s*=\s*["']([^"']*)["']/iu)?.[1];
    if (tag === "strong" || tag === "b") style.bold = true;
    if (tag === "em" || tag === "i") style.italic = true;
    if (tag === "u") style.underline = true;
    if (tag === "s" || tag === "strike") style.strike = true;
    if (tag === "sup") style.baseline = "sup";
    if (tag === "sub") style.baseline = "sub";
    if (tag === "a") {
      style.underline = true;
      style.color = "#0563C1";
      style.hyperlink = href;
    }
    if (tag === "p" && style.align) paragraphAlign = style.align;
    if (tag === "li") pushText("• ");
    stack.push({ tag, style });
  };
  const closeTag = (tag) => {
    for (let index = stack.length - 1; index > 0; index -= 1) {
      if (stack[index].tag === tag) {
        stack.splice(index, 1);
        return;
      }
    }
  };

  // YAML block scalars commonly put a newline between adjacent HTML blocks.
  // That whitespace is markup formatting, not an extra empty paragraph.
  const html = source.replace(/>\s+</gu, "><");
  const tokens = html.replace(/<br\s*\/?>/giu, "\n").match(/<[^>]+>|[^<]+/gu) ?? [html];
  for (const token of tokens) {
    if (token.startsWith("<")) {
      const close = token.match(/^<\s*\/\s*([\w-]+)/u);
      if (close) {
        if (["p", "li"].includes(close[1].toLowerCase())) pushBreak();
        closeTag(close[1].toLowerCase());
        continue;
      }
      const open = token.match(/^<\s*([\w-]+)([^>]*)>/u);
      if (open) {
        const tag = open[1].toLowerCase();
        if (tag === "br") pushBreak();
        else openTag(tag, open[2] ?? "");
      }
    } else pushText(token);
  }
  while (runs.length && runs[runs.length - 1].text.endsWith("\n")) runs[runs.length - 1].text = runs[runs.length - 1].text.slice(0, -1);
  return { runs: runs.length ? runs : [{ text: "" }], paragraphAlign };
}

function normalizeTextStyle(content, theme, scale, warnings, context) {
  const colors = theme.colors ?? {};
  const named = resolveStyle(content?.style, theme, "textStyles");
  const source = { ...named, ...record(content) };
  const fontSize = number(source.fontSize, 16) * scale;
  const lineHeight = source.lineHeightPx !== undefined
    ? number(source.lineHeightPx, fontSize) * scale / Math.max(1, fontSize)
    : number(source.lineHeight, 1.15);
  const align = Array.isArray(source.align) ? source.align : [source.align ?? "left", source.valign ?? "top"];
  if (source.gradient) warnings.push({ code: "text-gradient-fallback", context });
  if (source.backgroundColor) warnings.push({ code: "text-highlight-fallback", context });
  return {
    fontFamily: normalizeFontFamily(source.fontFamily, theme.fonts?.body ?? "Aptos"),
    fontSize,
    color: colorWithOpacity(source.color, source.opacity ?? 1, colors, theme.colors?.ink ?? "#1E1E1E"),
    bold: Boolean(source.bold),
    italic: Boolean(source.italic),
    lineHeight,
    align: align[0] === "distributed" ? "justify" : align[0] ?? "left",
    valign: align[1] === "middle" ? "middle" : align[1] === "bottom" ? "bottom" : "top",
    letterSpacing: source.letterSpacing === undefined ? undefined : number(source.letterSpacing) * scale,
  };
}

function convertFill(value, theme, warnings, context, opacity = 1) {
  if (!value || value === "none" || value === "transparent") return "none";
  if (typeof value === "string") return colorWithOpacity(value, opacity, theme.colors, "#000000");
  const source = record(value);
  if (source.type === "solid") return colorWithOpacity(source.color, source.opacity ?? opacity, theme.colors, "#000000");
  if (source.type === "gradient" || Array.isArray(source.stops)) {
    return {
      type: "gradient",
      gradientType: source.gradientType ?? "linear",
      angle: number(source.angle, 0),
      stops: (source.stops ?? []).map((stop) => ({
        position: number(stop.position ?? stop.offset, 0),
        color: colorWithOpacity(stop.color, opacity, theme.colors, "#000000"),
      })),
    };
  }
  if (source.type === "image") {
    warnings.push({ code: "image-fill-fallback", context, source: source.src });
    return "#00000000";
  }
  return colorWithOpacity(source.color ?? source.value, opacity, theme.colors, "#000000");
}

function backgroundOverlayFill(value, theme, warnings, context) {
  if (!value) return null;
  if (typeof value === "string") return convertFill({ type: "solid", color: value }, theme, warnings, context);
  const source = record(value);
  if (source.type === "linear-gradient" || source.type === "radial-gradient") {
    return convertFill({
      type: "gradient",
      gradientType: source.type === "radial-gradient" ? "radial" : "linear",
      angle: number(source.angle, 0),
      stops: source.stops ?? [],
    }, theme, warnings, context);
  }
  if (source.type === "gradient" || Array.isArray(source.stops)) return convertFill(source, theme, warnings, context);
  if (source.color || source.value) return convertFill({ type: "solid", color: source.color ?? source.value, opacity: source.opacity ?? 1 }, theme, warnings, context);
  return null;
}

function convertShadow(shadow, theme) {
  if (!shadow) return undefined;
  const source = record(shadow);
  const offset = Array.isArray(source.offset) ? source.offset : [source.offsetX ?? 0, source.offsetY ?? source.distance ?? 4];
  const x = number(offset[0]);
  const y = number(offset[1]);
  return {
    blur: number(source.blur ?? source.blurRadius, 3),
    distance: Math.hypot(x, y),
    angle: Math.atan2(y, x || 1) * 180 / Math.PI,
    color: resolveColor(source.color, theme.colors, "#000000"),
    opacity: number(source.opacity, 0.25),
  };
}

function convertBorder(border, theme, warnings, context) {
  let source = border;
  if (Array.isArray(border)) {
    const parts = border.filter(Boolean);
    if (parts.length > 1) warnings.push({ code: "asymmetric-border-flattened", context });
    source = parts[0] ?? {};
  }
  const value = record(source);
  const width = number(value.width, 0);
  return {
    color: resolveColor(value.color, theme.colors, "#00000000"),
    width: value.style === "none" ? 0 : width,
    dash: value.style === "dash" ? "dash" : value.style === "dot" ? "dot" : "solid",
  };
}

function transform(value) {
  const source = record(value);
  const flip = Array.isArray(source.flip) ? source.flip : [false, false];
  return { rotation: number(source.rotation, 0), flipH: Boolean(flip[0]), flipV: Boolean(flip[1]) };
}

function linePoints(value) {
  if (Array.isArray(value)) {
    return value.map((point) => {
      if (Array.isArray(point)) return [number(point[0], NaN), number(point[1], NaN)];
      const source = record(point);
      return [number(source.x ?? source.left, NaN), number(source.y ?? source.top, NaN)];
    }).filter((point) => point.every(Number.isFinite));
  }
  return String(value ?? "").trim().split(/\s+/u).map((point) => {
    const values = point.split(",").map(Number);
    return [values[0], values[1]];
  }).filter((point) => point.length >= 2 && point.every(Number.isFinite));
}

function lineBounds(points, scale, fallback) {
  if (points.length < 2) return fallback;
  // points are local to the declared bounds; offset to page coordinates.
  const xs = points.map(([x]) => fallback.left + x * scale);
  const ys = points.map(([, y]) => fallback.top + y * scale);
  const left = Math.min(...xs);
  const top = Math.min(...ys);
  const right = Math.max(...xs);
  const bottom = Math.max(...ys);
  return { left, top, width: Math.max(1, right - left), height: Math.max(1, bottom - top) };
}

function lineSegments(points, scale, parentBounds, line, source, id) {
  // Children are group-local; parentBounds offsets are NOT subtracted here.
  const scaled = points.map(([x, y]) => ({ x: x * scale, y: y * scale }));
  const beginArrowType = source.beginArrowType ?? source.headEnd ?? source.lineHead ?? line.beginArrowType ?? line.headEnd;
  const endArrowType = source.endArrowType ?? source.tailEnd ?? source.lineTail ?? line.endArrowType ?? line.tailEnd;
  return scaled.slice(0, -1).map((from, index) => {
    const to = scaled[index + 1];
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    return {
      type: "shape",
      id: `${id}-segment-${index + 1}`,
      name: `${id} segment ${index + 1}`,
      geometry: "line",
      position: {
        left: Math.min(from.x, to.x),
        top: Math.min(from.y, to.y),
        width: Math.max(1, Math.abs(dx)),
        height: Math.max(1, Math.abs(dy)),
      },
      ...(dx < 0 ? { flipH: true } : {}),
      ...(dy < 0 ? { flipV: true } : {}),
      style: {
        fill: "none",
        line: {
          ...line,
          ...(index === 0 && beginArrowType ? { beginArrowType } : {}),
          ...(index === points.length - 2 && endArrowType ? { endArrowType } : {}),
        },
      },
      role: source.role ?? "line-segment",
      zIndex: 1,
      allowOverlap: true,
    };
  });
}

function plainRichText(value) {
  return String(value ?? "")
    .replace(/<br\s*\/?>/giu, "\n")
    .replace(/<[^>]+>/gu, "")
    .replace(/&nbsp;/giu, " ")
    .replace(/&amp;/giu, "&")
    .trim();
}

function isFormulaText(value) {
  const text = plainRichText(value);
  return /^\\\([\s\S]+\\\)$/u.test(text) || /^\$\$[\s\S]+\$\$$/u.test(text) || /^\$[^$]+\$$/u.test(text);
}

function resourcePath(source, projectDir, warnings, context, remoteAssets = null) {
  if (typeof source !== "string") return null;
  if (source.startsWith("data:")) return source;
  if (/^https?:\/\//iu.test(source)) {
    const prefetched = remoteAssets instanceof Map ? remoteAssets.get(source) : remoteAssets?.[source];
    if (prefetched) return prefetched;
    warnings.push({ code: "remote-asset-not-fetched", context, source });
    return null;
  }
  const root = path.resolve(projectDir);
  const resolved = path.resolve(root, source);
  if (resolved !== root && !resolved.startsWith(`${root}${path.sep}`)) {
    warnings.push({ code: "asset-path-outside-project", context, source });
    return null;
  }
  return resolved;
}

function cellStyleFor(cell, tableStyle, row, column, rows, columns, theme, scale, warnings, context) {
  const source = record(cell);
  const bodyStyles = Array.isArray(tableStyle.bodyStyles) ? tableStyle.bodyStyles : [];
  const rowStyle = row === 0 ? record(tableStyle.firstRowStyle)
    : row === rows - 1 ? record(tableStyle.lastRowStyle)
      : record(bodyStyles.length ? bodyStyles[(row - 1) % bodyStyles.length] : {});
  const columnStyle = column === 0 ? record(tableStyle.firstColumnStyle)
    : column === columns - 1 ? record(tableStyle.lastColumnStyle) : {};
  const merged = tableStyle.rowOverColumn === false
    ? { ...tableStyle, ...record(tableStyle.cellStyle), ...columnStyle, ...rowStyle, ...source }
    : { ...tableStyle, ...record(tableStyle.cellStyle), ...rowStyle, ...columnStyle, ...source };
  const textStyle = normalizeTextStyle({
    ...resolveStyle(merged.textStyle, theme, "textStyles"),
    ...merged,
    align: merged.align,
  }, theme, scale, warnings, context);
  return {
    ...textStyle,
    fill: convertFill(merged.fill ?? merged.backgroundColor, theme, warnings, context),
    borderColor: resolveColor(record(merged.border).color, theme.colors, "#D3CEC3"),
    ...(merged.colSpan ? { colSpan: number(merged.colSpan, 1) } : {}),
    ...(merged.rowSpan ? { rowSpan: number(merged.rowSpan, 1) } : {}),
  };
}

function chartRows(chart) {
  const data = record(chart.data);
  const cols = Array.isArray(data.cols) ? data.cols.map(String) : [];
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const index = new Map(cols.map((key, position) => [key, position]));
  const get = (row, key) => row?.[index.get(String(key)) ?? -1];
  return { cols, rows, get };
}

function chartSeries(chart, theme, warnings, context) {
  const { cols, rows, get } = chartRows(chart);
  const sourceSeries = Array.isArray(chart.series) ? chart.series : [];
  if (!sourceSeries.length) return null;
  const types = sourceSeries.map((series) => String(series?.type ?? "bar").toLowerCase());
  const unsupported = types.find((type) => !SUPPORTED_CHARTS.has(type));
  if (unsupported) {
    warnings.push({ code: "unsupported-chart-type", context, chartType: unsupported });
    return null;
  }
  const primary = types[0] === "doughnut" ? "donut" : types[0];
  if (types.some((type) => (type === "doughnut" ? "donut" : type) !== primary)) warnings.push({ code: "mixed-chart-flattened", context, chartTypes: types });
  const mergedSeries = sourceSeries.map((series) => ({ ...record(chart.seriesDefaults?.[series?.type]), ...record(series) }));
  const categoriesFor = (series) => {
    const encode = record(series.encode);
    const key = encode.category ?? encode.x ?? cols[0];
    return rows.map((row) => get(row, key));
  };
  const converted = mergedSeries.map((series) => {
    const encode = record(series.encode);
    const type = String(series.type ?? primary).toLowerCase();
    const categoryKey = encode.category ?? encode.x ?? cols[0];
    const valueKey = encode.value ?? encode.y ?? cols[1];
    const values = rows.map((row) => number(get(row, valueKey), 0));
    const colorValue = type === "line" || type === "radar" || type === "area" ? series.lineColor : series.fill;
    const item = {
      name: String(series.name ?? valueKey),
      values,
      color: resolveColor(Array.isArray(colorValue) ? colorValue[0] : colorValue, theme.colors, "#B32635"),
    };
    if (primary === "scatter") item.xValues = rows.map((row) => number(get(row, encode.x ?? cols[0]), 0));
    if (primary === "pie" || primary === "donut") item.colors = (Array.isArray(series.fill) ? series.fill : []).map((color) => resolveColor(color, theme.colors));
    if (primary === "radar") item.values = rows.map((row) => number(get(row, encode.y ?? valueKey), 0));
    return item;
  });
  const first = mergedSeries[0];
  const categories = primary === "pie" || primary === "donut" || primary === "radar"
    ? categoriesFor(first)
    : primary === "scatter" ? rows.map((row) => get(row, record(first.encode).x ?? cols[0])) : categoriesFor(first);
  const style = {
    title: typeof chart.title === "string" ? chart.title : chart.title?.text,
    legend: chart.legend === false || chart.legend?.show === false ? false : Boolean(chart.legend),
    legendPosition: typeof chart.legend === "object" ? chart.legend.position : undefined,
    dataLabels: chart.dataLabels,
    showValue: Boolean(chart.dataLabels?.show && chart.dataLabels?.content === "value"),
    showCatName: Boolean(chart.dataLabels?.show && chart.dataLabels?.content === "category"),
    showPercent: Boolean(chart.dataLabels?.show && chart.dataLabels?.content === "percentage"),
    colors: converted[0]?.colors,
  };
  return { chartType: primary, series: converted, categories, xValues: primary === "scatter" ? converted[0]?.xValues : undefined, style };
}

function makeTableRows(element, manifest, theme, scale, warnings, context) {
  const tableStyle = resolveStyle(element.style, manifest.theme ?? {}, "tableStyles");
  const rows = Array.isArray(element.rows) ? element.rows : [[]];
  const columnCount = Math.max(1, ...rows.map((row) => Array.isArray(row) ? row.reduce((count, cell) => count + Math.max(1, number(record(cell).colSpan ?? record(cell).colspan, 1)), 0) : 0));
  return rows.map((row, rowIndex) => (Array.isArray(row) ? row : []).map((cell, columnIndex) => {
    const source = typeof cell === "object" ? record(cell) : { text: cell };
    const content = record(source.content);
    const normalized = { ...source, ...content };
    if (normalized.color === undefined) normalized.color = columnIndex === 0 && tableStyle.firstColumnColor !== undefined ? tableStyle.firstColumnColor : tableStyle.bodyColor;
    if (normalized.bold === undefined && rowIndex === 0 && tableStyle.headerBold !== undefined) normalized.bold = Boolean(tableStyle.headerBold);
    if (normalized.border === undefined && tableStyle.border !== undefined) normalized.border = tableStyle.border;
    const style = cellStyleFor(normalized, tableStyle, rowIndex, columnIndex, rows.length, columnCount, theme, scale, warnings, context);
    const textValue = normalized.text ?? "";
    const parsed = richText(textValue, style, theme.colors, scale);
    return {
      text: plainRichText(textValue),
      runs: parsed.runs,
      colSpan: normalized.colSpan ?? normalized.colspan,
      rowSpan: normalized.rowSpan ?? normalized.rowspan,
      style,
      fill: style.fill,
    };
  }));
}

function addPptdElement(slide, element, context, state) {
  const source = record(element);
  const bounds = scaleBounds(source.bounds, state.scale);
  const id = String(source.elementId ?? `${context}-${state.index}`);
  const type = String(source.elementType ?? "shape").toLowerCase();
  const theme = state.theme;
  const warnings = state.warnings;
  const colors = theme.colors ?? {};
  if (type === "text") {
    const content = record(source.content);
    const style = normalizeTextStyle(content, theme, state.scale, warnings, context);
    const textValue = content.text ?? "";
    const parsed = richText(textValue, style, colors, state.scale);
    if (parsed.paragraphAlign && !content.align) style.align = parsed.paragraphAlign;
    if (isFormulaText(textValue)) {
      const formula = plainRichText(textValue);
      const item = addFormula(slide, formula, bounds, { name: id, style, role: "formula" });
      item.rawPptd = source;
      state.index += 1;
      return item;
    }
    const item = addElement(slide, {
      id,
      name: id,
      type: "text",
      position: bounds,
      text: plainRichText(textValue),
      runs: parsed.runs,
      style,
      singleLine: content.wrap === false,
      allowOverflow: content.wrap === false,
      role: source.role ?? "body",
      ...(content.textDirection === "vertical" ? { rawPptd: source, textDirection: "vertical" } : {}),
      rawPptd: source,
    });
    if (textValue.includes("\\(") || textValue.includes("$$")) warnings.push({ code: "inline-latex-text-fallback", context });
    state.index += 1;
    return item;
  }
  if (type === "shape") {
    const geometry = normalizeGeometry(source.shapeName ?? "rect");
    if (!isPresetGeometry(source.shapeName ?? "rect")) warnings.push({ code: "shape-fallback", context, shapeName: source.shapeName });
    const opacity = number(source.opacity, 1);
    const style = {
      fill: convertFill(source.fill, theme, warnings, context, opacity),
      line: convertBorder(source.border, theme, warnings, context),
      shadow: convertShadow(source.shadow, theme),
    };
    const item = addShape(slide, geometry, bounds, style, { name: id, role: source.role ?? "shape" });
    Object.assign(item, transform(source), { rawPptd: source });
    state.index += 1;
    return item;
  }
  if (type === "line") {
    const border = convertBorder(source.border, theme, warnings, context);
    const points = linePoints(source.points);
    if (points.length < 2) warnings.push({ code: "line-points-fallback", context });
    const lineStyle = { fill: "none", line: { ...border }, shadow: convertShadow(source.shadow, theme) };
    const pointBounds = lineBounds(points, state.scale, bounds);
    const item = points.length > 2
      ? addGroup(slide, lineSegments(points, state.scale, bounds, border, source, id), bounds, { name: id, role: source.role ?? "line", allowOverlap: true })
      : addShape(slide, "line", pointBounds, lineStyle, { name: id, role: source.role ?? "line" });
    if (points.length === 2) {
      const dx = (points[1][0] - points[0][0]) * state.scale;
      const dy = (points[1][1] - points[0][1]) * state.scale;
      Object.assign(item, dx < 0 ? { flipH: true } : {}, dy < 0 ? { flipV: true } : {});
      const beginArrowType = source.beginArrowType ?? source.headEnd ?? source.lineHead ?? border.beginArrowType ?? border.headEnd;
      const endArrowType = source.endArrowType ?? source.tailEnd ?? source.lineTail ?? border.endArrowType ?? border.tailEnd;
      if (beginArrowType || endArrowType) item.style.line = { ...item.style.line, ...(beginArrowType ? { beginArrowType } : {}), ...(endArrowType ? { endArrowType } : {}) };
    }
    Object.assign(item, transform(source), { rawPptd: source });
    state.index += 1;
    return item;
  }
  if (type === "image") {
    const resolved = resourcePath(source.src, state.projectDir, warnings, context, state.remoteAssets);
    if (!resolved) {
      warnings.push({ code: "image-placeholder", context });
      const item = addShape(slide, "rect", bounds, { fill: "#00000000", line: { color: "#00000000", width: 0 } }, { name: id, role: "unsupported" });
      item.rawPptd = source;
      state.index += 1;
      return item;
    }
    const fit = record(source.fit).mode ?? "cover";
    if (source.cropShape) warnings.push({ code: "image-crop-shape-fallback", context });
    const item = addImage(slide, resolved, bounds, { name: id, fit, crop: source.crop, opacity: number(source.opacity, 1), alt: source.alt ?? id, ...transform(source) });
    if (source.focalPoint) item.focalPoint = structuredClone(source.focalPoint);
    item.rawPptd = source;
    state.index += 1;
    return item;
  }
  if (type === "icon") {
    warnings.push({ code: "icon-font-fallback", context, iconName: source.iconName });
    const icon = ICON_FALLBACKS[String(source.iconName ?? "").toLowerCase()] ?? "•";
    const style = normalizeTextStyle({ fontSize: number(source.bounds?.[2], 24) * 0.75, color: source.fill?.color ?? "#1E1E1E", align: ["center", "middle"] }, theme, state.scale, warnings, context);
    const item = addText(slide, icon, bounds, style, { name: id, role: "icon", singleLine: true });
    Object.assign(item, transform(source), { rawPptd: source });
    state.index += 1;
    return item;
  }
  if (type === "table") {
    const tableRows = makeTableRows(source, state.manifest, theme, state.scale, warnings, context);
    const tableStyle = resolveStyle(source.style, state.manifest.theme ?? {}, "tableStyles");
    const baseStyle = cellStyleFor({}, tableStyle, 0, 0, tableRows.length, tableRows[0]?.length ?? 1, theme, state.scale, warnings, context);
    const columnWidths = Array.isArray(source.columnWidths)
      ? source.columnWidths.map((value) => number(value, 0)).filter((value) => value > 0)
      : undefined;
    const rowHeights = Array.isArray(source.rowHeights)
      ? source.rowHeights.map((value) => number(value, 0)).filter((value) => value > 0)
      : undefined;
    const item = addTable(slide, tableRows, bounds, {
      name: id,
      header: source.header !== false,
      ...(columnWidths?.length ? { columnWidths } : {}),
      ...(rowHeights?.length ? { rowHeights } : {}),
      ...(source.banded !== undefined ? { banded: Boolean(source.banded) } : {}),
      style: baseStyle,
      role: source.role ?? "table",
    });
    item.rawPptd = source;
    state.index += 1;
    return item;
  }
  if (type === "chart") {
    const chart = chartSeries(source, theme, warnings, context);
    if (!chart) {
      const item = addShape(slide, "rect", bounds, { fill: "#00000000", line: { color: "#00000000", width: 0 } }, { name: id, role: "unsupported" });
      item.rawPptd = source;
      state.index += 1;
      return item;
    }
    const item = addChart(slide, chart.chartType, chart.series, bounds, { name: id, categories: chart.categories, xValues: chart.xValues, ...chart.style, role: source.role ?? "chart" });
    item.rawPptd = source;
    state.index += 1;
    return item;
  }
  warnings.push({ code: "unsupported-element-type", context, elementType: type });
  const item = addShape(slide, "rect", bounds, { fill: "#00000000", line: { color: "#00000000", width: 0 } }, { name: id, role: "unsupported" });
  item.rawPptd = source;
  state.index += 1;
  return item;
}

function normalizeProjectData(project) {
  const source = record(project);
  const manifest = record(source.manifest ?? source.deck ?? source.presentation);
  const pages = Array.isArray(source.pages) ? source.pages : [];
  if (manifest.version && manifest.version !== "v2") throw new Error(`Unsupported PPTD version: ${manifest.version}`);
  if (!Array.isArray(manifest.pages) && pages.length === 0) throw new Error("PPTD manifest must contain pages");
  return { manifest, pages, projectDir: source.projectDir ?? process.cwd(), manifestPath: source.manifestPath ?? null };
}

const REMOTE_URL_PATTERN = /^https?:\/\//iu;

function remoteImageUrlsInPage(page) {
  const urls = [];
  const background = record(page.background);
  if (background.type === "image" && REMOTE_URL_PATTERN.test(String(background.src ?? ""))) urls.push(String(background.src));
  for (const element of Array.isArray(page.elements) ? page.elements : []) {
    const src = record(element).src;
    if (typeof src === "string" && REMOTE_URL_PATTERN.test(src)) urls.push(src);
  }
  return urls;
}

/** Collect the unique remote (http/https) image URLs referenced by a PPTD project. */
export function collectPptdRemoteAssetUrls(project) {
  const source = normalizeProjectData(project);
  const pageValues = source.pages.length ? source.pages : source.manifest.pages.map((entry) => ({ path: entry, content: {} }));
  const urls = new Set();
  for (const pageEntry of pageValues) {
    const page = record(pageEntry.content ?? pageEntry.page ?? pageEntry);
    for (const url of remoteImageUrlsInPage(page)) urls.add(url);
  }
  return [...urls];
}

async function findCachedAsset(cacheDir, hash) {
  try {
    const entry = (await fs.readdir(cacheDir)).find((name) => name.startsWith(`${hash}.`));
    return entry ? path.join(cacheDir, entry) : null;
  } catch {
    return null;
  }
}

/**
 * Download every remote image referenced by a PPTD project into a local cache
 * directory (default `<projectDir>/media/remote`). Returns a Map of URL to
 * absolute local path suitable for `pptdToDeck({ remoteAssets })`. Downloads
 * are content-sniffed (extensions and content-type headers are not trusted);
 * webp is transcoded to png so the resulting PPTX opens in older PowerPoint.
 * Failures are reported per URL and never abort the batch.
 */
export async function prefetchPptdRemoteAssets(project, options = {}) {
  const source = normalizeProjectData(project);
  const cacheDir = path.resolve(options.cacheDir ?? path.join(source.projectDir, "media", "remote"));
  const fetchImpl = options.fetchImpl ?? globalThis.fetch;
  const concurrency = Math.max(1, number(options.concurrency, 4));
  const timeoutMs = Math.max(1000, number(options.timeoutMs, 20000));
  const maxBytes = Math.max(1024, number(options.maxBytes, 25 * 1024 * 1024));
  const refresh = Boolean(options.refresh);
  const urls = collectPptdRemoteAssetUrls(project);
  const assets = new Map();
  const failures = [];
  let fetched = 0;
  let reused = 0;
  if (!urls.length) return { assets, fetched, reused, failures, cacheDir };
  if (typeof fetchImpl !== "function") {
    for (const url of urls) failures.push({ url, error: "no fetch implementation available" });
    return { assets, fetched, reused, failures, cacheDir };
  }
  await fs.mkdir(cacheDir, { recursive: true });
  const worker = async (url) => {
    const hash = crypto.createHash("sha1").update(url).digest("hex").slice(0, 16);
    if (!refresh) {
      const cached = await findCachedAsset(cacheDir, hash);
      if (cached) {
        assets.set(url, cached);
        reused += 1;
        return;
      }
    }
    try {
      const response = await fetchImpl(url, { signal: AbortSignal.timeout(timeoutMs), redirect: "follow" });
      if (!response?.ok) throw new Error(`HTTP ${response?.status ?? "request failed"}`);
      const declared = Number(response.headers?.get?.("content-length") ?? 0);
      if (declared > maxBytes) throw new Error(`asset too large: ${declared} bytes`);
      const buffer = Buffer.from(await response.arrayBuffer());
      if (buffer.length === 0) throw new Error("empty response body");
      if (buffer.length > maxBytes) throw new Error(`asset too large: ${buffer.length} bytes`);
      const type = sniffImageType(buffer) ?? imageTypeFromContentType(response.headers?.get?.("content-type")) ?? imageTypeFromUrl(url);
      if (!type) throw new Error("unrecognized image type");
      let data = buffer;
      let extension = type.extension;
      if (type.mimeType === "image/webp") {
        // Static webp transcodes losslessly enough to png and keeps the PPTX
        // readable by PowerPoint versions without webp support.
        data = await sharp(buffer).png().toBuffer();
        extension = "png";
      }
      const target = path.join(cacheDir, `${hash}.${extension}`);
      await fs.writeFile(target, data);
      assets.set(url, target);
      fetched += 1;
    } catch (error) {
      failures.push({ url, error: String(error?.message ?? error) });
    }
  };
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(concurrency, urls.length) }, async () => {
    while (next < urls.length) {
      const url = urls[next];
      next += 1;
      await worker(url);
    }
  }));
  return { assets, fetched, reused, failures, cacheDir };
}

/** Compile a parsed PPTD v2 object into the common presentation IR. */
export function pptdToDeck(project, options = {}) {
  const source = normalizeProjectData(project);
  const manifest = source.manifest;
  const pptdSize = Array.isArray(manifest.size) ? { width: number(manifest.size[0], DEFAULT_PPTD_SIZE.width), height: number(manifest.size[1], DEFAULT_PPTD_SIZE.height) } : DEFAULT_PPTD_SIZE;
  const scale = number(options.scale, ENGINE_CANVAS.width / pptdSize.width);
  const slideSize = options.slideSize ?? { width: pptdSize.width * scale, height: pptdSize.height * scale };
  const themeSource = manifest.theme ?? {};
  const themeColors = { ...(themeSource.colors ?? {}) };
  const openFont = options.fontProfile === "open-source" ? "Noto Sans SC" : null;
  const theme = {
    colors: { ...themeColors },
    fonts: {
      heading: options.headingFont ?? openFont ?? "Aptos Display",
      body: options.bodyFont ?? openFont ?? "Aptos",
      cjk: options.cjkFont ?? openFont ?? "Microsoft YaHei",
    },
    textStyles: { ...(themeSource.textStyles ?? {}) },
    tableStyles: { ...(themeSource.tableStyles ?? {}) },
  };
  const warnings = [];
  const deck = createDeck({
    title: manifest.title ?? options.title ?? "Imported PPTD deck",
    slideSize,
    theme,
    fontProfile: options.fontProfile ?? null,
    metadata: { source: "pptd-v2", manifestPath: source.manifestPath },
  });
  const state = { manifest, theme: deck.theme, scale, projectDir: source.projectDir, warnings, index: 0, remoteAssets: options.remoteAssets ?? null };
  const defaultTransition = options.transition === false ? null : options.transition ?? { type: "fade", speed: "fast", advanceOnClick: true };
  const pageValues = source.pages.length ? source.pages : manifest.pages.map((entry) => ({ path: entry, content: {} }));
  pageValues.forEach((pageEntry, pageIndex) => {
    const page = record(pageEntry.content ?? pageEntry.page ?? pageEntry);
    const pagePath = pageEntry.path ?? manifest.pages?.[pageIndex] ?? `pages/${pageIndex + 1}.page`;
    const background = page.background;
    const pageBackground = background?.type === "image" ? null : convertFill(background ?? "#FFFFFF", deck.theme, warnings, `${pagePath}:background`);
    const slide = addSlide(deck, {
      id: `pptd-slide-${pageIndex + 1}`,
      name: pagePath,
      semanticType: page.pageType ?? "imported",
      notes: page.notes ?? "",
      sources: Array.isArray(page.sources) ? page.sources : [],
      background: pageBackground,
      transition: defaultTransition,
    });
    if (background?.type === "image") {
      const sourcePath = resourcePath(background.src, source.projectDir, warnings, `${pagePath}:background-image`, state.remoteAssets);
      slide.backgroundConfig = structuredClone({
        fit: typeof background.fit === "string" ? background.fit : background.fit?.mode ?? "cover",
        focalPoint: background.focalPoint ?? null,
        opacity: number(background.opacity, 1),
        brightness: number(background.brightness, 1),
        blur: number(background.blur, 0),
        safeZone: background.safeZone ?? null,
      });
      if (sourcePath) {
        const backgroundImage = addImage(slide, sourcePath, { left: 0, top: 0, width: slideSize.width, height: slideSize.height }, {
          name: "page-background-image",
          fit: typeof background.fit === "string" ? background.fit : background.fit?.mode ?? "cover",
          opacity: number(background.opacity, 1),
          role: "background",
          allowOverlap: true,
        });
        if (background.focalPoint) backgroundImage.focalPoint = structuredClone(background.focalPoint);
        backgroundImage.rawPptd = background;
        const brightness = number(background.brightness, 1);
        if (brightness !== 1) {
          const shadeOpacity = Math.min(0.55, Math.abs(1 - brightness));
          const shadeColor = brightness < 1 ? "#000000" : "#FFFFFF";
          addShape(slide, "rect", { left: 0, top: 0, width: slideSize.width, height: slideSize.height }, { fill: colorWithOpacity(shadeColor, shadeOpacity, deck.theme.colors, shadeColor), line: { color: "#00000000", width: 0 } }, { name: "page-background-brightness", role: "background-overlay", allowOverlap: true });
        }
        const overlay = backgroundOverlayFill(background.overlay ?? background.tint, deck.theme, warnings, `${pagePath}:background-overlay`);
        if (overlay) addShape(slide, "rect", { left: 0, top: 0, width: slideSize.width, height: slideSize.height }, { fill: overlay, line: { color: "#00000000", width: 0 } }, { name: "page-background-overlay", role: "background-overlay", allowOverlap: true });
        if (number(background.blur, 0) > 0) warnings.push({ code: "background-blur-advisory", context: `${pagePath}:background`, blur: number(background.blur, 0) });
      }
    }
    const elements = Array.isArray(page.elements) ? page.elements : [];
    elements.forEach((element) => addPptdElement(slide, element, `${pagePath}:${element.elementId ?? state.index}`, state));
  });
  deck.metadata.pptdBridge = {
    version: manifest.version ?? "v2",
    scale,
    sourceSize: pptdSize,
    warnings,
    unsupportedCount: warnings.length,
  };
  return deck;
}

function safeRelativePath(value) {
  const normalized = String(value ?? "").replaceAll("\\", "/");
  if (!normalized || normalized.startsWith("/") || normalized.includes("..")) throw new Error(`Invalid PPTD project path: ${value}`);
  return normalized;
}

/** Read a self-contained PPTD directory or a single .pptd manifest. */
export async function readPptdProject(input) {
  const requested = path.resolve(String(input));
  const stat = await fs.stat(requested);
  const projectDir = stat.isDirectory() ? requested : path.dirname(requested);
  let manifestPath = stat.isDirectory() ? null : requested;
  if (!manifestPath) {
    const entries = (await fs.readdir(projectDir)).filter((entry) => entry.toLowerCase().endsWith(".pptd"));
    if (entries.length !== 1) throw new Error(`Expected exactly one .pptd manifest in ${projectDir}, found ${entries.length}`);
    manifestPath = path.join(projectDir, entries[0]);
  }
  const manifestText = await fs.readFile(manifestPath, "utf8");
  const manifest = YAML.parse(manifestText) ?? {};
  const pages = [];
  for (const entry of manifest.pages ?? []) {
    const relative = safeRelativePath(entry);
    const pagePath = path.join(projectDir, relative);
    pages.push({ path: relative, content: YAML.parse(await fs.readFile(pagePath, "utf8")) ?? {} });
  }
  return { manifest, pages, projectDir, manifestPath };
}

/** Convert a PPTD project directly to a self-controlled editable PPTX. */
export async function exportPptdProject(input, outputPath, options = {}) {
  const project = typeof input === "object" && input.manifest ? input : await readPptdProject(input);
  // Remote (http/https) images are prefetched into a local cache so the export
  // embeds real bytes instead of dropping them as transparent placeholders.
  // Set `prefetchRemote: false` to keep the old offline behavior; per-URL
  // failures degrade gracefully to the previous `remote-asset-not-fetched`
  // warning path. Entries in `options.remoteAssets` win over prefetched ones.
  let remoteAssets = options.remoteAssets ?? null;
  let prefetch = null;
  if (options.prefetchRemote !== false && collectPptdRemoteAssetUrls(project).length > 0) {
    prefetch = await prefetchPptdRemoteAssets(project, {
      cacheDir: options.remoteCacheDir,
      fetchImpl: options.fetchImpl,
      concurrency: options.concurrency,
      timeoutMs: options.timeoutMs,
      maxBytes: options.maxBytes,
      refresh: options.refreshRemote,
    });
    const merged = new Map(prefetch.assets);
    const explicit = remoteAssets instanceof Map ? remoteAssets.entries() : Object.entries(remoteAssets ?? {});
    for (const [url, localPath] of explicit) merged.set(url, localPath);
    remoteAssets = merged;
  }
  const deck = pptdToDeck(project, { ...options, remoteAssets });
  await exportOoxmlBasic(deck, outputPath, {
    embedFonts: Boolean(options.embedFonts),
    fontAssets: options.fontAssets ?? deck.fontAssets,
    assetResolver: options.assetResolver,
    svgFallback: options.svgFallback ?? true,
  });
  const report = deck.metadata.pptdBridge;
  if (prefetch) {
    report.prefetch = {
      total: prefetch.assets.size + prefetch.failures.length,
      fetched: prefetch.fetched,
      reused: prefetch.reused,
      failures: prefetch.failures,
      cacheDir: prefetch.cacheDir,
    };
  }
  return { deck, outputPath, report };
}
