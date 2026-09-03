const OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math";

function escapeXml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

const COMMANDS = new Map([
  ["alpha", "α"], ["beta", "β"], ["gamma", "γ"], ["delta", "δ"], ["epsilon", "ϵ"],
  ["varepsilon", "ε"], ["zeta", "ζ"], ["eta", "η"], ["theta", "θ"], ["vartheta", "ϑ"],
  ["iota", "ι"], ["kappa", "κ"], ["lambda", "λ"], ["mu", "μ"], ["nu", "ν"],
  ["xi", "ξ"], ["pi", "π"], ["varpi", "ϖ"], ["rho", "ρ"], ["varrho", "ϱ"],
  ["sigma", "σ"], ["varsigma", "ς"], ["tau", "τ"], ["upsilon", "υ"], ["phi", "ϕ"],
  ["varphi", "φ"], ["chi", "χ"], ["psi", "ψ"], ["omega", "ω"], ["Gamma", "Γ"],
  ["Delta", "Δ"], ["Theta", "Θ"], ["Lambda", "Λ"], ["Xi", "Ξ"], ["Pi", "Π"],
  ["Sigma", "Σ"], ["Upsilon", "Υ"], ["Phi", "Φ"], ["Psi", "Ψ"], ["Omega", "Ω"],
  ["pm", "±"], ["mp", "∓"], ["times", "×"], ["cdot", "⋅"], ["div", "÷"],
  ["le", "≤"], ["leq", "≤"], ["ge", "≥"], ["geq", "≥"], ["neq", "≠"], ["ne", "≠"],
  ["approx", "≈"], ["sim", "∼"], ["equiv", "≡"], ["in", "∈"], ["notin", "∉"],
  ["subset", "⊂"], ["subseteq", "⊆"], ["supset", "⊃"], ["supseteq", "⊇"], ["to", "→"],
  ["rightarrow", "→"], ["leftarrow", "←"], ["leftrightarrow", "↔"], ["infty", "∞"],
  ["partial", "∂"], ["nabla", "∇"], ["forall", "∀"], ["exists", "∃"], ["therefore", "∴"],
  ["sum", "∑"], ["prod", "∏"], ["int", "∫"], ["oint", "∮"], ["ldots", "…"], ["cdots", "⋯"],
  ["langle", "⟨"], ["rangle", "⟩"], ["angle", "∠"], ["parallel", "∥"], ["perp", "⊥"],
]);

const SINGLE_COMMANDS = new Map([["\\", "\\"], ["%", "%"], ["_", "_"]]);

const TEXT_COMMANDS = new Map([
  ["sin", "sin"], ["cos", "cos"], ["tan", "tan"], ["cot", "cot"],
  ["sec", "sec"], ["csc", "csc"], ["log", "log"], ["ln", "ln"],
  ["exp", "exp"], ["lim", "lim"], ["max", "max"], ["min", "min"],
  ["sup", "sup"], ["inf", "inf"], ["det", "det"], ["Pr", "Pr"],
  ["gcd", "gcd"], ["quad", "  "], ["qquad", "    "], [",", " "],
  [";", " "], [":", " "], ["!", ""],
]);

const ACCENTS = new Map([
  ["hat", "^"], ["widehat", "^"], ["tilde", "~"], ["widetilde", "~"],
  ["vec", "→"], ["dot", "˙"], ["ddot", "¨"], ["breve", "˘"],
  ["check", "ˇ"], ["acute", "´"], ["grave", "`"], ["bar", "¯"],
]);

const NARY_COMMANDS = new Map([
  ["sum", "∑"], ["prod", "∏"], ["coprod", "∐"], ["int", "∫"], ["iint", "∬"],
  ["iiint", "∭"], ["oint", "∮"], ["bigcup", "⋃"], ["bigcap", "⋂"],
  ["bigsqcup", "⨆"], ["bigvee", "⋁"], ["bigwedge", "⋀"], ["bigoplus", "⨁"],
  ["bigotimes", "⨂"], ["bigodot", "⨀"], ["biguplus", "⨄"],
]);

