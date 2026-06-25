function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function fmtMoney(value, symbol) {
  if (value === null || value === undefined) return "—";
  return symbol + Math.round(value).toLocaleString("en-GB");
}

document.addEventListener("DOMContentLoaded", () => {
  const meta = document.getElementById("history-chart-data");
  if (!meta) return;
  const HISTORY_CHART_DATA = JSON.parse(meta.dataset.charts);
  const symbol = meta.dataset.currency || "£";
  const gridColor = cssVar("--line-soft") || "rgba(150,150,150,0.15)";
  const tickColor = cssVar("--paper-dim") || "#888";
  const brass = cssVar("--brass") || "#c8932b";
  const moss = cssVar("--moss") || "#6fb088";
  const rust = cssVar("--rust") || "#c4795a";

  Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
  Chart.defaults.color = tickColor;

  for (const [accountId, data] of Object.entries(HISTORY_CHART_DATA)) {
    const canvas = document.getElementById("history-chart-" + accountId);
    if (!canvas) continue;

    const { ages, projected, adjusted, actuals, current_age } = data;

    // Actual recorded dots — null everywhere except ages with a snapshot
    const actualPoints = ages.map(age =>
      actuals[String(age)] !== undefined ? actuals[String(age)] : null
    );

    // Today marker plugin
    const todayIndex = ages.indexOf(current_age);
    const todayPlugin = {
      id: "todayLine",
      afterDraw(chart) {
        if (todayIndex < 0) return;
        const { ctx, chartArea, scales } = chart;
        const x = scales.x.getPixelForValue(todayIndex);
        ctx.save();
        ctx.strokeStyle = tickColor;
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, chartArea.top);
        ctx.lineTo(x, chartArea.bottom);
        ctx.stroke();
        ctx.restore();
      },
    };

    new Chart(canvas, {
      type: "line",
      plugins: [todayPlugin],
      data: {
        labels: ages,
        datasets: [
          {
            label: "Original projection",
            data: projected,
            borderColor: tickColor,
            borderDash: [5, 4],
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.3,
            fill: false,
          },
          {
            label: "Actual-adjusted",
            data: adjusted,
            borderColor: brass,
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
            fill: false,
          },
          {
            label: "Recorded actual",
            data: actualPoints,
            borderColor: "transparent",
            backgroundColor: moss,
            pointRadius: 5,
            pointHoverRadius: 7,
            showLine: false,
          },
        ],
      },
      options: {
        responsive: true,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            position: "bottom",
            labels: { boxWidth: 12, padding: 16, color: tickColor },
          },
          tooltip: {
            callbacks: {
              title: items => "Age " + items[0].label,
              label(item) {
                if (item.parsed.y === null) return null;
                return item.dataset.label + ": " + fmtMoney(item.parsed.y, symbol);
              },
            },
          },
        },
        scales: {
          x: {
            ticks: {
              maxTicksLimit: 12,
              callback: (_, i) => ages[i],
              color: tickColor,
            },
            grid: { color: gridColor },
          },
          y: {
            ticks: {
              color: tickColor,
              callback: v => symbol + Math.round(v / 1000) + "k",
            },
            grid: { color: gridColor },
          },
        },
      },
    });
  }
});
