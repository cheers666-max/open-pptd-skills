/**
 * Chart data contracts shared by model consumers, renderers and QA.
 *
 * PowerPoint chart XML is permissive enough to accept malformed caches. That
 * is dangerous for a generation system: a length mismatch can produce a deck
 * that opens successfully while displaying the wrong categories or silently
 * converting invalid values to zero. Keep this contract close to the IR so
 * every renderer makes the same decision.
 */
export const CHART_TYPES = Object.freeze(new Set([
  "bar", "line", "area", "radar", "scatter", "pie", "donut", "doughnut",
]));

const PIE_TYPES = new Set(["pie", "donut", "doughnut"]);

function numericValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function issue(code, detail = {}) {
  return { code, ...detail };
}

/**
 * Return blocking data-contract violations for one chart element.
 * Chart type support is checked separately because a renderer may expose a
 * different capability set; these issues describe malformed chart data only.
 */
export function inspectChartData(element = {}) {
  const chartType = String(element.chartType ?? "bar");
  const series = Array.isArray(element.series) ? element.series : [];
  const issues = [];
  if (series.length === 0) issues.push(issue("chart-empty-series"));

  const checkValues = (values, seriesIndex, axis) => {
    if (!Array.isArray(values)) {
      issues.push(issue("chart-values-not-array", { seriesIndex, axis }));
      return;
    }
    const invalidIndex = values.findIndex((value) => numericValue(value) === null);
    if (invalidIndex >= 0) {
      issues.push(issue("chart-non-numeric-value", {
        seriesIndex,
        axis,
        pointIndex: invalidIndex,
        value: values[invalidIndex],
      }));
    }
  };

  if (chartType === "scatter") {
    const fallbackX = Array.isArray(element.xValues) && element.xValues.length
      ? element.xValues
      : (Array.isArray(element.categories) ? element.categories : []);
    if (fallbackX.length === 0 && series.length > 0) issues.push(issue("chart-scatter-x-values-missing"));
    for (const [seriesIndex, item] of series.entries()) {
      const values = item?.values;
      const xValues = Array.isArray(item?.xValues) && item.xValues.length ? item.xValues : fallbackX;
      checkValues(xValues, seriesIndex, "x");
      checkValues(values, seriesIndex, "y");
      if (Array.isArray(xValues) && Array.isArray(values) && xValues.length !== values.length) {
        issues.push(issue("chart-scatter-length-mismatch", {
          seriesIndex,
          xLength: xValues.length,
          yLength: values.length,
        }));
      }
    }
    return issues;
  }

  const categories = Array.isArray(element.categories) ? element.categories : [];
  if (categories.length === 0 && series.length > 0) issues.push(issue("chart-categories-missing"));
  for (const [seriesIndex, item] of series.entries()) {
    const values = item?.values;
    checkValues(values, seriesIndex, "y");
    if (Array.isArray(values) && values.length !== categories.length) {
      issues.push(issue("chart-data-length-mismatch", {
        seriesIndex,
        categoryLength: categories.length,
        valueLength: values.length,
      }));
    }
  }
  if (PIE_TYPES.has(chartType) && series.length > 1) {
    issues.push(issue("chart-pie-multiple-series", { seriesCount: series.length }));
  }
  return issues;
}

export function assertChartData(element = {}) {
  const chartType = String(element.chartType ?? "bar");
  if (!CHART_TYPES.has(chartType)) {
    const error = new Error(`Unsupported chart type: ${chartType}`);
    error.code = "unsupported-chart-type";
    error.chartType = chartType;
    throw error;
  }
  const issues = inspectChartData(element);
  if (issues.length > 0) {
    const error = new Error(`Chart data contract failed: ${issues.map((item) => item.code).join(", ")}`);
    error.code = "chart-data-contract-failed";
    error.chartType = chartType;
    error.issues = issues;
    throw error;
  }
  return element;
}