const ENVIRONMENT_DELIMITERS = {
  matrix: null,
  array: null,
  aligned: null,
  gathered: null,
  smallmatrix: null,
  pmatrix: ["(", ")"],
  bmatrix: ["[", "]"],
  Bmatrix: ["{", "}"],
  vmatrix: ["|", "|"],
  Vmatrix: ["‖", "‖"],
  cases: ["{", ""],
  "cases*": ["{", ""],
};

function stripMathDelimiters(value) {
  return String(value ?? "")
    .trim()
    .replace(/^\\\(/u, "")
    .replace(/\\\)$/u, "")
    .replace(/^\$\$/u, "")
    .replace(/\$\$$/u, "")
    .replace(/^\$/u, "")
    .replace(/\$$/u, "")
    .trim();
}

function readBalanced(source, start) {
  let index = start;
  while (/\s/u.test(source[index] ?? "")) index += 1;
  if (source[index] !== "{") return { value: source[index] ?? "", next: index + 1 };
  const begin = index + 1;
  let depth = 1;
  index += 1;
  while (index < source.length) {
    if (source[index] === "\\") {
      index += 2;
      continue;
    }
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") {
      depth -= 1;
      if (depth === 0) return { value: source.slice(begin, index), next: index + 1 };
    }
    index += 1;
  }
  return { value: source.slice(begin), next: source.length };
}

function readCommand(source, start) {
  let index = start + 1;
  if (index >= source.length) return { command: "", next: index };
  if (!/[A-Za-z]/u.test(source[index])) return { command: source[index], next: index + 1 };
  const begin = index;
  while (index < source.length && /[A-Za-z]/u.test(source[index])) index += 1;
  return { command: source.slice(begin, index), next: index };
}

function readEnvironment(source, start) {
  const name = readBalanced(source, start);
  const environment = String(name.value ?? "").trim();
  const endToken = `\\end{${environment}}`;
  const end = source.indexOf(endToken, name.next);
  return {
    environment,
    body: source.slice(name.next, end < 0 ? source.length : end),
    next: end < 0 ? source.length : end + endToken.length,
  };
}

function splitEnvironmentRows(source) {
  const rows = [];
  let begin = 0;
  let depth = 0;
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (character === "{") depth += 1;
    else if (character === "}") depth = Math.max(0, depth - 1);
    else if (character === "\\" && source[index + 1] === "\\" && depth === 0) {
      rows.push(source.slice(begin, index));
      index += 1;
      begin = index + 1;
    }
  }
  rows.push(source.slice(begin));
  return rows.map((row) => {
    const cells = [];
    let cellBegin = 0;
    let cellDepth = 0;
    for (let index = 0; index < row.length; index += 1) {
      if (row[index] === "{") cellDepth += 1;
      else if (row[index] === "}") cellDepth = Math.max(0, cellDepth - 1);
      else if (row[index] === "&" && cellDepth === 0) {
        cells.push(row.slice(cellBegin, index));
        cellBegin = index + 1;
      }
    }
    cells.push(row.slice(cellBegin));
    return cells.map((cell) => cell.trim());
  }).filter((row) => row.some((cell) => cell.length > 0));
}

function delimiterText(value) {
  const text = String(value ?? "");
  if (text === ".") return "";
  if (text.startsWith("\\")) {
    const command = text.slice(1);
    return {
      langle: "⟨", rangle: "⟩", lbrace: "{", rbrace: "}",
      vert: "|", Vert: "‖", backslash: "\\", "|": "|", "{": "{", "}": "}",
    }[command] ?? text;
  }
  return text;
}

function readDelimiter(source, start) {
  let index = start;
  while (/\s/u.test(source[index] ?? "")) index += 1;
  if (source[index] === "\\") {
    const command = readCommand(source, index);
    return { text: delimiterText(`\\${command.command}`), next: command.next };
  }
  return { text: delimiterText(source[index] ?? ""), next: index + 1 };
}

function skipWhitespace(source, start) {
  let index = start;
  while (/\s/u.test(source[index] ?? "")) index += 1;
  return index;
}

