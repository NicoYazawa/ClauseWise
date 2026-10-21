/**
 * Chart color palette: read from CSS variables so it shares the same source as the
 * site tokens (echarts needs concrete color values). Rules: one hue per chart, accent
 * for the primary data element and neutral for the rest; grid lines extremely faint;
 * line series use straight segments with no point markers; area fill at most 14%.
 */
function token(name: string, fallback: string): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return raw ? `rgb(${raw})` : fallback
}

export interface ChartTokens {
  accent: string
  neutral: string
  pale: string
  grid: string
  axis: string
  text: string
  negative: string
  warning: string
  positive: string
  surface: string
}

export function chartTokens(): ChartTokens {
  return {
    accent: token('--c-accent', '#0f766e'),
    neutral: token('--c-chart-2', '#6b7280'),
    pale: token('--c-chart-3', '#8fd0c6'),
    grid: token('--c-rule', '#f2f2f2'),
    axis: token('--c-muted', '#5f6672'),
    text: token('--c-text', '#111827'),
    negative: '#c4242a',
    warning: '#b45309',
    positive: '#247b50',
    surface: '#ffffff',
  }
}

/** Common chart base: no y-axis line, horizontal and extremely faint grid lines, axis font no larger than data */
export function chartBase(t: ChartTokens) {
  return {
    textStyle: { fontFamily: 'inherit', color: t.axis, fontSize: 12 },
    grid: { left: 44, right: 16, top: 20, bottom: 28, containLabel: false },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: t.surface,
      borderColor: '#e5e7eb',
      borderWidth: 1,
      textStyle: { color: t.text, fontSize: 12 },
      // taste-skill-ignore: floating tooltips are allowed to have a shadow
      extraCssText: 'box-shadow: 0 8px 24px -8px rgba(15,23,42,.16); border-radius: 8px;',
    },
  }
}
