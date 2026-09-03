import { compileDiagram } from "../layout/diagrams.mjs";

export const SMARTART_URI = "http://schemas.openxmlformats.org/drawingml/2006/diagram";
export const DIAGRAM_NS = "http://schemas.openxmlformats.org/drawingml/2006/diagram";
export const DIAGRAM_DATA_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramData";
export const DIAGRAM_LAYOUT_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramLayout";
export const DIAGRAM_QUICK_STYLE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramQuickStyle";
export const DIAGRAM_COLORS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramColors";
export const DIAGRAM_DRAWING_REL = "http://schemas.microsoft.com/office/2007/relationships/diagramDrawing";
export const DIAGRAM_DATA_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.drawingml.diagramData+xml";
export const DIAGRAM_LAYOUT_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.drawingml.diagramLayout+xml";
export const DIAGRAM_STYLE_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.drawingml.diagramStyle+xml";
export const DIAGRAM_COLORS_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.drawingml.diagramColors+xml";
export const DIAGRAM_DRAWING_CONTENT_TYPE = "application/vnd.ms-office.drawingml.diagramDrawing+xml";

const DEFAULT_LAYOUT_UID = "urn:microsoft.com/office/officeart/2005/8/layout/default";

function escapeXml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function stableId(index) {
  return `{00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}}`;
}

function normalizeNodes(spec) {
  return (Array.isArray(spec?.nodes) ? spec.nodes : []).map((node, index) => {
    const value = typeof node === "string" ? { label: node } : node ?? {};
    return {
      id: String(value.id ?? `node-${index + 1}`),
      label: String(value.label ?? value.title ?? value.text ?? `Node ${index + 1}`),
      detail: value.detail ?? value.description ?? "",
      color: value.color ?? null,
    };
  });
}

function normalizeEdges(spec, nodes) {
  const ids = new Set(nodes.map((node) => node.id));
  return (Array.isArray(spec?.edges) ? spec.edges : []).map((edge) => {
    const value = typeof edge === "string" ? {} : edge ?? {};
    return { from: String(value.from ?? ""), to: String(value.to ?? "") };
  }).filter((edge) => ids.has(edge.from) && ids.has(edge.to) && edge.from !== edge.to);
}

function textXml(text) {
  return `<a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="zh-CN"/><a:t>${escapeXml(text)}</a:t></a:r><a:endParaRPr lang="zh-CN"/></a:p>`;
}

function emptyTextXml() {
  return `<a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="zh-CN"/></a:p>`;
}

/**
 * Normalize a limited SmartArt semantic model. The visual fallback is always
 * compiled to ordinary editable shapes; `native` asks the OOXML writer to add
 * a real diagram data/layout package for PowerPoint.
 */
export function normalizeSmartArt(spec = {}, options = {}) {
  const nodes = normalizeNodes(spec);
  if (nodes.length === 0) throw new Error("SmartArt requires at least one node");
  const type = String(options.type ?? spec.type ?? spec.layout ?? "tree");
  const supportedTypes = new Set(["tree", "hierarchy", "flow", "process", "cycle", "relationship", "radial", "matrix", "pyramid"]);
  if (!supportedTypes.has(type)) throw new Error(`Unsupported SmartArt family: ${type}`);
  const edges = normalizeEdges(spec, nodes);
  const effectiveEdges = edges.length
    ? edges
    : ["flow", "process"].includes(type)
      ? nodes.slice(1).map((node, index) => ({ from: nodes[index].id, to: node.id }))
      : ["tree", "hierarchy", "radial"].includes(type)
        ? nodes.slice(1).map((node) => ({ from: nodes[0].id, to: node.id }))
        : ["cycle", "relationship"].includes(type)
          ? nodes.map((node, index) => ({ from: node.id, to: nodes[(index + 1) % nodes.length].id }))
          : [];
  return {
    kind: type,
    layoutUid: String(options.layoutUid ?? spec.layoutUid ?? DEFAULT_LAYOUT_UID),
    nodes,
    edges: effectiveEdges,
    // Keep the cross-renderer editable fallback as the safe default. A caller
    // must opt into a PowerPoint-native diagram package explicitly.
    native: Boolean(options.native ?? spec.native ?? false),
    nativeOnly: Boolean(options.nativeOnly ?? spec.nativeOnly),
    quickStyleUid: String(options.quickStyleUid ?? spec.quickStyleUid ?? "urn:microsoft.com/office/officeart/2005/8/quickstyle/simple5"),
    colorStyleUid: String(options.colorStyleUid ?? spec.colorStyleUid ?? "urn:microsoft.com/office/officeart/2005/8/colors/colorful4"),
    ...(spec.rawDataXml ? { rawDataXml: String(spec.rawDataXml) } : {}),
    ...(spec.rawLayoutXml ? { rawLayoutXml: String(spec.rawLayoutXml) } : {}),
    ...(spec.rawQuickStyleXml ? { rawQuickStyleXml: String(spec.rawQuickStyleXml) } : {}),
    ...(spec.rawColorStyleXml ? { rawColorStyleXml: String(spec.rawColorStyleXml) } : {}),
    ...(spec.rawDrawingXml ? { rawDrawingXml: String(spec.rawDrawingXml) } : {}),
    ...(spec.nativeSemanticSnapshot ? { nativeSemanticSnapshot: String(spec.nativeSemanticSnapshot) } : {}),
  };
}