function readNaryBody(source, start) {
  let index = skipWhitespace(source, start);
  if (index >= source.length || /[+,=;&)]/u.test(source[index])) return { value: "", next: index };
  if (source[index] === "{") {
    const group = readBalanced(source, index);
    return { value: group.value, next: group.next };
  }
  if (source[index] === "\\") {
    const command = readCommand(source, index);
    return { value: source.slice(index, command.next), next: command.next };
  }
  let next = index + 1;
  while (source[next] === "^" || source[next] === "_") {
    const argument = readBalanced(source, next + 1);
    next = argument.next;
  }
  return { value: source.slice(index, next), next };
}

function naryXml(command, source, start, style = {}) {
  let index = skipWhitespace(source, start);
  let sub = null;
  let sup = null;
  while (index < source.length) {
    if (source[index] === "\\") {
      const modifier = readCommand(source, index);
      if (modifier.command === "limits" || modifier.command === "nolimits") {
        index = skipWhitespace(source, modifier.next);
        continue;
      }
    }
    if (source[index] !== "^" && source[index] !== "_") break;
    const kind = source[index] === "^" ? "sup" : "sub";
    const argument = readBalanced(source, index + 1);
    const parsed = expressionXml(argument.value, style);
    if (kind === "sup") sup = parsed;
    else sub = parsed;
    index = skipWhitespace(source, argument.next);
  }
  const body = readNaryBody(source, index);
  const parsedBody = body.value ? expressionXml(body.value, style) : { xml: runXml("", style), unsupported: [] };
  const properties = `<m:naryPr><m:chr m:val="${escapeXml(NARY_COMMANDS.get(command))}"/><m:limLoc m:val="subSup"/><m:grow m:val="1"/></m:naryPr>`;
  const xml = `<m:nary>${properties}${sub ? `<m:sub>${sub.xml}</m:sub>` : ""}${sup ? `<m:sup>${sup.xml}</m:sup>` : ""}<m:e>${parsedBody.xml}</m:e></m:nary>`;
  return {
    xml,
    next: body.next,
    unsupported: [...(sub?.unsupported ?? []), ...(sup?.unsupported ?? []), ...(parsedBody.unsupported ?? [])],
  };
}

function runXml(text, style = {}) {
  const fontFamily = escapeXml(style.fontFamily ?? "Cambria Math");
  const fontSize = style.fontSize ? ` sz="${Math.round(Number(style.fontSize) * 72 / 96 * 100)}"` : "";
  const color = style.color ? `<a:solidFill><a:srgbClr val="${escapeXml(String(style.color).replace(/^#/u, "").slice(0, 6))}"/></a:solidFill>` : "";
  return `<m:r><a:rPr lang="zh-CN"${fontSize}><a:latin typeface="${fontFamily}"/><a:ea typeface="${fontFamily}"/>${color}</a:rPr><m:t>${escapeXml(text)}</m:t></m:r>`;
}

function matrixXml(environment, body, style = {}) {
  const rows = splitEnvironmentRows(body);
  const unsupported = [];
  const rowXml = rows.map((row) => `<m:mr>${row.map((cell) => {
    const parsed = expressionXml(cell || "", style);
    unsupported.push(...parsed.unsupported);
    return `<m:mc><m:mcPr/><m:e>${parsed.xml || runXml("", style)}</m:e></m:mc>`;
  }).join("")}</m:mr>`).join("");
  const matrix = `<m:m><m:mPr/>${rowXml || `<m:mr><m:mc><m:mcPr/><m:e>${runXml("", style)}</m:e></m:mc></m:mr>`}</m:m>`;
  const delimiters = ENVIRONMENT_DELIMITERS[environment];
  if (!delimiters) return { xml: matrix, unsupported: [...new Set(unsupported)] };
  const [begin, end] = delimiters;
  return { xml: `<m:d><m:dPr><m:begChr m:val="${escapeXml(begin)}"/><m:endChr m:val="${escapeXml(end)}"/><m:grow m:val="1"/></m:dPr><m:e>${matrix}</m:e></m:d>`, unsupported: [...new Set(unsupported)] };
}

