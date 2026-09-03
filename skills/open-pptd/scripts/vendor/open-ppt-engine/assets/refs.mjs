export const ASSET_URI_PREFIX = "asset://";

export function assetUri(assetId) {
  const value = String(assetId ?? "").trim();
  if (!value) throw new TypeError("assetId is required");
  return `${ASSET_URI_PREFIX}${value}`;
}

export function assetIdFrom(value) {
  if (value && typeof value === "object" && value.assetId) return String(value.assetId);
  if (value && typeof value === "object" && value.source && value.source !== value) return assetIdFrom(value.source);
  const source = String(value ?? "");
  return source.startsWith(ASSET_URI_PREFIX) ? source.slice(ASSET_URI_PREFIX.length) : null;
}

export function isAssetReference(value) {
  return Boolean(assetIdFrom(value));
}

export async function resolveAssetReference(value, assetResolver = null) {
  const assetId = assetIdFrom(value);
  if (!assetId) return typeof value === "object" && value?.source ? value.source : value;
  if (typeof assetResolver !== "function") throw new Error(`Asset reference cannot be resolved without an assetResolver: ${assetId}`);
  const resolved = await assetResolver(assetId);
  if (!resolved) throw new Error(`Asset resolver returned no source for ${assetId}`);
  return resolved;
}
