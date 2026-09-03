const EFFECTS = new Set([
  "appear",
  "fade",
  "blinds",
  "checkerboard",
  "circle",
  "dissolve",
  "fly",
  "plus",
  "randomBars",
  "split",
  "strips",
  "wheel",
  "wipe",
  "zoom",
]);

const BEHAVIORS = new Set(["effect", "motion", "rotation", "scale", "set"]);

const TRIGGERS = new Set(["on-click", "with-previous", "after-previous"]);
const TRANSITIONS = new Set(["in", "out", "none"]);
const DEFAULT_DURATION_MS = 500;

function escapeXml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function clamp(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
}

function repeatCount(value) {
  if (value === undefined || value === null || value === "") return null;
  if (String(value).toLowerCase() === "indefinite") return "indefinite";
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

function timingPercent(value) {
  if (value === undefined || value === null || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return Math.max(0, Math.min(100, number > 100 ? number / 1000 : number));
}

function directionFilter(effect, direction) {
  if (!direction || ["fade", "appear", "dissolve", "zoom", "circle", "plus", "wheel"].includes(effect)) return effect;
  const normalized = String(direction).trim();
  return normalized ? effect + "(" + normalized + ")" : effect;
}

function behaviorOf(source) {
  if (source.property !== undefined || source.attribute !== undefined || source.behavior === "set" || source.animationType === "set") return "set";
  if (source.motion || source.path || source.behavior === "motion" || source.animationType === "motion") return "motion";
  if (source.rotation !== undefined || source.angle !== undefined || source.behavior === "rotation" || source.animationType === "rotation") return "rotation";
  if (source.scale !== undefined || source.behavior === "scale" || source.animationType === "scale") return "scale";
  return String(source.behavior ?? source.animationType ?? "effect").toLowerCase();
}

function baseEffect(filter, fallback = "fade") {
  const value = String(filter ?? "").trim();
  const match = value.match(/^([a-zA-Z]+)(?:\(([^)]+)\))?$/u);
  const effect = match?.[1] ?? fallback;
  return { effect, direction: match?.[2] ?? undefined };
}

function normalizedTransition(value) {
  const transition = String(value ?? "in").toLowerCase();
  return TRANSITIONS.has(transition) ? transition : "in";
}

/**
 * Normalize the portable subset of PresentationML object animation.
 *
 * targetId points at an IR element. targetSourceId is used by the importer
 * for a source PPTX cNvPr id so an imported timing tree can be remapped when
 * the deck is exported again.
 */
export function normalizeAnimation(value) {
  if (!value) return null;
  const source = typeof value === "string" ? { effect: value } : value;
  const behavior = behaviorOf(source);
  if (!BEHAVIORS.has(behavior)) {
    return {
      unsupported: true,
      behavior,
      effect: source.effect ?? source.type ?? source.filter ?? behavior,
      filter: source.filter ?? source.effect ?? behavior,
      raw: source.raw,
      targetId: source.targetId ?? source.elementId ?? null,
      targetSourceId: source.targetSourceId ?? null,
    };
  }
  const target = source.targetId ?? source.elementId;
  const triggerTarget = source.triggerTargetId ?? source.triggerElementId;
  const normalizedRepeatCount = repeatCount(source.repeatCount ?? source.repeat);
  const normalizedRepeatDuration = source.repeatDurationMs ?? source.repeatDur ?? source.repeatDuration;
  const normalizedAccelerate = timingPercent(source.accelerate);
  const normalizedDecelerate = timingPercent(source.decelerate);
  const autoReverseValue = source.autoReverse ?? source.autoRev;
  const normalizedAutoReverse = autoReverseValue === true || autoReverseValue === 1 || autoReverseValue === "1" || String(autoReverseValue).toLowerCase() === "true";
  const common = {
    kind: behavior,
    transition: normalizedTransition(source.transition ?? (source.exit ? "out" : "in")),
    trigger: TRIGGERS.has(source.trigger) ? source.trigger : "after-previous",
    durationMs: Math.round(clamp(source.durationMs ?? source.duration, 1, 600000, DEFAULT_DURATION_MS)),
    delayMs: Math.round(clamp(source.delayMs ?? source.delay, 0, 600000, 0)),
    ...(target ? { targetId: target } : {}),
    ...(triggerTarget ? { triggerTargetId: triggerTarget } : {}),
    ...(source.targetSourceId !== undefined && source.targetSourceId !== null ? { targetSourceId: String(source.targetSourceId) } : {}),
    ...(source.triggerTargetSourceId !== undefined && source.triggerTargetSourceId !== null ? { triggerTargetSourceId: String(source.triggerTargetSourceId) } : {}),
    ...(normalizedRepeatCount !== null ? { repeatCount: normalizedRepeatCount } : {}),
    ...(normalizedRepeatDuration !== undefined && normalizedRepeatDuration !== null && normalizedRepeatDuration !== "" ? { repeatDurationMs: normalizedRepeatDuration === "indefinite" ? "indefinite" : Math.round(clamp(normalizedRepeatDuration, 1, 600000, 1)) } : {}),
    ...(normalizedAccelerate !== null ? { accelerate: normalizedAccelerate } : {}),
    ...(normalizedDecelerate !== null ? { decelerate: normalizedDecelerate } : {}),
    ...(autoReverseValue !== undefined ? { autoReverse: normalizedAutoReverse } : {}),
  };
  if (behavior === "motion") {
    const motion = source.motion && typeof source.motion === "object" ? source.motion : source;
    const path = String(motion.path ?? source.path ?? "").trim();
    if (!path) return { ...common, unsupported: true, effect: "motion", filter: "motion", raw: source.raw };
    return {
      ...common,
      path,
      ...(motion.origin ? { origin: String(motion.origin) } : {}),
    };
  }
  if (behavior === "rotation") {
    const valueInDegrees = Number(source.rotation ?? source.angle ?? source.by ?? 0);
    if (!Number.isFinite(valueInDegrees)) return { ...common, unsupported: true, effect: "rotation", filter: "rotation", raw: source.raw };
    return { ...common, byDegrees: Math.max(-360000, Math.min(360000, valueInDegrees)) };
  }
  if (behavior === "scale") {
    const scale = source.scale && typeof source.scale === "object" ? source.scale : source;
    const x = Number(scale.x ?? scale.width ?? scale.byX ?? scale.by ?? 1);
    const y = Number(scale.y ?? scale.height ?? scale.byY ?? scale.by ?? 1);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return { ...common, unsupported: true, effect: "scale", filter: "scale", raw: source.raw };
    return { ...common, x: Math.max(-10, Math.min(10, x)), y: Math.max(-10, Math.min(10, y)) };
  }
  if (behavior === "set") {
    const property = String(source.property ?? source.attribute ?? "").trim();
    if (!property || source.value === undefined) {
      return { ...common, unsupported: true, effect: "set", filter: "set", raw: source.raw };
    }
    return { ...common, property, value: source.value };
  }
  const parsed = baseEffect(source.effect ?? source.type ?? source.filter, "fade");
  const effect = parsed.effect;
  if (!EFFECTS.has(effect)) {
    return {
      ...common,
      unsupported: true,
      effect,
      filter: source.filter ?? effect,
      raw: source.raw,
    };
  }
  const direction = source.direction ?? parsed.direction;
  const filter = source.filter ?? directionFilter(effect, direction);
  return {
    ...common,
    effect,
    filter,
    ...(direction ? { direction: String(direction) } : {}),
  };
}

export function normalizeAnimations(values) {
  const list = Array.isArray(values) ? values : values ? [values] : [];
  return list.map(normalizeAnimation).filter(Boolean);
}

function collectElementAnimations(elements, output = []) {
  for (const element of elements ?? []) {
    const animations = normalizeAnimations(element.animation ?? element.animations);
    for (const animation of animations) output.push({ ...animation, targetId: animation.targetId ?? element.id });
    if (element.type === "group") collectElementAnimations(element.children, output);
  }
  return output;
}

export function collectSlideAnimations(slide) {
  const result = [];
  for (const animation of normalizeAnimations(slide?.animations ?? slide?.timing?.animations)) result.push(animation);
  collectElementAnimations(slide?.elements, result);
  return result;
}

function targetSpid(animation, targetMap) {
  const targetId = animation.targetId ?? animation.targetSourceId;
  if (targetId === undefined || targetId === null) return null;
  const value = targetMap instanceof Map ? targetMap.get(String(targetId)) ?? targetMap.get(targetId) : targetMap?.[targetId];
  return Number.isFinite(Number(value)) ? Number(value) : null;
}

function triggerCondition(animation, targetMap) {
  const triggerTarget = targetSpid({ targetId: animation.triggerTargetId ?? animation.triggerTargetSourceId }, targetMap);
  const targetXml = triggerTarget === null ? "" : `<p:tgtEl><p:spTgt spid="${triggerTarget}"/></p:tgtEl>`;
  if (animation.trigger === "on-click") return `<p:cond evt="onClick" delay="0">${targetXml}</p:cond>`;
  return `<p:cond delay="${Math.max(0, Math.round(animation.delayMs ?? 0))}">${targetXml}</p:cond>`;
}

function behaviorXml(animation, nodeId, spid) {
  const timingAttributes = [
    `id="${nodeId}"`,
    `dur="${Math.max(1, Math.round(animation.durationMs ?? DEFAULT_DURATION_MS))}"`,
    `fill="hold"`,
    animation.repeatCount !== undefined ? `repeatCount="${escapeXml(animation.repeatCount)}"` : "",
    animation.repeatDurationMs !== undefined ? `repeatDur="${escapeXml(animation.repeatDurationMs)}"` : "",
    animation.accelerate !== undefined ? `accelerate="${Math.round(Math.max(0, Math.min(100, Number(animation.accelerate))) * 1000)}"` : "",
    animation.decelerate !== undefined ? `decelerate="${Math.round(Math.max(0, Math.min(100, Number(animation.decelerate))) * 1000)}"` : "",
    animation.autoReverse !== undefined ? `autoRev="${animation.autoReverse ? 1 : 0}"` : "",
  ].filter(Boolean).join(" ");
  const target = `<p:cBhvr><p:cTn ${timingAttributes}/><p:tgtEl><p:spTgt spid="${spid}"/></p:tgtEl></p:cBhvr>`;
  if (animation.kind === "set") {
    const value = animation.value;
    const valueXml = typeof value === "boolean"
      ? `<p:boolVal val="${value ? 1 : 0}"/>`
      : typeof value === "number"
        ? `<p:fltVal val="${escapeXml(value)}"/>`
        : `<p:strVal val="${escapeXml(value)}"/>`;
    const setTarget = `<p:cBhvr><p:cTn ${timingAttributes}/><p:tgtEl><p:spTgt spid="${spid}"/></p:tgtEl><p:attrNameLst><p:attrName>${escapeXml(animation.property)}</p:attrName></p:attrNameLst></p:cBhvr>`;
    return `<p:set>${setTarget}<p:to>${valueXml}</p:to></p:set>`;
  }
  if (animation.kind === "set" && animation.property === "__legacy__") {
    const value = animation.value;
    const valueXml = typeof value === "boolean"
      ? `<p:boolVal val="${value ? 1 : 0}"/>`
      : typeof value === "number"
        ? `<p:fltVal val="${escapeXml(value)}"/>`
        : `<p:strVal val="${escapeXml(value)}"/>`;
    return `<p:set>${target.replace("</p:tgtEl></p:cBhvr>", `<p:tgtEl><p:spTgt spid="${spid}"/></p:tgtEl><p:attrNameLst><p:attrName>${escapeXml(animation.property)}</p:attrName></p:cBhvr>`)}<p:to>${valueXml}</p:to></p:set>`;
  }
  if (animation.kind === "motion") return `<p:animMotion path="${escapeXml(animation.path)}"${animation.origin ? ` origin="${escapeXml(animation.origin)}"` : ""}>${target}</p:animMotion>`;
  if (animation.kind === "rotation") return `<p:animRot by="${Math.round(Number(animation.byDegrees ?? 0) * 60000)}">${target}</p:animRot>`;
  if (animation.kind === "scale") return `<p:animScale x="${Math.round(Number(animation.x ?? 1) * 100000)}" y="${Math.round(Number(animation.y ?? 1) * 100000)}" zoomContents="1">${target}</p:animScale>`;
  const filter = escapeXml(animation.filter ?? animation.effect ?? "fade");
  const transition = escapeXml(animation.transition ?? "in");
  return '<p:animEffect transition="' + transition + '" filter="' + filter + '">' + target + '</p:animEffect>';
}

function remapRawTiming(rawXml, targetMap) {
  if (!rawXml) return "";
  return String(rawXml).replace(/(\bspid\s*=\s*["'])(\d+)(["'])/gu, (match, prefix, sourceId, suffix) => {
    const mapped = targetMap instanceof Map ? targetMap.get(String(sourceId)) ?? targetMap.get(sourceId) : targetMap?.[sourceId];
    return mapped === undefined ? match : prefix + mapped + suffix;
  });
}

/**
 * Serialize a small, valid PresentationML timing tree. Unsupported raw timing
 * is returned when no normalized animation is available, so import/export can
 * preserve timing trees instead of silently dropping them.
 */
export function timingXml(slideOrTiming, targetMap = new Map()) {
  const timing = slideOrTiming?.timing ?? slideOrTiming ?? {};
  const animations = slideOrTiming?.elements
    ? collectSlideAnimations(slideOrTiming)
    : normalizeAnimations(timing.animations ?? (slideOrTiming?.animations ?? []));
  const normalized = animations.filter((animation) => !animation.unsupported).map((animation) => ({
    ...animation,
    targetSpid: targetSpid(animation, targetMap),
  })).filter((animation) => animation.targetSpid !== null);
  if (timing.rawXml && (timing.preserveRaw === true || Number(timing.unparsedBehaviorCount ?? 0) > 0 || animations.some((animation) => animation.unsupported) || normalized.length !== animations.length)) {
    return remapRawTiming(timing.rawXml, targetMap);
  }
  if (normalized.length === 0) return remapRawTiming(timing.rawXml, targetMap);

  let nextId = 2;
  const blocks = [];
  for (const animation of normalized) {
    const behaviorId = ++nextId;
    const effect = behaviorXml(animation, behaviorId, animation.targetSpid);
    const previous = blocks[blocks.length - 1];
    if (animation.trigger === "with-previous" && previous) {
      previous.effects.push(effect);
      continue;
    }
    blocks.push({ animation, nodeId: ++nextId, effects: [effect] });
  }
  const children = blocks.map((block) => '<p:par><p:cTn id="' + block.nodeId + '" fill="hold"><p:stCondLst>' + triggerCondition(block.animation, targetMap) + '</p:stCondLst><p:childTnLst>' + block.effects.join("") + '</p:childTnLst></p:cTn></p:par>').join("");
  return '<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst><p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>' + children + '</p:childTnLst></p:cTn></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>';
}

export function parseTimingAnimation(node, conditionNode = null) {
  const local = (value) => String(value ?? "").split(":").pop();
  const behaviorName = local(node?.name);
  const behaviorNode = node?.children?.find((child) => child && local(child.name) === "cBhvr");
  const timingNode = behaviorNode?.children?.find((child) => child && local(child.name) === "cTn");
  const target = behaviorNode?.children?.find((child) => child && local(child.name) === "tgtEl")?.children
    ?.find((child) => child && local(child.name) === "spTgt");
  const filter = node?.attrs?.filter ?? Object.entries(node?.attrs ?? {}).find(([key]) => key.endsWith(":filter"))?.[1] ?? "fade";
  const transition = node?.attrs?.transition ?? Object.entries(node?.attrs ?? {}).find(([key]) => key.endsWith(":transition"))?.[1] ?? "in";
  const conditionList = behaviorNode?.children?.find((child) => child && local(child.name) === "stCondLst");
  const condition = conditionNode ?? conditionList?.children?.find((child) => child && local(child.name) === "cond");
  const common = {
    transition,
    durationMs: timingNode?.attrs?.dur ?? Object.entries(timingNode?.attrs ?? {}).find(([key]) => key.endsWith(":dur"))?.[1],
    delayMs: condition?.attrs?.delay ?? Object.entries(condition?.attrs ?? {}).find(([key]) => key.endsWith(":delay"))?.[1],
    targetSourceId: target?.attrs?.spid ?? Object.entries(target?.attrs ?? {}).find(([key]) => key.endsWith(":spid"))?.[1],
    repeatCount: timingNode?.attrs?.repeatCount ?? Object.entries(timingNode?.attrs ?? {}).find(([key]) => key.endsWith(":repeatCount"))?.[1],
    repeatDur: timingNode?.attrs?.repeatDur ?? Object.entries(timingNode?.attrs ?? {}).find(([key]) => key.endsWith(":repeatDur"))?.[1],
    accelerate: timingNode?.attrs?.accelerate ?? Object.entries(timingNode?.attrs ?? {}).find(([key]) => key.endsWith(":accelerate"))?.[1],
    decelerate: timingNode?.attrs?.decelerate ?? Object.entries(timingNode?.attrs ?? {}).find(([key]) => key.endsWith(":decelerate"))?.[1],
    autoRev: timingNode?.attrs?.autoRev ?? Object.entries(timingNode?.attrs ?? {}).find(([key]) => key.endsWith(":autoRev"))?.[1],
  };
  const triggerTarget = condition?.children?.find((child) => child && local(child.name) === "tgtEl")?.children
    ?.find((child) => child && local(child.name) === "spTgt");
  if (triggerTarget?.attrs?.spid !== undefined) common.triggerTargetSourceId = triggerTarget.attrs.spid;
  const attribute = behaviorNode?.children?.find((child) => child && local(child.name) === "attrNameLst")?.children
    ?.find((child) => child && local(child.name) === "attrName");
  const valueNode = node?.children?.find((child) => child && local(child.name) === "to")?.children?.find((child) => child);
  const value = valueNode
    ? (valueNode.attrs?.val !== undefined ? valueNode.attrs.val : valueNode.text ?? "")
    : undefined;
  let source = common;
  if (behaviorName === "animMotion") source = { ...common, behavior: "motion", path: node?.attrs?.path ?? "", origin: node?.attrs?.origin };
  else if (behaviorName === "animRot") source = { ...common, behavior: "rotation", rotation: Number(node?.attrs?.by ?? 0) / 60000 };
  else if (behaviorName === "animScale") source = { ...common, behavior: "scale", x: Number(node?.attrs?.x ?? 100000) / 100000, y: Number(node?.attrs?.y ?? 100000) / 100000 };
  else if (behaviorName === "set") source = { ...common, behavior: "set", property: attribute?.text ?? "", value };
  else {
    const parsed = baseEffect(filter, "fade");
    source = { ...common, behavior: "effect", effect: parsed.effect, direction: parsed.direction, filter };
  }
  const result = normalizeAnimation(source);
  if (result && !result.unsupported) result.trigger = condition?.attrs?.evt === "onClick" ? "on-click" : "after-previous";
  return result;
}
