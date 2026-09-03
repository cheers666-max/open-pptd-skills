import { walkElements } from "./elements.mjs";

/**
 * Collect every user-visible string that can end up in a PPTX font subset.
 * Master/layout text matters just as much as slide text because the OOXML
 * writer may preserve inherited objects instead of materialising them.
 */
export function collectDeckText(deck) {
  const chunks = [];
  const elements = [
    ...(deck?.master?.elements ?? []),
    ...(deck?.layouts ?? []).flatMap((layout) => layout.elements ?? []),
    ...(deck?.slides ?? []).flatMap((slide) => slide.elements ?? []),
  ];
  walkElements(elements, (element) => {
    if (element.type === "text") {
      chunks.push(element.text ?? "");
      for (const run of element.runs ?? []) chunks.push(run.text ?? "");
    }
    if (element.type === "formula") chunks.push(element.latex ?? element.fallbackText ?? "");
    if (element.type === "table") {
      for (const row of element.rows ?? []) for (const cell of row.cells ?? []) {
        chunks.push(cell.text ?? "");
        for (const run of cell.runs ?? []) chunks.push(run.text ?? "");
      }
    }
  });
  return chunks.join("\n");
}
