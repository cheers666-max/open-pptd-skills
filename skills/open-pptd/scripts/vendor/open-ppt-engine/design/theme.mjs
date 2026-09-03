export const defaultTheme = Object.freeze({
  colors: {
    ink: "#1E1E1E",
    muted: "#6E6B65",
    paper: "#F7F5F0",
    white: "#FFFFFF",
    line: "#D3CEC3",
    accent: "#B32635",
    accentDark: "#8E1B27",
    slate: "#2A2B2E",
  },
  fonts: {
    heading: "Aptos Display",
    body: "Aptos",
    cjk: "Microsoft YaHei",
    fallbacks: {
      latin: ["Arial Unicode MS", "Verdana"],
      cjk: ["Noto Sans SC", "Arial Unicode MS", "Heiti SC", "Songti SC"],
    },
  },
  type: {
    deckTitle: 50,
    slideTitle: 35,
    subheading: 24,
    body: 16,
    caption: 12,
  },
  spacing: {
    outer: 64,
    gutter: 28,
    section: 24,
  },
  radii: {
    sm: 8,
    md: 12,
    lg: 16,
    pill: 9999,
  },
  effects: {},
});

/**
 * A font-name-only preset for deployments that want to avoid proprietary
 * default font families. The actual font files still belong in `fontAssets`
 * and must pass the embedding/license checks before production publishing.
 */
export const openSourceTheme = Object.freeze({
  ...defaultTheme,
  fonts: {
    heading: "Noto Sans SC",
    body: "Noto Sans SC",
    cjk: "Noto Sans SC",
    fallbacks: {
      latin: ["Noto Sans SC", "DejaVu Sans", "Liberation Sans"],
      cjk: ["Noto Sans SC", "Noto Serif CJK SC"],
    },
  },
});

export function resolveTheme(theme = {}) {
  return {
    ...defaultTheme,
    ...theme,
    colors: { ...defaultTheme.colors, ...(theme.colors ?? {}) },
    fonts: {
      ...defaultTheme.fonts,
      ...(theme.fonts ?? {}),
      fallbacks: {
        ...defaultTheme.fonts.fallbacks,
        ...(theme.fonts?.fallbacks ?? {}),
        latin: [...(defaultTheme.fonts.fallbacks.latin ?? []), ...(theme.fonts?.fallbacks?.latin ?? [])].filter((value, index, values) => values.indexOf(value) === index),
        cjk: [...(defaultTheme.fonts.fallbacks.cjk ?? []), ...(theme.fonts?.fallbacks?.cjk ?? [])].filter((value, index, values) => values.indexOf(value) === index),
      },
    },
    type: { ...defaultTheme.type, ...(theme.type ?? {}) },
    spacing: { ...defaultTheme.spacing, ...(theme.spacing ?? {}) },
    radii: { ...defaultTheme.radii, ...(theme.radii ?? {}) },
    effects: { ...defaultTheme.effects, ...(theme.effects ?? {}) },
  };
}
