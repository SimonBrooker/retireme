const isMobile = window.matchMedia("(max-width: 768px)").matches;

const KIDS_PALETTE = [
  "#c8932b", "#6fb088", "#c4795a", "#5aa9c9", "#a98cc8", "#cfa15a", "#7c9a93", "#d17ba0",
];

function fmtKidsMoney(value, symbol) {
  if (value === null || value === undefined) return "—";
  return symbol + Math.round(value).toLocaleString("en-GB");
}

function cssVarKids(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

async function loadKidsChart() {
  const canvas = document.getElementById("kidsChart");
  if (!canvas) return;

  const res = await fetch("/kids/api/projection" + window.location.search);
  const data = await res.json();
  const symbol = data.currency_symbol || "£";

  const gridColor = cssVarKids("--line-soft") || "rgba(150,150,150,0.15)";
  const tickColor = cssVarKids("--paper-dim") || "#888";
  const markerColor = cssVarKids("--brass") || "#c8932b";

  Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
  Chart.defaults.color = tickColor;

  const eighteenIndex = data.ages.indexOf(18);

  const markerPlugin = {
    id: "eighteenMarker",
    afterDraw(chart) {
      if (eighteenIndex < 0) return;
      const xScale = chart.scales.x;
      const { ctx, chartArea } = chart;
      const x = xScale.getPixelForValue(eighteenIndex);
      ctx.save();
      ctx.strokeStyle = markerColor;
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.font = "11px Inter, sans-serif";
      ctx.fillStyle = markerColor;
      ctx.setLineDash([]);
      ctx.fillText("18th birthday", x + 4, chartArea.top + 12);
      ctx.restore();
    },
  };

  const datasets = data.children.map((child, i) => {
    const color = KIDS_PALETTE[i % KIDS_PALETTE.length];
    return {
      label: child.name,
      data: child.balances,
      borderColor: color,
      backgroundColor: color + "33",
      fill: false,
      spanGaps: false,
      tension: 0.15,
      borderWidth: 2,
      pointRadius: 0,
    };
  });

  new Chart(canvas, {
    type: "line",
    data: { labels: data.ages, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: !isMobile,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { grid: { color: gridColor }, title: { display: true, text: "Age" }, ticks: { autoSkip: true, maxRotation: 0 } },
        y: {
          grid: { color: gridColor },
          ticks: { callback: (v) => fmtKidsMoney(v, symbol) },
        },
      },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10 } },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${fmtKidsMoney(ctx.parsed.y, symbol)}`,
          },
        },
      },
    },
    plugins: [markerPlugin],
  });
}

document.addEventListener("DOMContentLoaded", loadKidsChart);