function binomialXml(numerator, denominator, style = {}) {
  const num = expressionXml(numerator, style);
  const den = expressionXml(denominator, style);
  return { xml: `<m:f><m:fPr><m:type m:val="noBar"/></m:fPr><m:num>${num.xml}</m:num><m:den>${den.xml}</m:den></m:f>`, unsupported: [...new Set([...num.unsupported, ...den.unsupported])] };
}

function accentXml(character, argument, style = {}) {
  const body = expressionXml(argument, style);
  return `<m:acc><m:accPr><m:chr m:val="${escapeXml(character)}"/></m:accPr><m:e>${body.xml}</m:e></m:acc>`;
}

function functionXml(name, style = {}) {
  return `<m:func><m:funcPr/><m:fName>${runXml(name, style)}</m:fName><m:e>${runXml("", style)}</m:e></m:func>`;
}

function expressionXml(source, style = {}) {
  const input = stripMathDelimiters(source);
  const nodes = [];
  const unsupported = [];
  let index = 0;

  const appendScript = (kind, argument, sourceCommand = kind) => {
    const previous = nodes.pop() ?? { xml: runXml("", style) };
    const script = expressionXml(argument, style);
    const base = previous.base ?? previous.xml;
    const sub = previous.sub ?? (kind === "sub" ? script.xml : null);
    const sup = previous.sup ?? (kind === "sup" ? script.xml : null);
    let xml;
    if (sub && sup) xml = `<m:sSubSup><m:e>${base}</m:e><m:sub>${sub}</m:sub><m:sup>${sup}</m:sup></m:sSubSup>`;
    else if (sub) xml = `<m:sSub><m:e>${base}</m:e><m:sub>${sub}</m:sub></m:sSub>`;
    else xml = `<m:sSup><m:e>${base}</m:e><m:sup>${sup}</m:sup></m:sSup>`;
    nodes.push({ xml, base, sub, sup, sourceCommand });
    unsupported.push(...script.unsupported);
  };

  const appendText = (text) => {
    if (text) nodes.push({ xml: runXml(text, style) });
  };

  while (index < input.length) {
    const character = input[index];
    if (/\s/u.test(character)) {
      let end = index + 1;
      while (end < input.length && /\s/u.test(input[end])) end += 1;
      appendText(" ");
      index = end;
      continue;
    }
    if (character === "^") {
      const argument = readBalanced(input, index + 1);
      appendScript("sup", argument.value);
      index = argument.next;
      continue;
    }
    if (character === "_") {
      const argument = readBalanced(input, index + 1);
      appendScript("sub", argument.value);
      index = argument.next;
      continue;
    }
    if (character === "{") {
      const argument = readBalanced(input, index);
      const nested = expressionXml(argument.value, style);
      nodes.push({ xml: nested.xml });
      unsupported.push(...nested.unsupported);
      index = argument.next;
      continue;
    }
    if (character !== "\\") {
      appendText(character);
      index += 1;
      continue;
    }

    const { command, next } = readCommand(input, index);
    index = next;
    if (command === "left" || command === "right" || command === "middle") {
      const delimiter = readDelimiter(input, index);
      appendText(delimiter.text);
      index = delimiter.next;
      continue;
    }
    if (["displaystyle", "textstyle", "scriptstyle", "scriptscriptstyle", "limits", "nolimits", "allowbreak"].includes(command)) {
      continue;
    }
    if (command === "begin") {
      const environment = readEnvironment(input, index);
      if (!Object.hasOwn(ENVIRONMENT_DELIMITERS, environment.environment)) {
        unsupported.push(`begin:${environment.environment}`);
        appendText(`\\begin{${environment.environment}}`);
      } else {
        let nextIndex = environment.next;
        if (environment.environment === "array") nextIndex = readBalanced(input, nextIndex).next;
        const matrix = matrixXml(environment.environment, environment.body, style);
        nodes.push({ xml: matrix.xml });
        unsupported.push(...matrix.unsupported);
        index = Math.max(nextIndex, environment.next);
        continue;
      }
      index = environment.next;
      continue;
    }
    if (command === "binom") {
      const numerator = readBalanced(input, index);
      const denominator = readBalanced(input, numerator.next);
      const binomial = binomialXml(numerator.value, denominator.value, style);
      nodes.push({ xml: `<m:d><m:dPr><m:begChr m:val="("/><m:endChr m:val=")"/><m:grow m:val="1"/></m:dPr><m:e>${binomial.xml}</m:e></m:d>` });
      unsupported.push(...binomial.unsupported);
      index = denominator.next;
      continue;
    }
    if (command === "overset" || command === "underset") {
      const annotation = readBalanced(input, index);
      const argument = readBalanced(input, annotation.next);
      const annotationXml = expressionXml(annotation.value, style);
      const argumentXml = expressionXml(argument.value, style);
      const kind = command === "overset" ? "limUpp" : "limLow";
      nodes.push({ xml: `<m:${kind}><m:e>${argumentXml.xml}</m:e><m:lim>${annotationXml.xml}</m:lim></m:${kind}>` });
      unsupported.push(...annotationXml.unsupported, ...argumentXml.unsupported);
      index = argument.next;
      continue;
    }
    if (ACCENTS.has(command)) {
      const argument = readBalanced(input, index);
      const body = expressionXml(argument.value, style);
      nodes.push({ xml: accentXml(ACCENTS.get(command), argument.value, style) });
      unsupported.push(...body.unsupported);
      index = argument.next;
      continue;
    }
    if (command === "frac") {
      const numerator = readBalanced(input, index);
      const denominator = readBalanced(input, numerator.next);
      const num = expressionXml(numerator.value, style);
      const den = expressionXml(denominator.value, style);
      nodes.push({ xml: `<m:f><m:fPr/><m:num>${num.xml}</m:num><m:den>${den.xml}</m:den></m:f>` });
      unsupported.push(...num.unsupported, ...den.unsupported);
      index = denominator.next;
      continue;
    }
    if (command === "sqrt") {
      let degree = null;
      while (/\s/u.test(input[index] ?? "")) index += 1;
      if (input[index] === "[") {
        const end = input.indexOf("]", index + 1);
        degree = expressionXml(end < 0 ? input.slice(index + 1) : input.slice(index + 1, end), style);
        index = end < 0 ? input.length : end + 1;
      }
      const radicand = readBalanced(input, index);
      const body = expressionXml(radicand.value, style);
      const degreeXml = degree ? `<m:deg>${degree.xml}</m:deg>` : "<m:deg/>";
      nodes.push({ xml: `<m:rad><m:radPr/>${degreeXml}<m:e>${body.xml}</m:e></m:rad>` });
      unsupported.push(...(degree?.unsupported ?? []), ...body.unsupported);
      index = radicand.next;
      continue;
    }
    if (NARY_COMMANDS.has(command)) {
      const nary = naryXml(command, input, index, style);
      nodes.push({ xml: nary.xml });
      unsupported.push(...nary.unsupported);
      index = nary.next;
      continue;
    }
    if (command === "operatorname") {
      const argument = readBalanced(input, index);
      nodes.push({ xml: functionXml(argument.value.replaceAll("\\", ""), style) });
      index = argument.next;
      continue;
    }
    if (["text", "mathrm", "mathbf", "mathit"].includes(command)) {
      const argument = readBalanced(input, index);
      appendText(argument.value.replaceAll("\\", ""));
      index = argument.next;
      continue;
    }
    if (TEXT_COMMANDS.has(command)) {
      appendText(TEXT_COMMANDS.get(command));
      continue;
    }
    if (["overline", "underline", "overbrace", "underbrace"].includes(command)) {
      const argument = readBalanced(input, index);
      const body = expressionXml(argument.value, style);
      if (command === "overbrace" || command === "underbrace") {
        const position = command === "underbrace" ? "bot" : "top";
        nodes.push({ xml: `<m:groupChr><m:groupChrPr><m:chr m:val="{"/><m:pos m:val="${position}"/><m:vertJc m:val="bot"/></m:groupChrPr><m:e>${body.xml}</m:e></m:groupChr>` });
      } else {
        const position = command === "underline" ? "bot" : "top";
        nodes.push({ xml: `<m:bar><m:barPr><m:pos m:val="${position}"/></m:barPr><m:e>${body.xml}</m:e></m:bar>` });
      }
      unsupported.push(...body.unsupported);
      index = argument.next;
      continue;
    }
    if (COMMANDS.has(command)) {
      appendText(COMMANDS.get(command));
      continue;
    }
    if (SINGLE_COMMANDS.has(`\\${command}`)) {
      appendText(SINGLE_COMMANDS.get(`\\${command}`));
      continue;
    }
    unsupported.push(command);
    appendText(`\\${command}`);
  }
  return { xml: nodes.map((node) => node.xml).join(""), unsupported: [...new Set(unsupported)] };
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
}

