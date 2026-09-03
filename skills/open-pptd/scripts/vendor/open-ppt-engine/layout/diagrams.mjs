const DEFAULT_COLORS = ["#B32635", "#2A2B2E", "#B66B31", "#8E1B27", "#6E6B65", "#167C8D"];

function number(value, fallback) {
  return Number.isFinite(Number(value)) ? Number(value) : fallback;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function normalizedNodes(spec) {
  return (Array.isArray(spec?.nodes) ? spec.nodes : []).map((node, index) => {
    const value = typeof node === "string" ? { label: node } : node ?? {};
    return {
      id: String(value.id ?? `node-${index + 1}`),
      label: String(value.label ?? value.title ?? value.text ?? `Node ${index + 1}`),
      detail: value.detail ?? value.description ?? "",
      color: value.color ?? null,
      textColor: value.textColor ?? null,
      ...(value.style ? { style: structuredClone(value.style) } : {}),
    };
  });
}

function normalizedEdges(spec, nodes) {
  const ids = new Set(nodes.map((node) => node.id));
  return (Array.isArray(spec?.edges) ? spec.edges : []).map((edge) => {
    const value = typeof edge === "string" ? {} : edge ?? {};
    return { from: String(value.from ?? ""), to: String(value.to ?? ""), ...(value.color ? { color: value.color } : {}) };
  }).filter((edge) => ids.has(edge.from) && ids.has(edge.to) && edge.from !== edge.to);
}

function cardChildren(node, box, options, index) {
  const palette = options.colors ?? DEFAULT_COLORS;
  const fill = node.color ?? palette[index % palette.length];
  const textColor = node.textColor ?? options.textColor ?? "#FFFFFF";
  const shape = {
    type: "shape",
    id: `${node.id}-surface`,
    name: `${node.label} surface`,
    geometry: options.geometry ?? "roundRect",
    position: box,
    style: {
      fill,
      line: { color: options.lineColor ?? fill, width: number(options.lineWidth, 1) },
      radius: number(options.radius, 16),
      ...(node.style?.shape ?? {}),
    },
    role: "diagram-node",
    zIndex: 10,
  };
  const text = {
    type: "text",
    id: `${node.id}-label`,
    name: node.label,
    position: { left: box.left + 16, top: box.top + 12, width: Math.max(1, box.width - 32), height: Math.max(1, box.height - (node.detail ? 42 : 24)) },
    text: node.detail ? `${node.label}\n${node.detail}` : node.label,
    style: {
      fontFamily: options.fontFamily ?? "Aptos",
      fontSize: number(options.fontSize, 18),
      color: textColor,
      bold: true,
      align: "center",
      valign: "middle",
      lineHeight: 1.1,
      ...(node.style?.text ?? {}),
    },
    role: "diagram-label",
    zIndex: 11,
    allowOverlap: true,
  };
  return [shape, text];
}

function rectangleAnchor(rect, target) {
  const center = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  const dx = Number(target.x) - center.x;
  const dy = Number(target.y) - center.y;
  if (dx === 0 && dy === 0) return center;
  const scaleX = Math.abs(dx) > 0 ? (rect.width / 2) / Math.abs(dx) : Number.POSITIVE_INFINITY;
  const scaleY = Math.abs(dy) > 0 ? (rect.height / 2) / Math.abs(dy) : Number.POSITIVE_INFINITY;
  const scale = Math.min(scaleX, scaleY);
  return { x: center.x + dx * scale, y: center.y + dy * scale };
}

function lineChild(from, to, options, index) {
  const dx = Number(to.x) - Number(from.x);
  const dy = Number(to.y) - Number(from.y);
  const left = Math.min(from.x, to.x);
  const top = Math.min(from.y, to.y);
  const width = Math.max(1, Math.abs(dx));
  const height = Math.max(1, Math.abs(dy));
  return {
    type: "shape",
    id: `edge-${index + 1}`,
    name: `Connector ${index + 1}`,
    geometry: "line",
    position: { left, top, width, height },
    ...(dx < 0 ? { flipH: true } : {}),
    ...(dy < 0 ? { flipV: true } : {}),
    style: {
      fill: "none",
      line: {
        color: options.lineColor ?? "#D3CEC3",
        width: number(options.lineWidth, 2),
        dash: options.lineDash ?? "solid",
        ...(options.beginArrowType ? { beginArrowType: options.beginArrowType } : {}),
        endArrowType: options.endArrowType ?? options.arrowType ?? "triangle",
      },
    },
    role: "diagram-connector",
    zIndex: 1,
    allowOverlap: true,
  };
}

function flowLayout(nodes, edges, box, options) {
  const gap = number(options.gap, 28);
  const height = clamp(number(options.nodeHeight, 112), 64, box.height);
  const width = clamp(number(options.nodeWidth, (box.width - gap * Math.max(0, nodes.length - 1)) / Math.max(1, nodes.length)), 100, box.width);
  const total = width * nodes.length + gap * Math.max(0, nodes.length - 1);
  const start = Math.max(0, (box.width - total) / 2);
  const positions = new Map(nodes.map((node, index) => [node.id, { left: start + index * (width + gap), top: (box.height - height) / 2, width, height }]));
  const centers = new Map(nodes.map((node) => { const p = positions.get(node.id); return [node.id, { x: p.left + p.width / 2, y: p.top + p.height / 2 }]; }));
  const connectors = (edges.length ? edges : nodes.slice(1).map((node, index) => ({ from: nodes[index].id, to: node.id }))).map((edge, index) => {
    const fromCenter = centers.get(edge.from); const toCenter = centers.get(edge.to);
    const fromBox = positions.get(edge.from); const toBox = positions.get(edge.to);
    const from = fromCenter && toCenter && fromBox ? rectangleAnchor(fromBox, toCenter) : null;
    const to = fromCenter && toCenter && toBox ? rectangleAnchor(toBox, fromCenter) : null;
    return from && to ? lineChild({ x: from.x, y: from.y }, { x: to.x, y: to.y }, { ...options, lineColor: edge.color ?? options.lineColor }, index) : null;
  }).filter(Boolean);
  return { positions, connectors };
}

function treeLayout(nodes, edges, box, options) {
  const gapX = number(options.gapX ?? options.gap, 28);
  const gapY = number(options.gapY, 56);
  const height = clamp(number(options.nodeHeight, 88), 56, box.height);
  const width = clamp(number(options.nodeWidth, 180), 100, box.width);
  const parentOf = new Map(edges.map((edge) => [edge.to, edge.from]));
  const levels = new Map();
  const levelFor = (id, stack = new Set()) => {
    if (levels.has(id)) return levels.get(id);
    if (stack.has(id)) return 0;
    const parent = parentOf.get(id);
    const level = parent ? levelFor(parent, new Set([...stack, id])) + 1 : 0;
    levels.set(id, level);
    return level;
  };
  nodes.forEach((node) => levelFor(node.id));
  const grouped = new Map();
  for (const node of nodes) { const level = levels.get(node.id) ?? 0; grouped.set(level, [...(grouped.get(level) ?? []), node]); }
  const positions = new Map();
  for (const [level, group] of grouped.entries()) {
    const total = group.length * width + Math.max(0, group.length - 1) * gapX;
    const start = Math.max(0, (box.width - total) / 2);
    group.forEach((node, index) => positions.set(node.id, { left: start + index * (width + gapX), top: Math.min(box.height - height, level * (height + gapY)), width, height }));
  }
  const centers = new Map(nodes.map((node) => { const p = positions.get(node.id); return [node.id, { x: p.left + p.width / 2, y: p.top + p.height / 2 }]; }));
  const connectors = edges.map((edge, index) => {
    const fromCenter = centers.get(edge.from); const toCenter = centers.get(edge.to);
    const fromBox = positions.get(edge.from); const toBox = positions.get(edge.to);
    const from = fromCenter && toCenter && fromBox ? rectangleAnchor(fromBox, toCenter) : null;
    const to = fromCenter && toCenter && toBox ? rectangleAnchor(toBox, fromCenter) : null;
    return from && to ? lineChild(from, to, { ...options, lineColor: edge.color ?? options.lineColor }, index) : null;
  }).filter(Boolean);
  return { positions, connectors };
}

function cycleLayout(nodes, box, options) {
  const radiusX = Math.max(0, (box.width - number(options.nodeWidth, 180)) / 2);
  const radiusY = Math.max(0, (box.height - number(options.nodeHeight, 88)) / 2);
  const center = { x: box.width / 2, y: box.height / 2 };
  const width = clamp(number(options.nodeWidth, 180), 100, box.width);
  const height = clamp(number(options.nodeHeight, 88), 56, box.height);
  const positions = new Map();
  const centers = new Map();
  nodes.forEach((node, index) => {
    const angle = -Math.PI / 2 + index * 2 * Math.PI / Math.max(1, nodes.length);
    const x = center.x + Math.cos(angle) * radiusX;
    const y = center.y + Math.sin(angle) * radiusY;
    positions.set(node.id, { left: x - width / 2, top: y - height / 2, width, height });
    centers.set(node.id, { x, y });
  });
  const connectors = nodes.map((node, index) => {
    const nextNode = nodes[(index + 1) % nodes.length];
    const fromCenter = centers.get(node.id); const toCenter = centers.get(nextNode.id);
    const fromBox = positions.get(node.id); const toBox = positions.get(nextNode.id);
    const from = rectangleAnchor(fromBox, toCenter);
    const to = rectangleAnchor(toBox, fromCenter);
    return lineChild(from, to, options, index);
  });
  return { positions, connectors };
}

function gridLayout(nodes, edges, box, options) {
  const columns = clamp(Math.round(number(options.columns ?? options.matrixColumns, Math.ceil(Math.sqrt(nodes.length)))), 1, Math.max(1, nodes.length));
  const rows = Math.ceil(nodes.length / columns);
  const gapX = number(options.gapX ?? options.gap, 24);
  const gapY = number(options.gapY ?? options.gap, 24);
  const width = clamp(number(options.nodeWidth, (box.width - gapX * Math.max(0, columns - 1)) / columns), 100, box.width);
  const height = clamp(number(options.nodeHeight, (box.height - gapY * Math.max(0, rows - 1)) / rows), 56, box.height);
  const totalWidth = width * columns + gapX * Math.max(0, columns - 1);
  const totalHeight = height * rows + gapY * Math.max(0, rows - 1);
  const startX = Math.max(0, (box.width - totalWidth) / 2);
  const startY = Math.max(0, (box.height - totalHeight) / 2);
  const positions = new Map(nodes.map((node, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    return [node.id, { left: startX + column * (width + gapX), top: startY + row * (height + gapY), width, height }];
  }));
  const centers = new Map(nodes.map((node) => {
    const p = positions.get(node.id);
    return [node.id, { x: p.left + p.width / 2, y: p.top + p.height / 2 }];
  }));
  const connectors = edges.map((edge, index) => {
    const fromBox = positions.get(edge.from);
    const toBox = positions.get(edge.to);
    const fromCenter = centers.get(edge.from);
    const toCenter = centers.get(edge.to);
    if (!fromBox || !toBox || !fromCenter || !toCenter) return null;
    return lineChild(rectangleAnchor(fromBox, toCenter), rectangleAnchor(toBox, fromCenter), { ...options, lineColor: edge.color ?? options.lineColor }, index);
  }).filter(Boolean);
  return { positions, connectors };
}

function pyramidLayout(nodes, edges, box, options) {
  const gap = number(options.gap, 12);
  const height = clamp(number(options.nodeHeight, (box.height - gap * Math.max(0, nodes.length - 1)) / Math.max(1, nodes.length)), 48, box.height);
  const positions = new Map();
  nodes.forEach((node, index) => {
    const widthRatio = (index + 1) / Math.max(1, nodes.length);
    const width = clamp(number(options.nodeWidth, box.width * (0.34 + widthRatio * 0.66)), 100, box.width);
    positions.set(node.id, {
      left: (box.width - width) / 2,
      top: index * (height + gap),
      width,
      height,
    });
  });
  const centers = new Map(nodes.map((node) => {
    const p = positions.get(node.id);
    return [node.id, { x: p.left + p.width / 2, y: p.top + p.height / 2 }];
  }));
  const connectors = [];
  for (const [index, edge] of edges.entries()) {
    const fromBox = positions.get(edge.from);
    const toBox = positions.get(edge.to);
    const fromCenter = centers.get(edge.from);
    const toCenter = centers.get(edge.to);
    if (fromBox && toBox && fromCenter && toCenter) connectors.push(lineChild(rectangleAnchor(fromBox, toCenter), rectangleAnchor(toBox, fromCenter), { ...options, lineColor: edge.color ?? options.lineColor }, index));
  }
  return { positions, connectors };
}

function radialLayout(nodes, edges, box, options) {
  const root = nodes[0];
  const children = nodes.slice(1);
  const nodeWidth = clamp(number(options.nodeWidth, 180), 100, box.width);
  const nodeHeight = clamp(number(options.nodeHeight, 72), 56, box.height);
  const center = { x: box.width / 2, y: box.height / 2 };
  const radiusX = Math.max(nodeWidth, (box.width - nodeWidth) / 2);
  const radiusY = Math.max(nodeHeight, (box.height - nodeHeight) / 2);
  const positions = new Map([[root.id, { left: center.x - nodeWidth / 2, top: center.y - nodeHeight / 2, width: nodeWidth, height: nodeHeight }]]);
  children.forEach((node, index) => {
    const angle = -Math.PI / 2 + index * 2 * Math.PI / Math.max(1, children.length);
    const x = center.x + Math.cos(angle) * radiusX;
    const y = center.y + Math.sin(angle) * radiusY;
    positions.set(node.id, { left: x - nodeWidth / 2, top: y - nodeHeight / 2, width: nodeWidth, height: nodeHeight });
  });
  const centers = new Map(nodes.map((node) => {
    const p = positions.get(node.id);
    return [node.id, { x: p.left + p.width / 2, y: p.top + p.height / 2 }];
  }));
  const effectiveEdges = edges.length ? edges : children.map((node) => ({ from: root.id, to: node.id }));
  const connectors = effectiveEdges.map((edge, index) => {
    const fromBox = positions.get(edge.from);
    const toBox = positions.get(edge.to);
    const fromCenter = centers.get(edge.from);
    const toCenter = centers.get(edge.to);
    return fromBox && toBox && fromCenter && toCenter
      ? lineChild(rectangleAnchor(fromBox, toCenter), rectangleAnchor(toBox, fromCenter), { ...options, lineColor: edge.color ?? options.lineColor }, index)
      : null;
  }).filter(Boolean);
  return { positions, connectors };
}

export function compileDiagram(spec = {}, box, options = {}) {
  const normalized = { ...spec, ...(options ?? {}) };
  const nodes = normalizedNodes(normalized);
  if (nodes.length === 0) return [];
  const edges = normalizedEdges(normalized, nodes);
  const type = String(normalized.type ?? normalized.layout ?? "flow");
  const layout = ["tree", "hierarchy"].includes(type)
    ? treeLayout(nodes, edges.length ? edges : nodes.slice(1).map((node) => ({ from: nodes[0].id, to: node.id })), box, normalized)
    : ["cycle", "relationship"].includes(type)
      ? cycleLayout(nodes, box, normalized)
      : type === "radial"
        ? radialLayout(nodes, edges, box, normalized)
        : type === "matrix"
          ? gridLayout(nodes, edges, box, normalized)
          : type === "pyramid"
            ? pyramidLayout(nodes, edges, box, normalized)
            : flowLayout(nodes, edges.length ? edges : nodes.slice(1).map((node, index) => ({ from: nodes[index].id, to: node.id })), box, normalized);
  const children = [...layout.connectors];
  const cardOptions = type === "pyramid" && !normalized.geometry ? { ...normalized, geometry: "trapezoid" } : normalized;
  nodes.forEach((node, index) => children.push(...cardChildren(node, layout.positions.get(node.id), cardOptions, index)));
  return children;
}
