const ROLE_BUCKETS = Object.freeze({
  title: "title",
  subheading: "body",
  body: "body",
  quote: "other",
  callout: "other",
  caption: "other",
  "data-grid": "body",
});

function isRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value);
}

function merge(base, override) {
  if (!isRecord(base) || !isRecord(override)) return override === undefined ? structuredClone(base) : structuredClone(override);
  const result = structuredClone(base);
  for (const [key, value] of Object.entries(override)) {
    result[key] = isRecord(result[key]) && isRecord(value) ? merge(result[key], value) : structuredClone(value);
  }
  return result;
}

function directStyle(bucket) {
  if (!isRecord(bucket)) return {};
  if (isRecord(bucket.style)) return bucket.style;
  if (bucket.levels || bucket.rawXml) return {};
  return Object.fromEntries(Object.entries(bucket).filter(([key]) => key !== "style"));
}

function levelStyle(bucket, level) {
  if (!isRecord(bucket?.levels)) return {};
  return bucket.levels[String(level)] ?? bucket.levels[level] ?? {};
}

export function textStyleBucketForRole(role) {
  return ROLE_BUCKETS[String(role ?? "body")] ?? "other";
}

export function textStyleForRole(textStyles = {}, role = "body", level = 0) {
  const bucket = textStyleBucketForRole(role);
  const defaultBucket = textStyles?.default;
  const roleBucket = textStyles?.[bucket];
  return merge(
    merge(
      merge({}, directStyle(defaultBucket)),
      levelStyle(defaultBucket, level),
    ),
    merge(directStyle(roleBucket), levelStyle(roleBucket, level)),
  );
}

export function textStyleLevels(value = {}) {
  const bucket = isRecord(value) ? value : {};
  const levels = isRecord(bucket.levels) ? structuredClone(bucket.levels) : {};
  const direct = directStyle(bucket);
  if (Object.keys(direct).length > 0 && levels["0"] === undefined && levels[0] === undefined) levels["0"] = direct;
  return levels;
}

export function normalizeTextStyles(value = {}) {
  if (!isRecord(value)) return {};
  const result = structuredClone(value);
  for (const bucket of ["default", "title", "body", "other"]) {
    if (result[bucket] !== undefined) {
      result[bucket] = {
        ...(isRecord(result[bucket]) ? result[bucket] : {}),
        levels: textStyleLevels(result[bucket]),
      };
    }
  }
  return result;
}