/**
 * Return the semantic payload that the native diagram parts represent. Imported
 * SmartArt stores this snapshot so an edit can invalidate only the native data
 * that is no longer truthful, while an untouched diagram can keep its original
 * OOXML byte-for-byte inside the regenerated package.
 */
export function smartArtSemanticSnapshot(smartArt = {}) {
  return JSON.stringify({
    kind: String(smartArt.kind ?? "flow"),
    layoutUid: String(smartArt.layoutUid ?? DEFAULT_LAYOUT_UID),
    quickStyleUid: String(smartArt.quickStyleUid ?? ""),
    colorStyleUid: String(smartArt.colorStyleUid ?? ""),
    nodes: (smartArt.nodes ?? []).map((node) => ({
      id: String(node?.id ?? ""),
      label: String(node?.label ?? ""),
      detail: String(node?.detail ?? ""),
      color: node?.color ?? null,
    })),
    edges: (smartArt.edges ?? []).map((edge) => ({ from: String(edge?.from ?? ""), to: String(edge?.to ?? "") })),
  });
}

function nativeSnapshotObject(smartArt) {
  if (!smartArt?.nativeSemanticSnapshot) return null;
  try {
    const parsed = JSON.parse(String(smartArt.nativeSemanticSnapshot));
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

/** True only when an imported native diagram still matches its source model. */
export function smartArtNativePartsAreFresh(smartArt = {}) {
  const snapshot = nativeSnapshotObject(smartArt);
  return !snapshot || smartArtSemanticSnapshot(smartArt) === JSON.stringify(snapshot);
}

export function smartArtNativeLayoutIsFresh(smartArt = {}) {
  const snapshot = nativeSnapshotObject(smartArt);
  return !snapshot || (String(snapshot.kind) === String(smartArt.kind) && String(snapshot.layoutUid) === String(smartArt.layoutUid));
}

export function smartArtNativeStyleIsFresh(smartArt = {}) {
  const snapshot = nativeSnapshotObject(smartArt);
  return !snapshot || String(snapshot.quickStyleUid) === String(smartArt.quickStyleUid);
}

export function smartArtNativeColorsAreFresh(smartArt = {}) {
  const snapshot = nativeSnapshotObject(smartArt);
  return !snapshot || String(snapshot.colorStyleUid) === String(smartArt.colorStyleUid);
}

export function smartArtFallback(spec, position, options = {}) {
  const normalized = normalizeSmartArt(spec, options);
  return { normalized, children: compileDiagram(normalized, position, options) };
}

function dataModelXml(smartArt) {
  const ids = new Map(smartArt.nodes.map((node, index) => [node.id, stableId(index + 1)]));
  const rootId = stableId(0);
  const connectionIds = smartArt.edges.map((_, index) => stableId(smartArt.nodes.length + index + 1));
  const parentTransitionIds = smartArt.edges.map((_, index) => stableId(smartArt.nodes.length + smartArt.edges.length + index + 1));
  const siblingTransitionIds = smartArt.edges.map((_, index) => stableId(smartArt.nodes.length + smartArt.edges.length * 2 + index + 1));
  const points = [
    `<dgm:pt modelId="${rootId}" type="doc"><dgm:prSet loTypeId="${escapeXml(smartArt.layoutUid)}" loCatId="list" qsTypeId="${escapeXml(smartArt.quickStyleUid)}" qsCatId="simple" csTypeId="${escapeXml(smartArt.colorStyleUid)}" csCatId="colorful" phldr="1"/><dgm:spPr/><dgm:t>${emptyTextXml()}</dgm:t></dgm:pt>`,
    ...smartArt.nodes.map((node, index) => `<dgm:pt modelId="${ids.get(node.id)}"><dgm:prSet phldrT="[Text]"/><dgm:spPr/><dgm:t>${textXml(node.detail ? `${node.label}\n${node.detail}` : node.label)}</dgm:t></dgm:pt>`),
    ...smartArt.edges.flatMap((_, index) => [
      `<dgm:pt modelId="${parentTransitionIds[index]}" type="parTrans" cxnId="${connectionIds[index]}"><dgm:prSet/><dgm:spPr/></dgm:pt>`,
      `<dgm:pt modelId="${siblingTransitionIds[index]}" type="sibTrans" cxnId="${connectionIds[index]}"><dgm:prSet/><dgm:spPr/></dgm:pt>`,
    ]),
  ].join("");
  const connections = [
    ...smartArt.edges.map((edge, index) => `<dgm:cxn modelId="${connectionIds[index]}" type="parOf" srcId="${ids.get(edge.from) ?? rootId}" destId="${ids.get(edge.to) ?? rootId}" srcOrd="${index}" destOrd="0" parTransId="${parentTransitionIds[index]}" sibTransId="${siblingTransitionIds[index]}"/>`),
  ].join("");
  const drawingRelationshipId = smartArt.rawDrawingXml ? smartArtDrawingRelationshipId(smartArt) : null;
  const drawingExtension = drawingRelationshipId
    ? `<dsp:dataModelExt relId="${escapeXml(drawingRelationshipId)}" minVer="http://schemas.openxmlformats.org/drawingml/2006/diagram"/>`
    : "";
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><dgm:dataModel xmlns:dgm="${DIAGRAM_NS}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"${drawingExtension ? " xmlns:dsp=\"http://schemas.microsoft.com/office/drawing/2008/diagram\"" : ""}><dgm:ptLst>${points}</dgm:ptLst><dgm:cxnLst>${connections}</dgm:cxnLst><dgm:bg/><dgm:whole/>${drawingExtension}</dgm:dataModel>`;
}

function layoutAlgorithm(kind) {
  if (["tree", "hierarchy"].includes(kind)) return `<dgm:alg type="hierChild"><dgm:param type="linDir" val="fromT"/><dgm:param type="grDir" val="tB"/></dgm:alg>`;
  if (["cycle", "relationship", "radial"].includes(kind)) return `<dgm:alg type="cycle"/>`;
  if (kind === "pyramid") return `<dgm:alg type="snake"><dgm:param type="grDir" val="tB"/><dgm:param type="flowDir" val="row"/></dgm:alg>`;
  return `<dgm:alg type="snake"><dgm:param type="grDir" val="tL"/><dgm:param type="flowDir" val="row"/><dgm:param type="contDir" val="sameDir"/><dgm:param type="off" val="ctr"/></dgm:alg>`;
}

export function smartArtLayoutXml(smartArt) {
  if (smartArt.rawLayoutXml && smartArtNativeLayoutIsFresh(smartArt)) return smartArt.rawLayoutXml;
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><dgm:layoutDef xmlns:dgm="${DIAGRAM_NS}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" uniqueId="${escapeXml(smartArt.layoutUid)}"><dgm:title val="Open PPT ${escapeXml(smartArt.kind)}"/><dgm:desc val="Generated by Open PPT Engine"/><dgm:catLst><dgm:cat type="list" pri="400"/></dgm:catLst><dgm:layoutNode name="diagram"><dgm:varLst><dgm:dir/><dgm:resizeHandles val="exact"/></dgm:varLst>${layoutAlgorithm(smartArt.kind)}<dgm:shape type="rect"><dgm:adjLst/></dgm:shape><dgm:presOf/><dgm:constrLst/><dgm:ruleLst/><dgm:forEach name="nodes" axis="ch" ptType="node"><dgm:layoutNode name="node"><dgm:varLst><dgm:bulletEnabled val="1"/></dgm:varLst><dgm:alg type="tx"/><dgm:shape type="roundRect"><dgm:adjLst/></dgm:shape><dgm:presOf axis="desOrSelf" ptType="node"/><dgm:constrLst><dgm:constr type="lMarg" refType="primFontSz" fact="0.3"/><dgm:constr type="rMarg" refType="primFontSz" fact="0.3"/><dgm:constr type="tMarg" refType="primFontSz" fact="0.3"/><dgm:constr type="bMarg" refType="primFontSz" fact="0.3"/></dgm:constrLst><dgm:ruleLst/></dgm:layoutNode></dgm:forEach></dgm:layoutNode></dgm:layoutDef>`;
}

export function smartArtDataXml(smartArt) {
  return smartArt.rawDataXml && smartArtNativePartsAreFresh(smartArt) ? smartArt.rawDataXml : dataModelXml(smartArt);
}

/**
 * The data and layout parts are required by PresentationML. Quick style and
 * color parts are optional in the standard, but including them makes a native
 * SmartArt instance stable across PowerPoint re-save and preserves imported
 * style semantics instead of asking the destination theme to guess them.
 */
export function smartArtQuickStyleXml(smartArt) {
  if (smartArt.rawQuickStyleXml && smartArtNativeStyleIsFresh(smartArt)) return smartArt.rawQuickStyleXml;
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><dgm:styleDef xmlns:dgm="${DIAGRAM_NS}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" uniqueId="${escapeXml(smartArt.quickStyleUid)}"><dgm:title val="Open PPT quick style"/><dgm:desc val="Generated by Open PPT Engine"/><dgm:catLst><dgm:cat type="simple" pri="400"/></dgm:catLst><dgm:styleLst/></dgm:styleDef>`;
}

export function smartArtColorsXml(smartArt) {
  if (smartArt.rawColorStyleXml && smartArtNativeColorsAreFresh(smartArt)) return smartArt.rawColorStyleXml;
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><dgm:colorsDef xmlns:dgm="${DIAGRAM_NS}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" uniqueId="${escapeXml(smartArt.colorStyleUid)}"><dgm:title val="Open PPT colors"/><dgm:desc val="Generated by Open PPT Engine"/><dgm:catLst><dgm:cat type="colorful" pri="400"/></dgm:catLst><dgm:styleLst/></dgm:colorsDef>`;
}

export function smartArtDrawingXml(smartArt) {
  return smartArt.rawDrawingXml ?? null;
}

export function smartArtDrawingRelationshipId(smartArt) {
  const raw = String(smartArt?.rawDataXml ?? "");
  const value = raw.match(/<[^>]*dataModelExt\b[^>]*\brelId\s*=\s*["']([^"']+)["']/u)?.[1];
  return value ? String(value) : "rId6";
}

export function smartArtFrameXml(element, index, dataRelId, layoutRelId, quickStyleRelId = null, colorsRelId = null) {
  const p = element.position;
  const name = escapeXml(element.name ?? `smartArt-${index}`);
  const styleAttributes = [
    `r:dm="${dataRelId}"`,
    `r:lo="${layoutRelId}"`,
    ...(quickStyleRelId ? [`r:qs="${quickStyleRelId}"`] : []),
    ...(colorsRelId ? [`r:cs="${colorsRelId}"`] : []),
  ].join(" ");
  return `<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="${index + 2}" name="${name}"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="${Math.round(p.left * 9525)}" y="${Math.round(p.top * 9525)}"/><a:ext cx="${Math.round(p.width * 9525)}" cy="${Math.round(p.height * 9525)}"/></p:xfrm><a:graphic><a:graphicData uri="${SMARTART_URI}"><dgm:relIds xmlns:dgm="${DIAGRAM_NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ${styleAttributes}/></a:graphicData></a:graphic></p:graphicFrame>`;
}
