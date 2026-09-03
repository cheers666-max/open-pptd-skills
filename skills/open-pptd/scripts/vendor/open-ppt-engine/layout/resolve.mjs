import { cloneDeck } from "../ir/model.mjs";
import { textStyleForRole } from "../ir/text-styles.mjs";

function isObject(value) {
  return value && typeof value === "object" && !Array.isArray(value);
}

function mergeValue(base, override) {
  if (!isObject(base) || !isObject(override)) return override === undefined ? base : structuredClone(override);
  const result = structuredClone(base);
  for (const [key, value] of Object.entries(override)) {
    result[key] = isObject(result[key]) && isObject(value) ? mergeValue(result[key], value) : structuredClone(value);
  }
  return result;
}

function normalizePosition(value) {
  return { left: 0, top: 0, width: 0, height: 0, ...(value ?? {}) };
}

function normalizePlaceholder(placeholder, index = 0) {
  const type = placeholder?.type ?? "body";
  const idx = Number.isFinite(Number(placeholder?.idx)) ? Number(placeholder.idx) : index;
  return {
    ...structuredClone(placeholder ?? {}),
    id: placeholder?.id ?? `${type}-${idx}`,
    type,
    idx,
    name: placeholder?.name ?? `${type}-${idx}`,
    position: normalizePosition(placeholder?.position),
    style: structuredClone(placeholder?.style ?? {}),
  };
}

function placeholderRef(element) {
  if (typeof element?.placeholder === "string") return { id: element.placeholder, type: element.placeholder, semantic: true };
  if (isObject(element?.placeholder)) return element.placeholder;
  if (element?.placeholderId || element?.placeholderType) {
    return { id: element.placeholderId, type: element.placeholderType, idx: element.placeholderIdx };
  }
  return null;
}

function placeholderTypeMatches(left, right) {
  const aliases = {
    title: new Set(["title", "ctrtitle"]),
    subtitle: new Set(["subtitle", "sub-title"]),
    body: new Set(["body", "obj", "text", "content"]),
    caption: new Set(["caption", "ftr", "hdr", "dt", "sldnum"]),
    chart: new Set(["chart"]),
    table: new Set(["tbl", "table"]),
  };
  const normalize = (value) => String(value ?? "").toLowerCase().replaceAll("-", "");
  const a = normalize(left);
  const b = normalize(right);
  if (a === b) return true;
  const aSet = aliases[a] ?? new Set([a]);
  const bSet = aliases[b] ?? new Set([b]);
  return [...aSet].some((value) => bSet.has(value));
}

function matchesPlaceholder(placeholder, reference) {
  if (!reference) return false;
  const idMatches = !reference.id || reference.id === placeholder.id || reference.id === placeholder.name;
  if (reference.id && !idMatches && !reference.semantic) return false;
  if (reference.name && reference.name !== placeholder.name) return false;
  if (reference.type && !placeholderTypeMatches(reference.type, placeholder.type) && !idMatches) return false;
  if (reference.idx !== undefined && Number(reference.idx) !== Number(placeholder.idx)) return false;
  return idMatches || Boolean(reference.type || reference.idx !== undefined || reference.name);
}

function collectPlaceholders(master, layout) {
  const result = [];
  const add = (placeholder, index) => {
    const normalized = normalizePlaceholder(placeholder, index);
    const existing = result.findIndex((candidate) => candidate.id === normalized.id || (
      placeholderTypeMatches(candidate.type, normalized.type) && candidate.idx === normalized.idx
    ));
    if (existing >= 0) result[existing] = mergeValue(result[existing], normalized);
    else result.push(normalized);
  };
  for (const [index, placeholder] of (master?.placeholders ?? []).entries()) add(placeholder, index);
  for (const [index, placeholder] of (layout?.placeholders ?? []).entries()) add(placeholder, index);
  return result;
}

function findPlaceholder(placeholders, reference) {
  // A semantic string such as "subtitle" is allowed to fall back to an
  // external template's type alias, but an exact placeholder id/name must
  // win first. Standard PowerPoint title layouts commonly contain multiple
  // subTitle placeholders (for example kicker and subtitle).
  if (reference?.semantic && reference.id) {
    const exact = placeholders.find((placeholder) => placeholder.id === reference.id || placeholder.name === reference.id);
    if (exact) return exact;
  }
  return placeholders.find((placeholder) => matchesPlaceholder(placeholder, reference)) ?? null;
}

