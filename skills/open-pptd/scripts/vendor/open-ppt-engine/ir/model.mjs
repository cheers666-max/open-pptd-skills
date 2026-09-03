import { openSourceTheme, resolveTheme } from "../design/theme.mjs";
import { normalizeTextStyles } from "./text-styles.mjs";
import { normalizeGeometry } from "./geometries.mjs";
import { assetUri } from "../assets/refs.mjs";
import { normalizeTransition } from "./transitions.mjs";
import { normalizeFormula } from "./formulas.mjs";
import { normalizeSmartArt } from "./smartart.mjs";
import { compileDiagram } from "../layout/diagrams.mjs";

export const CANVAS = Object.freeze({ width: 1280, height: 720 });
const DEFAULT_LAYOUT = Object.freeze({ id: "layout-blank", name: "Blank", type: "blank", background: null, placeholders: [] });

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
}

function nextAvailableId(values, prefix) {
  const existing = new Set(values.filter(Boolean).map(String));
  const pattern = new RegExp(`^${escapeRegExp(prefix)}-(\\d+)$`, "u");
  let candidate = 1;
  for (const value of existing) {
    const match = value.match(pattern);
    if (match) candidate = Math.max(candidate, Number(match[1]) + 1);
  }
  let id = `${prefix}-${String(candidate).padStart(4, "0")}`;
  while (existing.has(id)) id = `${prefix}-${String(++candidate).padStart(4, "0")}`;
  return id;
}

function sourceLine(source) {
  if (typeof source === "string") return `- ${source}`;
  const value = source && typeof source === "object" ? source : {};
  const url = value.url ?? value.uri ?? null;
  const locator = value.locator ?? value.page ?? null;
  const label = value.title ?? value.name ?? url ?? "source";
  return `- ${label}${url && label !== url ? ` (${url})` : ""}${locator ? ` [${locator}]` : ""}`;
}

export function sourceNotesBlock(sources = []) {
  if (!Array.isArray(sources) || sources.length === 0) return "";
  return `[Sources]\n${sources.map(sourceLine).join("\n")}`;
}

function appendSourceNotes(notes, sources) {
  const block = sourceNotesBlock(sources);
  if (!block) return String(notes ?? "");
  const current = String(notes ?? "").trim();
  if (/^\[Sources\]\s*$/mu.test(current)) {
    const additions = block.split("\n").slice(1).filter((line) => !current.split("\n").includes(line));
    return additions.length ? `${current}\n${additions.join("\n")}` : current;
  }
  return [current, block].filter(Boolean).join("\n\n");
}

function nestedElementIds(elements = [], output = []) {
  for (const element of elements) {
    if (element?.id) output.push(element.id);
    if (element?.type === "group") nestedElementIds(element.children ?? [], output);
  }
  return output;
}

export function createDeck({
  title = "Untitled deck",
  slideSize = CANVAS,
  theme = {},
  textStyles = {},
  fontProfile = null,
  metadata = {},
  master = {},
  layouts = [],
  fontAssets = [],
  tableStyles = [],
} = {}) {
  const normalizedLayouts = layouts.length > 0 ? structuredClone(layouts) : [structuredClone(DEFAULT_LAYOUT)];
  return {
    schemaVersion: "0.1",
    title,
    slideSize: { ...CANVAS, ...slideSize },
    theme: resolveTheme(fontProfile === "open-source" ? { ...openSourceTheme, ...theme } : theme),
    textStyles: normalizeTextStyles(textStyles),
    metadata,
    master: { id: "master-default", name: "Open PPT", background: null, ...structuredClone(master) },
    layouts: normalizedLayouts,
    fontAssets: structuredClone(fontAssets),
    tableStyles: structuredClone(Array.isArray(tableStyles) ? tableStyles : []),
    assets: [],
    slides: [],
  };
}

export function addSlide(deck, {
  id: slideId,
  name = `Slide ${deck.slides.length + 1}`,
  background = null,
  semanticType = "freeform",
  notes = "",
  sources = [],
  transition = null,
  timing = null,
  layoutId = null,
  layoutVariant = null,
  sectionId = null,
  sectionName = null,
  pageRole = null,
  sectionNumber = null,
  hidden = false,
  elements = [],
} = {}) {
  const resolvedSlideId = slideId ?? nextAvailableId(deck.slides.map((slide) => slide.id), "slide");
  const normalizedSources = Array.isArray(sources) ? structuredClone(sources) : [];
  const slide = {
    id: resolvedSlideId,
    name,
    semanticType,
    background,
    notes: appendSourceNotes(notes, normalizedSources),
    sources: normalizedSources,
    ...(transition ? { transition: normalizeTransition(transition) } : {}),
    ...(timing ? { timing: structuredClone(timing) } : {}),
    layoutId: layoutId ?? deck.layouts?.[0]?.id ?? null,
    ...(layoutVariant ? { layoutVariant: String(layoutVariant) } : {}),
    ...(sectionId ? { sectionId: String(sectionId) } : {}),
    ...(sectionName ? { sectionName: String(sectionName) } : {}),
    ...(pageRole ? { pageRole: String(pageRole) } : {}),
    ...(sectionNumber !== null && sectionNumber !== undefined ? { sectionNumber: String(sectionNumber) } : {}),
    ...(hidden ? { hidden: true } : {}),
    elements: [],
  };
  deck.slides.push(slide);
  for (const element of elements) addElement(slide, element);
  return slide;
}

