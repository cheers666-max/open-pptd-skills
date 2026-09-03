export function cropFraction(value) {
  const raw = Number(value ?? 0);
  const normalized = raw <= 1 ? raw : raw <= 100 ? raw / 100 : raw / 100000;
  return Math.max(0, Math.min(0.999, normalized));
}

export function normalizeCrop(value) {
  if (!value || typeof value !== "object") return null;
  return {
    left: cropFraction(value.left),
    top: cropFraction(value.top),
    right: cropFraction(value.right),
    bottom: cropFraction(value.bottom),
  };
}

export function coverCrop(imageWidth, imageHeight, boxWidth, boxHeight) {
  const width = Number(imageWidth);
  const height = Number(imageHeight);
  const targetWidth = Number(boxWidth);
  const targetHeight = Number(boxHeight);
  if (!(width > 0 && height > 0 && targetWidth > 0 && targetHeight > 0)) return null;
  const imageRatio = height / width;
  const boxRatio = targetHeight / targetWidth;
  if (boxRatio > imageRatio) {
    const renderedWidth = targetHeight / imageRatio;
    const horizontal = Math.max(0, Math.min(0.999, 0.5 * (1 - targetWidth / renderedWidth)));
    return { left: horizontal, top: 0, right: horizontal, bottom: 0 };
  }
  const renderedHeight = targetWidth * imageRatio;
  const vertical = Math.max(0, Math.min(0.999, 0.5 * (1 - targetHeight / renderedHeight)));
  return { left: 0, top: vertical, right: 0, bottom: vertical };
}

export function containPosition(position, imageWidth, imageHeight) {
  const width = Number(imageWidth);
  const height = Number(imageHeight);
  const box = position ?? {};
  if (!(width > 0 && height > 0 && Number(box.width) > 0 && Number(box.height) > 0)) return box;
  const imageRatio = width / height;
  const boxRatio = Number(box.width) / Number(box.height);
  const containedWidth = imageRatio > boxRatio ? Number(box.width) : Number(box.height) * imageRatio;
  const containedHeight = imageRatio > boxRatio ? Number(box.width) / imageRatio : Number(box.height);
  return {
    ...box,
    left: Number(box.left) + (Number(box.width) - containedWidth) / 2,
    top: Number(box.top) + (Number(box.height) - containedHeight) / 2,
    width: containedWidth,
    height: containedHeight,
  };
}

export function normalizeFocalPoint(value) {
  const source = Array.isArray(value) ? { x: value[0], y: value[1] } : value ?? {};
  return {
    x: Math.max(0, Math.min(1, Number(source.x ?? source.left ?? 0.5) || 0.5)),
    y: Math.max(0, Math.min(1, Number(source.y ?? source.top ?? 0.5) || 0.5)),
  };
}

export function focalPointCrop(imageWidth, imageHeight, boxWidth, boxHeight, focalPoint) {
  const centered = coverCrop(imageWidth, imageHeight, boxWidth, boxHeight);
  if (!centered) return null;
  const focal = normalizeFocalPoint(focalPoint);
  const visibleWidth = Math.max(0.001, 1 - centered.left - centered.right);
  const visibleHeight = Math.max(0.001, 1 - centered.top - centered.bottom);
  const left = Math.max(0, Math.min(1 - visibleWidth, focal.x - visibleWidth / 2));
  const top = Math.max(0, Math.min(1 - visibleHeight, focal.y - visibleHeight / 2));
  return { left, top, right: Math.max(0, 1 - left - visibleWidth), bottom: Math.max(0, 1 - top - visibleHeight) };
}