function isAutoPosition(element) {
  return element?.positionMode === "placeholder" || element?.positionMode === "auto" || element?.positionAuto === true;
}

function roleForPlaceholder(placeholder) {
  if (placeholder?.role) return placeholder.role;
  if (placeholderTypeMatches(placeholder?.type, "title")) return "title";
  if (placeholderTypeMatches(placeholder?.type, "subtitle")) return "subheading";
  if (placeholderTypeMatches(placeholder?.type, "caption")) return "caption";
  return "body";
}

function inheritedTextStyle(deck, placeholder) {
  const role = roleForPlaceholder(placeholder);
  const level = Number.isFinite(Number(placeholder?.level)) ? Number(placeholder.level) : 0;
  return mergeValue(
    textStyleForRole(deck?.textStyles ?? {}, role, level),
    textStyleForRole(deck?.master?.textStyles ?? {}, role, level),
  );
}

function materializeInheritedElement(element, slide, source, index) {
  const clone = structuredClone(element);
  clone.id = `${source}-${slide.id}-${element.id ?? index}`;
  clone.sourceId = element.id ?? null;
  clone.inheritedFrom = source;
  clone.zIndex = Number(element.zIndex ?? 0) - 100000 + index;
  return clone;
}

function resolveElement(element, placeholders, deck) {
  const resolved = structuredClone(element);
  const reference = placeholderRef(element);
  const placeholder = findPlaceholder(placeholders, reference);
  if (!placeholder) {
    if (resolved.type === "text") {
      const level = Number.isFinite(Number(resolved.bulletLevel)) ? Number(resolved.bulletLevel) : 0;
      resolved.style = mergeValue(
        textStyleForRole(deck?.textStyles ?? {}, resolved.role ?? "body", level),
        resolved.style ?? {},
      );
    }
    return resolved;
  }

  const position = isAutoPosition(element) || !element.position ? placeholder.position : element.position;
  resolved.position = normalizePosition(position);
  resolved.style = mergeValue(
    mergeValue(inheritedTextStyle(deck, placeholder), placeholder.style ?? {}),
    element.style ?? {},
  );
  resolved.role = element.role ?? roleForPlaceholder(placeholder);
  resolved.placeholderId = placeholder.id;
  resolved.placeholderType = placeholder.type;
  resolved.placeholderIdx = placeholder.idx;
  if (!resolved.name || resolved.name === "element" || resolved.name === "text") resolved.name = placeholder.name;
  if (resolved.type === "text" && resolved.text === undefined && placeholder.text !== undefined) resolved.text = placeholder.text;
  return resolved;
}

export function resolveSlideLayout(deck, sourceSlide, { includeInherited = true } = {}) {
  if (sourceSlide?.layoutResolved === true) return sourceSlide;
  const slide = structuredClone(sourceSlide);
  const master = deck?.master ?? {};
  const layouts = Array.isArray(deck?.layouts) ? deck.layouts : [];
  const layout = layouts.find((candidate) => candidate.id === slide.layoutId) ?? layouts[0] ?? {};
  const placeholders = collectPlaceholders(master, layout);
  const inherited = [];
  if (includeInherited) {
    for (const [index, element] of (master.elements ?? []).entries()) inherited.push(materializeInheritedElement(element, slide, "master", index));
    for (const [index, element] of (layout.elements ?? []).entries()) inherited.push(materializeInheritedElement(element, slide, "layout", index));
  }
  slide.background = slide.background ?? layout.background ?? master.background ?? null;
  slide.elements = [
    ...inherited,
    ...(slide.elements ?? []).map((element) => resolveElement(element, placeholders, deck)),
  ];
  slide.layoutResolved = true;
  slide.resolvedLayout = {
    id: layout.id ?? null,
    name: layout.name ?? null,
    placeholderCount: placeholders.length,
  };
  return slide;
}

export function resolveDeckLayout(sourceDeck, options = {}) {
  const deck = cloneDeck(sourceDeck);
  deck.slides = deck.slides.map((slide) => resolveSlideLayout(deck, slide, options));
  return deck;
}

export function getLayout(deck, layoutId = null) {
  return (deck?.layouts ?? []).find((layout) => layout.id === layoutId) ?? deck?.layouts?.[0] ?? null;
}
