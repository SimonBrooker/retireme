const isMobile = window.matchMedia("(max-width: 768px)").matches;

const PALETTE = [
  "#c8932b", // brass/amber
  "#6fb088", // moss green
  "#c4795a", // rust
  "#5aa9c9", // steel blue
  "#a98cc8", // plum
  "#cfa15a", // sand
  "#7c9a93", // sage
  "#d17ba0", // dusty rose
];
const UNALLOCATED_COLOR = "#9aa4b2";

let CURRENCY_SYMBOL = "£";

function fmtMoney(value) {
  if (value === null || value === undefined) return "—";
  return CURRENCY_SYMBOL + Math.round(value).toLocaleString("en-GB");
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

async function loadDashboardCharts() {
  const res = await fetch("/api/projection" + window.location.search);
  const data = await res.json();

  CURRENCY_SYMBOL = data.currency_symbol || "£";

  const gridColor = cssVar("--line-soft") || "rgba(150,150,150,0.15)";
  const tickColor = cssVar("--paper-dim") || "#888";
  const todayColor = cssVar("--paper-dim") || "#888";
  const retirementColor = cssVar("--brass") || "#c8932b";
  const targetIncomeColor = cssVar("--moss") || "#6fb088";

  Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
  Chart.defaults.color = tickColor;

  const todayIndex = data.ages.indexOf(data.current_age);
  const retirementIndex = data.ages.indexOf(data.retirement_age);
  const targetIncomeIndex =
    data.target_income_age !== null && data.target_income_age !== undefined
      ? data.ages.indexOf(data.target_income_age)
      : -1;

  const markerLinesPlugin = {
    id: "markerLines",
    afterDraw(chart) {
      const xScale = chart.scales.x;
      const { ctx, chartArea } = chart;
      const draw = (index, color, label, labelOffset) => {
        if (index < 0) return;
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
        ctx.fillText(label, x + 4, chartArea.top + labelOffset);
        ctx.restore();
      };
      draw(todayIndex, todayColor, "today", 12);
      draw(retirementIndex, retirementColor, "retirement", 24);
      draw(targetIncomeIndex, targetIncomeColor, "income goal reached", 36);
    },
  };

  // --- Composition chart: one stacked area per account ---
  const accountDatasets = data.accounts.map((acc, i) => {
    const color = PALETTE[i % PALETTE.length];
    return {
      label: acc.name,
      data: acc.balances,
      borderColor: color,
      backgroundColor: color + "4d",
      fill: true,
      stack: "networth",
      spanGaps: true,
      tension: 0.15,
      borderWidth: 1.5,
      pointRadius: acc.is_actual.map((a) => (a ? 3 : 0)),
      pointBackgroundColor: color,
      pointBorderColor: color,
      _meta: acc, // stash growth/contribution/is_actual for the tooltip callback
    };
  });

  const hasUnallocated = data.unallocated_inheritance.some((v) => v);
  if (hasUnallocated) {
    accountDatasets.push({
      label: "Unallocated inheritance",
      data: data.unallocated_inheritance,
      borderColor: UNALLOCATED_COLOR,
      backgroundColor: UNALLOCATED_COLOR + "4d",
      fill: true,
      stack: "networth",
      spanGaps: true,
      borderWidth: 1.5,
      pointRadius: 0,
      _meta: null,
    });
  }

  function tooltipLines(ctx) {
    const meta = ctx.dataset._meta;
    const i = ctx.dataIndex;
    const value = ctx.parsed.y;
    if (!meta) return `${ctx.dataset.label}: ${fmtMoney(value)}`;
    if (meta.is_actual[i]) {
      return `${ctx.dataset.label}: ${fmtMoney(value)} (actual recorded figure)`;
    }
    const growth = meta.growth[i];
    const contribution = meta.contribution[i];
    if (growth === null && contribution === null) {
      return `${ctx.dataset.label}: ${fmtMoney(value)}`;
    }
    return [
      `${ctx.dataset.label}: ${fmtMoney(value)}`,
      `  growth +${fmtMoney(growth)} · contribution +${fmtMoney(contribution)}`,
    ];
  }

  function compositionTitle(items) {
    if (!items.length) return "";
    const idx = items[0].dataIndex;
    const chart = items[0].chart;

    let anyHidden = false;
    for (let i = 0; i < chart.data.datasets.length; i++) {
      if (!chart.isDatasetVisible(i)) {
        anyHidden = true;
        break;
      }
    }

    if (!anyHidden) {
      return `Age ${data.ages[idx]} · Total net worth ${fmtMoney(data.total_net_worth[idx])}`;
    }

    let selectedTotal = 0;
    for (let i = 0; i < chart.data.datasets.length; i++) {
      if (chart.isDatasetVisible(i)) {
        const v = chart.data.datasets[i].data[idx];
        if (typeof v === "number") selectedTotal += v;
      }
    }
    return `Age ${data.ages[idx]} · Selected net worth ${fmtMoney(selectedTotal)}`;
  }

  new Chart(document.getElementById("compositionChart"), {
    type: "line",
    data: { labels: data.ages, datasets: accountDatasets },
    options: {
      responsive: true,
      maintainAspectRatio: !isMobile,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { grid: { color: gridColor }, title: { display: true, text: "Age" }, ticks: { autoSkip: true, maxRotation: 0 } },
        y: {
          stacked: true,
          grid: { color: gridColor },
          ticks: { callback: (v) => fmtMoney(v) },
        },
      },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10 } },
        tooltip: { callbacks: { title: compositionTitle, label: tooltipLines } },
      },
    },
    plugins: [markerLinesPlugin],
  });

  // --- Withdrawal capacity chart ---
  const withdrawalDatasets = [
    {
      label: "Annual withdrawal capacity",
      data: data.withdrawal_capacity,
      borderColor: retirementColor,
      backgroundColor: "transparent",
      pointRadius: 0,
      borderWidth: 2,
      tension: 0.15,
    },
  ];
  if (data.annual_expenses_target) {
    withdrawalDatasets.push({
      label: "Target annual income",
      data: data.ages.map(() => data.annual_expenses_target),
      borderColor: cssVar("--rust") || "#c4795a",
      borderDash: [6, 4],
      pointRadius: 0,
      borderWidth: 1.5,
    });
  }

  new Chart(document.getElementById("withdrawalChart"), {
    type: "line",
    data: { labels: data.ages, datasets: withdrawalDatasets },
    options: {
      responsive: true,
      maintainAspectRatio: !isMobile,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { grid: { color: gridColor }, title: { display: true, text: "Age" }, ticks: { autoSkip: true, maxRotation: 0 } },
        y: { grid: { color: gridColor }, ticks: { callback: (v) => fmtMoney(v) } },
      },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10 } },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${fmtMoney(ctx.parsed.y)}` } },
      },
    },
    plugins: [markerLinesPlugin],
  });

  // --- Growth rate scenario chart ---
  const SCENARIO_COLORS = {
    "3": "#5aa9c9", // steel blue — conservative
    "5": "#7c9a93", // sage
    "7": "#6fb088", // moss
    "9": "#c8932b", // brass
    "12": "#c4795a", // rust — aggressive
    actual: "#a98cc8", // plum — your accounts' real configured rates
  };

  const scenarioRetirementIndex = data.scenario_ages.indexOf(data.retirement_age);
  const scenarioMarkerPlugin = {
    id: "scenarioMarker",
    afterDraw(chart) {
      if (scenarioRetirementIndex < 0) return;
      const xScale = chart.scales.x;
      const { ctx, chartArea } = chart;
      const x = xScale.getPixelForValue(scenarioRetirementIndex);
      ctx.save();
      ctx.strokeStyle = retirementColor;
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.font = "11px Inter, sans-serif";
      ctx.fillStyle = retirementColor;
      ctx.setLineDash([]);
      ctx.fillText("retirement", x + 4, chartArea.top + 12);
      ctx.restore();
    },
  };

  const scenarioDatasets = data.scenario_rates.map((rate) => ({
    label: `${rate}%`,
    data: data.scenario_series[String(rate)],
    borderColor: SCENARIO_COLORS[String(rate)],
    backgroundColor: "transparent",
    pointRadius: 0,
    borderWidth: 2,
    tension: 0.1,
  }));
  scenarioDatasets.push({
    label: "Your accounts' rates",
    data: data.scenario_series.actual,
    borderColor: SCENARIO_COLORS.actual,
    backgroundColor: "transparent",
    pointRadius: 0,
    borderWidth: 2.5,
    borderDash: [2, 2],
    tension: 0.1,
  });

  new Chart(document.getElementById("scenarioChart"), {
    type: "line",
    data: { labels: data.scenario_ages, datasets: scenarioDatasets },
    options: {
      responsive: true,
      maintainAspectRatio: !isMobile,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { grid: { color: gridColor }, title: { display: true, text: "Age" }, ticks: { autoSkip: true, maxRotation: 0 } },
        y: { grid: { color: gridColor }, ticks: { callback: (v) => fmtMoney(v) } },
      },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10 } },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${fmtMoney(ctx.parsed.y)}` } },
      },
    },
    plugins: [scenarioMarkerPlugin],
  });
}

document.addEventListener("DOMContentLoaded", loadDashboardCharts);
