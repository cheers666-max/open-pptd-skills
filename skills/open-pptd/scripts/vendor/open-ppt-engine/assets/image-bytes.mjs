/**
 * Image byte sniffing helpers shared by the OOXML writer and the PPTD
 * remote-asset prefetcher. File extensions and content-type headers are
 * routinely wrong for downloaded assets; the magic bytes are not.
 */

const CONTENT_TYPE_MAP = Object.freeze({
  "image/png": { mimeType: "image/png", extension: "png" },
  "image/jpeg": { mimeType: "image/jpeg", extension: "jpg" },
  "image/jpg": { mimeType: "image/jpeg", extension: "jpg" },
  "image/gif": { mimeType: "image/gif", extension: "gif" },
  "image/svg+xml": { mimeType: "image/svg+xml", extension: "svg" },
  "image/webp": { mimeType: "image/webp", extension: "webp" },
});

const URL_EXTENSION_MAP = Object.freeze({
  png: { mimeType: "image/png", extension: "png" },
  jpg: { mimeType: "image/jpeg", extension: "jpg" },
  jpeg: { mimeType: "image/jpeg", extension: "jpg" },
  gif: { mimeType: "image/gif", extension: "gif" },
  svg: { mimeType: "image/svg+xml", extension: "svg" },
  webp: { mimeType: "image/webp", extension: "webp" },
});

/** Detect the real image type from magic bytes. Returns null when unknown. */
export function sniffImageType(data) {
  if (!data || data.length < 4) return null;
  if (data[0] === 0x89 && data[1] === 0x50 && data[2] === 0x4e && data[3] === 0x47) return { mimeType: "image/png", extension: "png" };
  if (data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff) return { mimeType: "image/jpeg", extension: "jpg" };
  if (data.length >= 6 && data.subarray(0, 6).toString("latin1") === "GIF89a") return { mimeType: "image/gif", extension: "gif" };
  if (data.length >= 6 && data.subarray(0, 6).toString("latin1") === "GIF87a") return { mimeType: "image/gif", extension: "gif" };
  if (data.length >= 12 && data.subarray(0, 4).toString("latin1") === "RIFF" && data.subarray(8, 12).toString("latin1") === "WEBP") return { mimeType: "image/webp", extension: "webp" };
  const head = data.subarray(0, 512).toString("utf8").trimStart().toLowerCase();
  if (head.startsWith("<svg") || (head.startsWith("<?xml") && head.slice(0, 400).includes("<svg"))) return { mimeType: "image/svg+xml", extension: "svg" };
  return null;
}

/** Map an HTTP content-type header to an image type. Returns null when unknown. */
export function imageTypeFromContentType(value) {
  const key = String(value ?? "").split(";", 1)[0].trim().toLowerCase();
  return CONTENT_TYPE_MAP[key] ?? null;
}

/** Map a URL or filename extension to an image type. Returns null when unknown. */
export function imageTypeFromUrl(value) {
  const pathname = String(value ?? "").split(/[?#]/u, 1)[0];
  const extension = pathname.split(".").pop()?.toLowerCase() ?? "";
  return URL_EXTENSION_MAP[extension] ?? null;
}
