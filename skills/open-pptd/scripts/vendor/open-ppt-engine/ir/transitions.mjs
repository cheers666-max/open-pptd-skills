const TRANSITION_EFFECTS = new Set([
  "blinds", "checker", "circle", "comb", "cover", "cut", "diamond", "dissolve", "fade",
  "newsflash", "plus", "push", "random", "randomBar", "split", "strips", "uncover", "wheel",
  "wipe", "wedge", "zoom",
]);

const SPEEDS = new Set(["slow", "med", "fast"]);

function integer(value, fallback = null) {
  if (value === undefined || value === null || value === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.round(parsed)) : fallback;
}

function speed(value) {
  const normalized = String(value ?? "med").toLowerCase();
  return SPEEDS.has(normalized) ? normalized : "med";
}

/**
 * Normalize the small, portable part of the OOXML transition contract.
 * Unknown effects are rejected instead of being silently exported as fade.
 */
export function normalizeTransition(value) {
  if (!value) return null;
  const source = typeof value === "string" ? { type: value } : value;
  const type = String(source.type ?? source.effect ?? "fade").trim();
  const effect = [...TRANSITION_EFFECTS].find((candidate) => candidate.toLowerCase() === type.toLowerCase());
  if (!effect) throw new Error(`Unsupported slide transition effect: ${type}`);
  const normalized = {
    type: effect,
    speed: speed(source.speed ?? source.spd),
    advanceOnClick: source.advanceOnClick ?? source.advClick ?? true,
  };
  const advanceMs = integer(source.advanceMs ?? source.advanceTime ?? source.advTm);
  if (advanceMs !== null) normalized.advanceMs = advanceMs;
  if (source.direction ?? source.dir) normalized.direction = String(source.direction ?? source.dir);
  if (source.spokes !== undefined) normalized.spokes = integer(source.spokes, 1);
  return normalized;
}

function escapeXml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

/** Serialize a normalized transition in the order required by p:sld. */
export function transitionXml(value) {
  const transition = normalizeTransition(value);
  if (!transition) return "";
  const attrs = [
    `spd="${escapeXml(transition.speed)}"`,
    `advClick="${transition.advanceOnClick ? 1 : 0}"`,
    transition.advanceMs !== undefined ? `advTm="${transition.advanceMs}"` : "",
  ].filter(Boolean).join(" ");
  const effectAttrs = [
    transition.direction ? `dir="${escapeXml(transition.direction)}"` : "",
    transition.spokes !== undefined ? `spokes="${transition.spokes}"` : "",
  ].filter(Boolean).join(" ");
  return `<p:transition${attrs ? ` ${attrs}` : ""}><p:${transition.type}${effectAttrs ? ` ${effectAttrs}` : ""}/></p:transition>`;
}

export function parseTransition(value) {
  if (!value) return null;
  return normalizeTransition(value);
}