export function addElement(slide, element) {
  const sourcePosition = element.position;
  const hasPosition = sourcePosition !== undefined && sourcePosition !== null;
  const resolvedId = element.id ?? nextAvailableId(nestedElementIds(slide.elements), element.type ?? "element");
  const normalized = {
    id: resolvedId,
    type: element.type ?? "shape",
    name: element.name ?? element.id ?? "element",
    position: {
      left: 0,
      top: 0,
      width: 0,
      height: 0,
      ...(sourcePosition ?? {}),
    },
    positionMode: element.positionMode ?? (hasPosition ? "explicit" : "auto"),
    zIndex: element.zIndex ?? slide.elements.length,
    allowOverlap: Boolean(element.allowOverlap),
    ...element,
  };
  normalized.position = {
    left: 0,
    top: 0,
    width: 0,
    height: 0,
    ...(sourcePosition ?? {}),
  };
  slide.elements.push(normalized);
  return normalized;
}

export function addText(slide, text, position, style = {}, options = {}) {
  return addElement(slide, {
    type: "text",
    name: options.name ?? "text",
    position,
    positionMode: options.positionMode ?? (position ? "explicit" : "placeholder"),
    ...(options.placeholder ? { placeholder: options.placeholder } : {}),
    text,
    style: options.inheritStyle
      ? { ...style }
      : {
        fontFamily: "Aptos",
        fontSize: 16,
        color: "#1E1E1E",
        bold: false,
        align: "left",
        valign: "top",
        lineHeight: 1.15,
        ...style,
      },
    singleLine: Boolean(options.singleLine),
    allowWrap: Boolean(options.allowWrap),
    allowOverflow: Boolean(options.allowOverflow),
    autoFit: Boolean(options.autoFit),
    ...(options.bullet !== undefined ? { bullet: options.bullet } : {}),
    ...(options.bulletChar !== undefined ? { bulletChar: String(options.bulletChar) } : {}),
    ...(options.bulletLevel !== undefined ? { bulletLevel: Number(options.bulletLevel) } : {}),
    role: options.role ?? "body",
    allowOverlap: options.allowOverlap,
    hidden: options.hidden,
  });
}

export function addShape(slide, geometry, position, style = {}, options = {}) {
  return addElement(slide, {
    type: "shape",
    name: options.name ?? geometry,
    geometry: normalizeGeometry(geometry),
    position,
    positionMode: options.positionMode ?? (position ? "explicit" : "placeholder"),
    ...(options.placeholder ? { placeholder: options.placeholder } : {}),
    style: {
      fill: "none",
      line: { color: "#00000000", width: 0 },
      radius: 16,
      ...style,
    },
    role: options.role ?? "shape",
    allowOverlap: options.allowOverlap,
    hidden: options.hidden,
  });
}

export function addImage(slide, source, position, options = {}) {
  const resolvedSource = options.assetId ? assetUri(options.assetId) : source;
  if (/^https?:\/\//iu.test(String(resolvedSource ?? ""))) {
    const sources = Array.isArray(slide.sources) ? slide.sources : [];
    if (!sources.some((item) => (typeof item === "string" ? item : item?.url ?? item?.uri) === resolvedSource)) {
      const nextSources = [...sources, { title: options.name ?? "External image", url: resolvedSource }];
      slide.sources = nextSources;
      slide.notes = appendSourceNotes(slide.notes, nextSources);
    }
  }
  return addElement(slide, {
    type: "image",
    name: options.name ?? "image",
    position,
    source: resolvedSource,
    ...(options.assetId ? { assetId: String(options.assetId) } : {}),
    fit: options.fit ?? "cover",
    alt: options.alt ?? "",
    rotation: Number(options.rotation ?? 0),
    opacity: options.opacity === undefined ? 1 : Number(options.opacity),
    flipH: Boolean(options.flipH),
    flipV: Boolean(options.flipV),
    ...(options.crop ? { crop: structuredClone(options.crop) } : {}),
    role: options.role ?? "image",
    allowOverlap: options.allowOverlap,
    hidden: options.hidden,
  });
}

