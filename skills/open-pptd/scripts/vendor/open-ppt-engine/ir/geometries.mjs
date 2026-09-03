// Common preset geometry names shared by OOXML, PptxGenJS and the HTML preview.
// The names intentionally follow DrawingML / PptxGenJS where possible.
export const PRESET_GEOMETRIES = Object.freeze([
  "rect", "roundRect", "ellipse", "line", "triangle", "rtTriangle", "diamond",
  "parallelogram", "trapezoid", "hexagon", "pentagon", "chevron", "rightArrow",
  "leftArrow", "upArrow", "downArrow", "cloud", "arc", "star5", "plus", "teardrop",
  "can", "cube", "heart", "lightningBolt",
]);

const PRESET_SET = new Set(PRESET_GEOMETRIES);
const ALIASES = new Map([
  ["rectangle", "rect"],
  ["roundedRectangle", "roundRect"],
  ["rounded-rectangle", "roundRect"],
  ["right-arrow", "rightArrow"],
  ["left-arrow", "leftArrow"],
  ["up-arrow", "upArrow"],
  ["down-arrow", "downArrow"],
  ["righttriangle", "rtTriangle"],
]);

export function normalizeGeometry(value, fallback = "rect") {
  const raw = String(value ?? fallback);
  const normalized = ALIASES.get(raw) ?? raw;
  return PRESET_SET.has(normalized) ? normalized : fallback;
}

export function isPresetGeometry(value) {
  return PRESET_SET.has(String(value ?? ""));
}
