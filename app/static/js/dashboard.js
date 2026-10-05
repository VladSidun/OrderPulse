const dataElement = document.getElementById("status-chart-data");
const canvas = document.getElementById("status-chart");
const fallback = document.getElementById("chart-fallback");
if (dataElement && canvas && typeof window.Chart === "function") {
  const data = JSON.parse(dataElement.textContent);
  if (data.values.some((value) => value > 0)) {
    canvas.hidden = false;
    new window.Chart(canvas, {
      type: "bar",
      data: {
        labels: data.labels,
        datasets: [
          {
            label: "Замовлення",
            data: data.values,
            backgroundColor: [
              "#a8d7be",
              "#aee0e6",
              "#ecdb91",
              "#6dcabd",
              "#c5f566",
              "#f4a99a",
            ],
            borderRadius: 8,
            maxBarThickness: 48,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? false
          : { duration: 400 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#1c2621",
            titleColor: "#f2f5ef",
            bodyColor: "#f2f5ef",
            borderColor: "#52645a",
            borderWidth: 1,
            padding: 12,
          },
        },
        scales: {
          x: {
            ticks: { color: "#b0bdb3" },
            grid: { display: false },
            border: { display: false },
          },
          y: {
            beginAtZero: true,
            ticks: { precision: 0, color: "#b0bdb3" },
            grid: { color: "#34423a" },
            border: { display: false },
          },
        },
      },
    });
    fallback.hidden = true;
  }
}