export function addTable(slide, rows, position, options = {}) {
  return addElement(slide, {
    type: "table",
    name: options.name ?? "table",
    position,
    rows,
    header: options.header ?? true,
    ...(Array.isArray(options.columnWidths) ? { columnWidths: options.columnWidths.map((value) => Number(value)) } : {}),
    ...(Array.isArray(options.rowHeights) ? { rowHeights: options.rowHeights.map((value) => Number(value)) } : {}),
    ...(options.banded !== undefined ? { banded: Boolean(options.banded) } : {}),
    style: options.style ?? {},
    role: options.role ?? "table",
    allowOverlap: options.allowOverlap,
    hidden: options.hidden,
  });
}

export function addChart(slide, chartType, series, position, options = {}) {
  return addElement(slide, {
    type: "chart",
    name: options.name ?? "chart",
    position,
    chartType,
    categories: options.categories ?? [],
    ...(Array.isArray(options.xValues) ? { xValues: options.xValues } : {}),
    series,
    style: {
      ...(options.style ?? {}),
      ...(options.title !== undefined ? { title: options.title } : {}),
      ...(options.legend !== undefined ? { legend: options.legend } : {}),
      ...(options.dataLabels !== undefined ? { dataLabels: options.dataLabels } : {}),
      ...(options.showValue !== undefined ? { showValue: options.showValue } : {}),
      ...(options.showCatName !== undefined ? { showCatName: options.showCatName } : {}),
      ...(options.showPercent !== undefined ? { showPercent: options.showPercent } : {}),
      ...(options.xAxis !== undefined ? { xAxis: structuredClone(options.xAxis) } : {}),
      ...(options.yAxis !== undefined ? { yAxis: structuredClone(options.yAxis) } : {}),
    },
    role: options.role ?? "chart",
    allowOverlap: options.allowOverlap,
    hidden: options.hidden,
  });
}

/**
 * Add an editable Office Math equation. The OOXML backend emits OMML; other
 * renderers use the explicit fallback text while keeping the source latex.
 */
export function addFormula(slide, formula, position, options = {}) {
  const style = {
    fontFamily: "Cambria Math",
    fontSize: 24,
    color: "#1E1E1E",
    align: "center",
    valign: "middle",
    ...(options.style ?? {}),
  };
  const normalized = normalizeFormula(formula, style);
  return addElement(slide, {
    type: "formula",
    name: options.name ?? "formula",
    position,
    latex: normalized.latex,
    omml: normalized.omml,
    fallbackText: normalized.fallbackText,
    ...(normalized.unsupportedCommands?.length ? { unsupportedCommands: normalized.unsupportedCommands } : {}),
    style,
    role: options.role ?? "formula",
    allowOverlap: options.allowOverlap,
    hidden: options.hidden,
  });
}

/** Compile an editable diagram family into native shapes and lines. */
export function addDiagram(slide, spec, position, options = {}) {
  return addGroup(slide, compileDiagram(spec, position, options), position, {
    name: options.name ?? "diagram",
    role: options.role ?? "diagram",
    allowOverlap: options.allowOverlap,
    hidden: options.hidden,
  });
}

/**
 * Add an editable shape fallback with optional native PowerPoint SmartArt
 * package metadata. The fallback keeps HTML/PptxGenJS/LibreOffice deterministic;
 * the OOXML backend can emit the native diagram parts when requested.
 */
export function addSmartArt(slide, spec, position, options = {}) {
  const normalized = normalizeSmartArt(spec, options);
  const group = addGroup(slide, compileDiagram(normalized, position, options), position, {
    name: options.name ?? "smartArt",
    role: options.role ?? "smartArt",
    allowOverlap: options.allowOverlap,
    hidden: options.hidden,
  });
  group.smartArt = normalized;
  return group;
}

/**
 * Add a native IR group. Child positions are local to the group's position box.
 * Exporters may flatten the group, but the saved IR keeps the hierarchy.
 */
export function addGroup(slide, children, position, options = {}) {
  const reserved = new Set(nestedElementIds(slide.elements));
  const normalizeChild = (child, index) => {
    const normalized = structuredClone(child ?? {});
    normalized.id ??= nextAvailableId([...reserved], normalized.type ?? "element");
    reserved.add(normalized.id);
    normalized.name ??= normalized.id;
    normalized.position = { left: 0, top: 0, width: 0, height: 0, ...(normalized.position ?? {}) };
    normalized.zIndex ??= index;
    if (normalized.type === "group") normalized.children = (normalized.children ?? []).map(normalizeChild);
    return normalized;
  };
  return addElement(slide, {
    type: "group",
    name: options.name ?? "group",
    position,
    children: Array.isArray(children) ? children.map(normalizeChild) : [],
    role: options.role ?? "group",
    allowOverlap: options.allowOverlap,
    hidden: options.hidden,
  });
}

export function cloneDeck(deck) {
  return structuredClone(deck);
}
