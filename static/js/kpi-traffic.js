(() => {
  const root = document.querySelector("[data-traffic-graph]");
  const dataNode = document.getElementById("traffic-series");
  if (!root || !dataNode) return;

  let series = [];
  try {
    series = JSON.parse(dataNode.textContent || "[]");
  } catch (_err) {
    series = [];
  }

  const ns = "http://www.w3.org/2000/svg";
  const visitorsColor = "#051A9C";
  const viewsColor = "#FF5908";

  function el(name, attrs = {}, parent = null) {
    const node = document.createElementNS(ns, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (parent) parent.appendChild(node);
    return node;
  }

  function draw() {
    const width = Math.max(root.clientWidth || 640, 280);
    const height = 240;
    const pad = { top: 18, right: 16, bottom: 36, left: 36 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;

    root.replaceChildren();
    const svg = el(
      "svg",
      {
        viewBox: `0 0 ${width} ${height}`,
        width: "100%",
        height: String(height),
        role: "presentation",
      },
      root
    );

    if (!series.length) {
      const empty = el(
        "text",
        {
          x: String(width / 2),
          y: String(height / 2),
          "text-anchor": "middle",
          fill: "#5A6490",
          "font-size": "13",
          "font-family": "Inter, sans-serif",
        },
        svg
      );
      empty.textContent = "No visits yet.";
      return;
    }

    const maxValue = Math.max(
      1,
      ...series.map((row) => Math.max(row.visitors || 0, row.views || 0))
    );
    const xAt = (index) => {
      if (series.length === 1) return pad.left + innerW / 2;
      return pad.left + (index / (series.length - 1)) * innerW;
    };
    const yAt = (value) => pad.top + innerH - (value / maxValue) * innerH;

    for (let tick = 0; tick <= 3; tick += 1) {
      const value = Math.round((maxValue * tick) / 3);
      const y = yAt(value);
      el(
        "line",
        {
          x1: String(pad.left),
          x2: String(width - pad.right),
          y1: String(y),
          y2: String(y),
          stroke: "rgba(5, 26, 156, 0.08)",
          "stroke-width": "1",
        },
        svg
      );
      const label = el(
        "text",
        {
          x: String(pad.left - 8),
          y: String(y + 3),
          "text-anchor": "end",
          fill: "#8B93B5",
          "font-size": "10",
          "font-family": "Inter, sans-serif",
        },
        svg
      );
      label.textContent = String(value);
    }

    function linePath(key) {
      return series
        .map((row, index) => {
          const command = index === 0 ? "M" : "L";
          return `${command}${xAt(index).toFixed(1)} ${yAt(row[key] || 0).toFixed(1)}`;
        })
        .join(" ");
    }

    function areaPath(key) {
      if (series.length === 1) {
        const x = xAt(0);
        const y = yAt(series[0][key] || 0);
        const half = Math.min(28, innerW * 0.18);
        return `M${x - half} ${pad.top + innerH} L${x - half} ${y} L${x + half} ${y} L${x + half} ${pad.top + innerH} Z`;
      }
      const top = series
        .map((row, index) => {
          const command = index === 0 ? "M" : "L";
          return `${command}${xAt(index).toFixed(1)} ${yAt(row[key] || 0).toFixed(1)}`;
        })
        .join(" ");
      const lastX = xAt(series.length - 1);
      const firstX = xAt(0);
      const base = pad.top + innerH;
      return `${top} L${lastX.toFixed(1)} ${base} L${firstX.toFixed(1)} ${base} Z`;
    }

    el(
      "path",
      {
        d: areaPath("views"),
        fill: "rgba(255, 89, 8, 0.12)",
        stroke: "none",
      },
      svg
    );
    el(
      "path",
      {
        d: linePath("views"),
        fill: "none",
        stroke: viewsColor,
        "stroke-width": "2",
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
      },
      svg
    );
    el(
      "path",
      {
        d: linePath("visitors"),
        fill: "none",
        stroke: visitorsColor,
        "stroke-width": "2",
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
      },
      svg
    );

    series.forEach((row, index) => {
      const x = xAt(index);
      el(
        "circle",
        {
          cx: String(x),
          cy: String(yAt(row.views || 0)),
          r: "3",
          fill: viewsColor,
        },
        svg
      );
      el(
        "circle",
        {
          cx: String(x),
          cy: String(yAt(row.visitors || 0)),
          r: "3",
          fill: visitorsColor,
        },
        svg
      );
    });

    const labelEvery = Math.max(1, Math.ceil(series.length / 7));
    series.forEach((row, index) => {
      const isEdge = index === 0 || index === series.length - 1;
      if (!isEdge && index % labelEvery !== 0) return;
      const label = el(
        "text",
        {
          x: String(xAt(index)),
          y: String(height - 12),
          "text-anchor": "middle",
          fill: "#5A6490",
          "font-size": "10",
          "font-family": "Inter, sans-serif",
        },
        svg
      );
      label.textContent = row.label || row.day;
    });
  }

  draw();
  window.addEventListener("resize", draw);
})();
