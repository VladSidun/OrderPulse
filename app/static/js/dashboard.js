const dataElement = document.getElementById('status-chart-data');
const canvas = document.getElementById('status-chart');
const fallback = document.getElementById('chart-fallback');
if (dataElement && canvas && typeof window.Chart === 'function') {
  const data = JSON.parse(dataElement.textContent);
  if (data.values.some(value => value > 0)) {
    canvas.hidden = false;
    new window.Chart(canvas, {
      type: 'bar',
      data: {
        labels: data.labels,
        datasets: [{
          label: 'Замовлення',
          data: data.values,
          backgroundColor: ['#425b76', '#1850a3', '#705400', '#00636e', '#14643b', '#9e2433'],
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {legend: {display: false}},
        scales: {y: {beginAtZero: true, ticks: {precision: 0}}},
      },
    });
    fallback.hidden = true;
  }
}