function replaceMacro(text, name, replacement, argumentCount = 1) {
  const argumentsPattern = argumentCount === 2 ? "\\{([^{}]*)\\}\\s*\\{([^{}]*)\\}" : "\\{([^{}]*)\\}";
  const pattern = new RegExp(`\\\\${escapeRegExp(name)}\\s*${argumentsPattern}`, "gu");
  let current = text;
  let previous = null;
  while (current !== previous) {
    previous = current;
    current = current.replace(pattern, replacement);
  }
  return current;
}

function rawFormulaText(value) {
  let text = String(value ?? "")
    .replace(/<[^>]+>/gu, "")
    .replace(/\s+/gu, " ")
    .trim();
  text = replaceMacro(text, "text", "$1");
  text = replaceMacro(text, "frac", "($1)/($2)", 2);
  text = replaceMacro(text, "sqrt", "√($1)");
  text = replaceMacro(text, "binom", "C($1,$2)", 2);
  text = replaceMacro(text, "overset", "$2", 2);
  text = replaceMacro(text, "underset", "$2", 2);
  text = replaceMacro(text, "overbrace", "$1");
  text = replaceMacro(text, "underbrace", "$1");
  text = text
    .replace(/\\left\b|\\right\b|\\middle\b|\\displaystyle\b|\\textstyle\b|\\scriptstyle\b|\\scriptscriptstyle\b|\\limits\b|\\nolimits\b|\\allowbreak\b/gu, "")
    .replace(/\\(?:quad|qquad|,|;|:|!)/gu, " ");
  for (const [command, symbol] of COMMANDS.entries()) {
    text = text.replace(new RegExp(`\\\\${escapeRegExp(command)}\\b`, "gu"), symbol);
  }
  for (const [command, symbol] of TEXT_COMMANDS.entries()) {
    text = text.replace(new RegExp(`\\\\${escapeRegExp(command)}\\b`, "gu"), symbol);
  }
  return text
    .replace(/[{}]/gu, "")
    .replace(/\s+/gu, " ")
    .trim();
}

