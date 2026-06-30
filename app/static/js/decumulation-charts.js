const DECUM_PALETTE = {
  "2": "#5aa9c9",
  "3": "#7c9a93",
  "4": "#6fb088",
  "5": "#c8932b",
  "6": "#c4795a",
};
const DECUM_EXTRA_COLORS = ["#a98cc8", "#cfa15a", "#d17ba0", "#9c8a6a"];

const DECUM_TYPE_COLORS = {
  ISA: "#5aa9c9",
  SIPP: "#c8932b",
  PENSION_DC: "#cfa15a",
  PENSION_DB: "#a98cc8",
  GIA: "#c4795a",
  CASH: "#7c9a93",
  OTHER: "#9c8a6a",
};
const STATE_PENSION_COLOR = "#6fb088";

function colorForType(type, fallbackIndex) {
  if (DECUM_TYPE_COLORS[type]) return DECUM_TYPE_COLORS[type];
  return DECUM_EXTRA_COLORS[fallbackIndex % DECUM_EXTRA_COLORS.length];
}

function fmtDecum(value, symbol) {
  if (value === null || value === undefined) return "—";
  return symbol + Math.round(value).toLocaleString("en-GB");
}

function cssVarDecum(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function colorForRate(rate, index) {
  const key = String(rate);
  if (DECUM_PALETTE[key]) return DECUM_PALETTE[key];
  return DECUM_EXTRA_COLORS[index % DECUM_EXTRA_COLORS.length];
}

function makeVerticalMarkerPlugin(id, ages, targetAge, color, label) {
  const index = ages.indexOf(targetAge);
  return {
    id,
    afterDraw(chart) {
      if (index < 0) return;
      const xScale = chart.scales.x;
      const { ctx, chartArea } = chart;
      const x = xScale.getPixelForValue(index);
      ctx.save();
      ctx.strokeStyle = color;
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.font = "11px Inter, sans-serif";
      ctx.fillStyle = color;
      ctx.setLineDash([]);
      ctx.fillText(label, x + 4, chartArea.top + 12);
      ctx.restore();
    },
  };
}

async function loadDecumulationCharts() {
  const balanceCanvas = document.getElementById("decumChart");
  if (!balanceCanvas) return;

  const res = await fetch("/decumulation/api/projection" + window.location.search);
  const data = await res.json();
  const symbol = data.currency_symbol || "£";

  const gridColor = cssVarDecum("--line-soft") || "rgba(150,150,150,0.15)";
  const tickColor = cssVarDecum("--paper-dim") || "#888";
  const markerColor = cssVarDecum("--brass") || "#c8932b";

  Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
  Chart.defaults.color = tickColor;

  const statePensionMarker = makeVerticalMarkerPlugin(
    "statePensionMarker", data.ages, data.state_pension_age, markerColor, "State Pension starts"
  );

  // --- Chart 1: portfolio value by withdrawal rate ---
  const rateKeys = Object.keys(data.scenarios);
  const balanceDatasets = rateKeys.map((rateKey, i) => {
    const isYourRate = parseFloat(rateKey) === parseFloat(data.your_rate);
    const color = colorForRate(rateKey, i);
    return {
      label: isYourRate ? `${rateKey}% (your rate)` : `${rateKey}%`,
      data: data.scenarios[rateKey],
      borderColor: color,
      backgroundColor: "transparent",
      pointRadius: 0,
      borderWidth: isYourRate ? 2.5 : 1.5,
      borderDash: isYourRate ? [2, 2] : [],
      tension: 0.1,
    };
  });

  new Chart(balanceCanvas, {
    type: "line",
    data: { labels: data.ages, datasets: balanceDatasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { grid: { color: gridColor }, title: { display: true, text: "Age" }, ticks: { autoSkip: true, maxRotation: 0 } },
        y: { grid: { color: gridColor }, ticks: { callback: (v) => fmtDecum(v, symbol) } },
      },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10 } },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${fmtDecum(ctx.parsed.y, symbol)}` } },
      },
    },
    plugins: [statePensionMarker],
  });

  // --- Chart 2: withdrawal sources, stacked bar, at the configured rate ---
  const stackCanvas = document.getElementById("decumStackChart");
  if (stackCanvas && data.detail) {
    const pensionUnlockedMarker = makeVerticalMarkerPlugin(
      "pensionUnlockedMarker", data.ages, data.pension_access_age, "#6fb088", "Pension unlocked"
    );

    new Chart(stackCanvas, {
      type: "bar",
      data: {
        labels: data.ages,
        datasets: [
          {
            label: "Tax-free (ISA/other)",
            data: data.detail.tax_free_withdrawal,
            backgroundColor: "#5aa9c9",
            stack: "income",
          },
          {
            label: "Taxable (SIPP/pension)",
            data: data.detail.taxable_withdrawal,
            backgroundColor: "#c8932b",
            stack: "income",
          },
          {
            label: "State Pension",
            data: data.detail.state_pension,
            backgroundColor: "#6fb088",
            stack: "income",
          },
          {
            label: "Shortfall (unmet)",
            data: data.detail.bridge_shortfall,
            backgroundColor: "#c4795a",
            stack: "income",
          },
        ],
      },
      options: {
        responsive: true,
      maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { stacked: true, grid: { color: gridColor }, title: { display: true, text: "Age" }, ticks: { autoSkip: true, maxRotation: 0 } },
          y: {
            stacked: true,
            grid: { color: gridColor },
            ticks: { callback: (v) => fmtDecum(v, symbol) },
          },
        },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10 } },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${fmtDecum(ctx.parsed.y, symbol)}`,
              footer: (items) => {
                const i = items[0].dataIndex;
                if (data.detail.pension_locked[i]) {
                  return "SIPP/pension locked this year";
                }
                return "";
              },
            },
          },
        },
      },
      plugins: [pensionUnlockedMarker, statePensionMarker],
    });
  }

  // --- Chart 3: Die with Zero — withdrawal sources by account TYPE, at the solved rate ---
  const dwzCanvas = document.getElementById("decumDieWithZeroChart");
  if (dwzCanvas && data.die_with_zero) {
    const dwz = data.die_with_zero;
    const typeKeys = Object.keys(dwz.by_type);
    const dwzDatasets = typeKeys.map((type, i) => ({
      label: type,
      data: dwz.by_type[type],
      backgroundColor: colorForType(type, i),
      stack: "income",
    }));
    dwzDatasets.push({
      label: "State Pension",
      data: dwz.state_pension,
      backgroundColor: STATE_PENSION_COLOR,
      stack: "income",
    });

    const dwzPensionUnlockedMarker = makeVerticalMarkerPlugin(
      "dwzPensionUnlockedMarker", data.ages, data.pension_access_age, "#6fb088", "Pension unlocked"
    );
    const dwzStatePensionMarker = makeVerticalMarkerPlugin(
      "dwzStatePensionMarker", data.ages, data.state_pension_age, markerColor, "State Pension starts"
    );

    new Chart(dwzCanvas, {
      type: "bar",
      data: { labels: data.ages, datasets: dwzDatasets },
      options: {
        responsive: true,
      maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { stacked: true, grid: { color: gridColor }, title: { display: true, text: "Age" }, ticks: { autoSkip: true, maxRotation: 0 } },
          y: {
            stacked: true,
            grid: { color: gridColor },
            ticks: { callback: (v) => fmtDecum(v, symbol) },
          },
        },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10 } },
          tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${fmtDecum(ctx.parsed.y, symbol)}` } },
        },
      },
      plugins: [dwzPensionUnlockedMarker, dwzStatePensionMarker],
    });
  }
}

function setupDecumViewOptions() {
  const strategySelect = document.getElementById("decum-strategy-select");
  const indexField = document.querySelector("[data-index-thresholds-field]");
  if (!strategySelect || !indexField) return;

  function sync() {
    const isFixed = strategySelect.value === "fixed";
    indexField.style.display = isFixed ? "none" : "";
  }

  strategySelect.addEventListener("change", sync);
  sync();
}

document.addEventListener("DOMContentLoaded", () => {
  loadDecumulationCharts();
  setupDecumViewOptions();
});
