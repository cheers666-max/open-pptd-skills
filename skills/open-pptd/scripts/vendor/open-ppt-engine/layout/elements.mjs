function positionOf(element) {
  return {
    left: Number(element?.position?.left ?? 0),
    top: Number(element?.position?.top ?? 0),
    width: Number(element?.position?.width ?? 0),
    height: Number(element?.position?.height ?? 0),
  };
}

function sortElements(elements = []) {
  return [...elements].sort((a, b) => (a.zIndex ?? 0) - (b.zIndex ?? 0));
}

/**
 * Groups use child coordinates relative to the group's position box. Renderers
 * that do not expose a stable group primitive can use this function to produce
 * absolute leaf elements without losing the group in the canonical IR.
 */
export function flattenElements(elements = []) {
  const result = [];
  let renderOrder = 0;

  function visit(element, parentOffset = { left: 0, top: 0 }, path = [], parentHidden = false) {
    const position = positionOf(element);
    if (element?.type === "group") {
      const offset = {
        left: parentOffset.left + position.left,
        top: parentOffset.top + position.top,
      };
      const hidden = parentHidden || element.hidden === true;
      for (const [index, child] of sortElements(element.children ?? []).entries()) {
        visit(child, offset, [...path, index], hidden);
      }
      return;
    }

    const clone = structuredClone(element);
    clone.position = {
      ...position,
      left: parentOffset.left + position.left,
      top: parentOffset.top + position.top,
    };
    if (parentHidden) clone.hidden = true;
    clone.zIndex = renderOrder++;
    clone.renderPath = path;
    result.push(clone);
  }

  for (const [index, element] of sortElements(elements).entries()) visit(element, { left: 0, top: 0 }, [index]);
  return result;
}

export function walkElements(elements = [], visitor) {
  function visit(element, parent = null) {
    visitor(element, parent);
    if (element?.type === "group") {
      for (const child of element.children ?? []) visit(child, element);
    }
  }
  for (const element of elements) visit(element, null);
}
