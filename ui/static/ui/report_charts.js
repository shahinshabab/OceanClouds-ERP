/*
 * Report charts.
 *
 * The view puts every chart's data in one json_script block (#report-charts);
 * each <canvas data-report-chart="key"> draws the chart with that key.
 * Chart shapes come from reports/utils.py _chart():
 *   {type: "bar" | "hbar" | "line", format: "count" | "money" | "hours",
 *    labels: [...], series: [{label, values}], stacked: bool}
 */
(function () {
  "use strict";

  var dataNode = document.getElementById("report-charts");
  if (!dataNode || typeof window.Chart === "undefined") {
    return;
  }

  var charts = JSON.parse(dataNode.textContent);

  // Black and white app: the first series is ink, the second a mid grey,
  // the third a light grey. Identity never relies on colour alone: series
  // carry a legend and the tooltip names them.
  var SERIES = ["#0a0a0a", "#8c8c8c", "#cfcfcf"];
  var INK = "#0a0a0a";
  var MUTED = "#6b6b6b";
  var GRID = "#ececec";

  var money = new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  });
  var number = new Intl.NumberFormat("en-IN");

  function formatValue(value, format) {
    if (format === "money") {
      return money.format(value);
    }
    if (format === "hours") {
      var minutes = Math.round(value * 60);
      return Math.floor(minutes / 60) + "h " + (minutes % 60) + "m";
    }
    return number.format(value);
  }

  function formatTick(value, format) {
    if (format === "money") {
      if (Math.abs(value) >= 100000) {
        return "₹" + (value / 100000).toFixed(1).replace(/\.0$/, "") + "L";
      }
      if (Math.abs(value) >= 1000) {
        return "₹" + (value / 1000).toFixed(0) + "k";
      }
      return "₹" + value;
    }
    if (format === "hours") {
      return value + "h";
    }
    return number.format(value);
  }

  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 12;
  Chart.defaults.color = MUTED;

  function build(canvas, spec) {
    var horizontal = spec.type === "hbar";
    var line = spec.type === "line";
    var multi = spec.series.length > 1;
    var valueAxis = horizontal ? "x" : "y";
    var categoryAxis = horizontal ? "y" : "x";

    var datasets = spec.series.map(function (series, index) {
      var colour = SERIES[index % SERIES.length];
      var dataset = {
        label: series.label,
        data: series.values,
        backgroundColor: colour,
        borderColor: colour,
      };
      if (line) {
        dataset.borderWidth = 2;
        dataset.pointRadius = 0;
        dataset.pointHoverRadius = 5;
        dataset.pointHitRadius = 12;
        dataset.cubicInterpolationMode = "monotone";
        dataset.fill = false;
        dataset.borderDash = index === 1 ? [6, 4] : [];
      } else {
        dataset.borderRadius = 4;
        dataset.borderSkipped = "start";
        dataset.borderWidth = 0;
        dataset.maxBarThickness = horizontal ? 18 : 28;
        dataset.categoryPercentage = 0.75;
        dataset.barPercentage = 0.9;
      }
      return dataset;
    });

    var scales = {};
    scales[valueAxis] = {
      beginAtZero: true,
      stacked: !!spec.stacked,
      grid: { color: GRID, drawTicks: false },
      border: { display: false },
      ticks: {
        padding: 6,
        precision: spec.format === "count" ? 0 : undefined,
        callback: function (value) {
          return formatTick(value, spec.format);
        },
      },
    };
    scales[categoryAxis] = {
      stacked: !!spec.stacked,
      grid: { display: false },
      border: { color: GRID },
      ticks: {
        color: horizontal ? INK : MUTED,
        autoSkip: !horizontal,
        maxRotation: 0,
      },
    };

    return new Chart(canvas, {
      type: line ? "line" : "bar",
      data: { labels: spec.labels, datasets: datasets },
      options: {
        indexAxis: horizontal ? "y" : "x",
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 250 },
        interaction: { mode: "index", intersect: false, axis: categoryAxis },
        scales: scales,
        plugins: {
          legend: {
            display: multi,
            position: "bottom",
            align: "start",
            labels: { boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 2, color: INK },
          },
          tooltip: {
            backgroundColor: INK,
            padding: 10,
            cornerRadius: 8,
            displayColors: multi,
            callbacks: {
              label: function (context) {
                var value = formatValue(context.parsed[valueAxis] || 0, spec.format);
                return multi ? " " + context.dataset.label + ": " + value : " " + value;
              },
              footer: function (items) {
                if (!multi || !spec.stacked) {
                  return "";
                }
                var total = items.reduce(function (sum, item) {
                  return sum + (item.parsed[valueAxis] || 0);
                }, 0);
                return "Total: " + formatValue(total, spec.format);
              },
            },
          },
        },
      },
    });
  }

  document.querySelectorAll("canvas[data-report-chart]").forEach(function (canvas) {
    var spec = charts[canvas.dataset.reportChart];
    if (!spec) {
      return;
    }
    var empty = spec.series.every(function (series) {
      return series.values.every(function (value) {
        return !value;
      });
    });
    if (empty || !spec.labels.length) {
      var box = canvas.closest(".chart-box");
      if (box) {
        box.classList.add("is-empty");
      }
      return;
    }
    if (spec.type === "hbar") {
      // Give each bar row enough room, however many categories there are.
      var box2 = canvas.closest(".chart-box");
      if (box2) {
        box2.style.height = Math.max(160, spec.labels.length * 30 + 40) + "px";
      }
    }
    build(canvas, spec);
  });
})();