export function latexToOmml(latex, style = {}) {
  const parsed = expressionXml(latex, style);
  return {
    omml: `<m:oMathPara xmlns:m="${OMML_NS}"><m:oMath>${parsed.xml || runXml("", style)}</m:oMath></m:oMathPara>`,
    unsupported: parsed.unsupported,
  };
}

export function normalizeFormula(formula = {}, style = {}) {
  const source = typeof formula === "string" ? { latex: formula } : formula;
  const latex = source?.latex ?? source?.text ?? "";
  const raw = String(source?.omml ?? "").trim();
  const omml = raw
    ? (raw.includes("<m:oMathPara") ? raw : `<m:oMathPara xmlns:m="${OMML_NS}">${raw}</m:oMathPara>`)
    : latexToOmml(latex, style).omml;
  const parsed = raw ? { unsupported: [] } : latexToOmml(latex, style);
  return {
    latex: String(latex),
    omml,
    fallbackText: String(source?.fallbackText ?? rawFormulaText(source?.text ?? latex)),
    ...(parsed.unsupported.length > 0 ? { unsupportedCommands: parsed.unsupported } : {}),
  };
}

export function formulaPlainText(formula = {}) {
  return String(formula?.fallbackText ?? formula?.text ?? formula?.latex ?? rawFormulaText(formula?.omml ?? ""));
}

export function formulaOmmlXml(formula = {}, style = {}) {
  return normalizeFormula(formula, style).omml;
}
