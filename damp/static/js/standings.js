// Public standings page: points-over-time chart, leaderboard, search and player stats.
(function () {
  "use strict";

  const data = JSON.parse(document.getElementById("lp-data").textContent);
  const players = data.players; // sorted by rank
  const byId = new Map(players.map((p) => [p.id, p]));
  const TOP_N = 4; // leaders drawn in colour; everyone else is a muted context line
  const TOOLTIP_N = 6;
  const labels = ["Start"].concat(data.nights.map((n) => n.label));

  // Leaders: rank <= TOP_N, but never split a tie at the cut (then colour only those above it).
  const cut = players.filter((p) => p.rank <= TOP_N).length > TOP_N ? players[TOP_N].rank : TOP_N + 1;
  const leaders = players.filter((p) => p.rank < cut).slice(0, TOP_N);
  const leaderSlot = new Map(leaders.map((p, i) => [p.id, i]));

  const fmtPts = (v) => Number(v).toLocaleString("sv-SE", { maximumFractionDigits: 2 });
  const fmtOr = (v, f = String) => (v == null ? "–" : f(v));
  let selectedId = null;
  let hoverId = null;
  let theme = readTheme();
  let chart = null;

  function readTheme() {
    const css = getComputedStyle(document.documentElement);
    const v = (name) => css.getPropertyValue(name).trim();
    return {
      font: v("--font") || "system-ui, sans-serif",
      text: v("--text"),
      text2: v("--text-2"),
      muted: v("--text-muted"),
      surface: v("--surface"),
      grid: v("--chart-grid"),
      axis: v("--chart-axis"),
      line: v("--chart-muted"),
      lineDim: v("--chart-muted-dim"),
      series: [v("--chart-1"), v("--chart-2"), v("--chart-3"), v("--chart-4")],
      selected: [v("--chart-selected"), v("--chart-selected-2"), v("--chart-selected-3")],
    };
  }

  // ---------- colours / emphasis ----------

  function focusId() {
    return hoverId ?? selectedId;
  }

  function baseColor(id) {
    return leaderSlot.has(id) ? theme.series[leaderSlot.get(id)] : theme.line;
  }

  function selectedStroke(chartCtx) {
    const [a, b, c] = theme.selected;
    const area = chartCtx.chart.chartArea;
    if (!area || (a === b && b === c)) return a;
    const g = chartCtx.chart.ctx.createLinearGradient(area.left, 0, area.right, 0);
    g.addColorStop(0, a);
    g.addColorStop(0.5, b);
    g.addColorStop(1, c);
    return g;
  }

  function strokeFor(id) {
    const f = focusId();
    if (f == null) return baseColor(id);
    if (id === f) return selectedStroke;
    return theme.lineDim;
  }

  function keyColor(id) {
    const f = focusId();
    if (f != null && id === f) return theme.selected[0];
    if (f != null) return theme.lineDim;
    return baseColor(id);
  }

  function datasetStyle(id) {
    const f = focusId();
    const isFocus = id === f;
    const isLeader = leaderSlot.has(id);
    const dot = keyColor(id);
    return {
      borderColor: strokeFor(id),
      backgroundColor: dot,
      pointBackgroundColor: dot,
      pointHoverBackgroundColor: dot,
      borderWidth: isFocus ? 3 : f == null && isLeader ? 2 : 1.25,
      pointRadius: isFocus ? 3.5 : 0,
      order: isFocus ? 0 : isLeader ? 1 : 2,
    };
  }

  // Note: update("none") in Chart.js 4.5 keeps stale point options, so use a short animated update.
  function styleDatasets() {
    chart.data.datasets.forEach((ds) => Object.assign(ds, datasetStyle(ds.playerId)));
    chart.update();
  }

  // ---------- chart plugins ----------

  const crosshair = {
    id: "crosshair",
    afterDatasetsDraw(c) {
      const active = c.tooltip && c.tooltip.getActiveElements();
      if (!active || !active.length) return;
      const x = active[0].element.x;
      const { top, bottom } = c.chartArea;
      const ctx = c.ctx;
      ctx.save();
      ctx.strokeStyle = theme.axis;
      ctx.globalAlpha = 0.6;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.restore();
    },
  };

  // Direct end labels for the coloured lines (leaders, or the focused player).
  // A label that would collide with one already drawn is skipped; the legend
  // and leaderboard still carry identity.
  const endLabels = {
    id: "endLabels",
    afterDatasetsDraw(c) {
      if (c.width < 560) return;
      const f = focusId();
      const want = f != null ? [f] : leaders.map((p) => p.id);
      const ctx = c.ctx;
      ctx.save();
      ctx.font = `600 12px ${theme.font}`;
      ctx.fillStyle = theme.text2;
      ctx.textBaseline = "middle";
      const placed = [];
      want.forEach((id) => {
        const idx = c.data.datasets.findIndex((d) => d.playerId === id);
        if (idx < 0) return;
        const pts = c.getDatasetMeta(idx).data;
        const last = pts[pts.length - 1];
        if (!last) return;
        if (placed.some((y) => Math.abs(y - last.y) < 14)) return;
        placed.push(last.y);
        const name = byId.get(id).name;
        const room = c.width - last.x - 10;
        let text = name;
        while (text.length > 1 && ctx.measureText(text).width > room) text = text.slice(0, -1);
        ctx.fillText(text === name ? name : text.slice(0, -1) + "…", last.x + 8, last.y);
      });
      ctx.restore();
    },
  };

  // Right padding wide enough for the longest name an end label could show.
  function endLabelRoom() {
    const ctx = document.createElement("canvas").getContext("2d");
    ctx.font = `600 12px ${theme.font}`;
    const widest = Math.max(0, ...players.map((p) => ctx.measureText(p.name).width));
    return Math.ceil(Math.min(170, widest + 14));
  }

  // Per night: the ids shown in the tooltip (top N at that point + focus).
  const tooltipIds = labels.map((_, i) => {
    const top = players
      .filter((p) => p.series[i] > 0)
      .sort((a, b) => b.series[i] - a.series[i])
      .slice(0, TOOLTIP_N)
      .map((p) => p.id);
    return new Set(top);
  });

  function buildChart() {
    const canvas = document.getElementById("points-chart");
    if (!canvas) return;
    const labelRoom = endLabelRoom();
    Chart.defaults.font.family = theme.font;
    chart = new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: players.map((p) => ({
          label: p.name,
          playerId: p.id,
          data: p.series,
          tension: 0,
          borderJoinStyle: "round",
          borderCapStyle: "round",
          // Hover dots only on the series the tooltip lists, not on every line.
          pointHoverRadius: (ctx) => (ctx.dataset.playerId === focusId() || tooltipIds[ctx.dataIndex].has(ctx.dataset.playerId) ? 5 : 0),
          pointBorderWidth: 0,
          pointHoverBorderWidth: 0,
          ...datasetStyle(p.id),
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 180 },
        // End labels are hidden on narrow charts, so only reserve room for them when shown.
        layout: { padding: (ctx) => ({ right: ctx.chart.width < 560 ? 8 : labelRoom, top: 8 }) },
        interaction: { mode: "index", intersect: false },
        onHover(evt, _els, c) {
          // Hovering near a specific line (not just the night) highlights it.
          const near = c.getElementsAtEventForMode(evt, "nearest", { intersect: false, axis: "xy" }, false)[0];
          const id = near && Math.abs(near.element.y - evt.y) < 10 ? c.data.datasets[near.datasetIndex].playerId : null;
          if (id !== hoverId && selectedId == null) {
            hoverId = id;
            refreshEmphasis();
          }
        },
        onClick(evt, _els, c) {
          const near = c.getElementsAtEventForMode(evt, "nearest", { intersect: false, axis: "xy" }, false)[0];
          if (near && Math.abs(near.element.y - evt.y) < 12) select(c.data.datasets[near.datasetIndex].playerId);
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: theme.axis },
            ticks: { color: theme.muted, maxRotation: 0, autoSkipPadding: 12 },
          },
          y: {
            beginAtZero: true,
            grid: { color: theme.grid },
            border: { display: false },
            ticks: { color: theme.muted, precision: 0 },
            title: { display: true, text: "Poäng", color: theme.muted },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: theme.surface.startsWith("rgba") ? "#1a1636" : theme.surface,
            titleColor: theme.text,
            bodyColor: theme.text2,
            borderColor: theme.grid,
            borderWidth: 1,
            padding: 10,
            usePointStyle: true,
            boxWidth: 14,
            boxHeight: 3,
            filter(item) {
              const id = item.dataset.playerId;
              return id === focusId() || tooltipIds[item.dataIndex].has(id);
            },
            itemSort: (a, b) => b.raw - a.raw,
            callbacks: {
              title: (items) => (items[0].dataIndex === 0 ? "Start" : "Efter " + items[0].label),
              label: (item) => ` ${fmtPts(item.raw)} p  ${item.dataset.label}`,
              labelPointStyle: () => ({ pointStyle: "line", rotation: 0 }),
              labelColor: (item) => ({ borderColor: keyColor(item.dataset.playerId), backgroundColor: keyColor(item.dataset.playerId), borderWidth: 3 }),
            },
          },
        },
      },
      plugins: [crosshair, endLabels],
    });
    canvas.addEventListener("mouseleave", () => {
      if (hoverId != null) {
        hoverId = null;
        refreshEmphasis();
      }
    });
  }

  function applyThemeToChart() {
    if (!chart) return;
    const o = chart.options;
    Chart.defaults.font.family = theme.font;
    o.scales.x.border.color = theme.axis;
    o.scales.x.ticks.color = theme.muted;
    o.scales.y.grid.color = theme.grid;
    o.scales.y.ticks.color = theme.muted;
    o.scales.y.title.color = theme.muted;
    const t = o.plugins.tooltip;
    t.backgroundColor = theme.surface.startsWith("rgba") ? "#1a1636" : theme.surface;
    t.titleColor = theme.text;
    t.bodyColor = theme.text2;
    t.borderColor = theme.grid;
  }

  // ---------- legend / leaderboard keys ----------

  const legendEl = document.getElementById("chart-legend");

  function lineKey(color) {
    const k = document.createElement("span");
    k.className = "line-key";
    k.setAttribute("aria-hidden", "true");
    k.style.background = color;
    return k;
  }

  function renderLegend() {
    legendEl.replaceChildren();
    if (!players.length) return;
    const f = focusId();
    const add = (color, text) => {
      const li = document.createElement("li");
      li.append(lineKey(color), document.createTextNode(text));
      legendEl.append(li);
    };
    if (f != null) {
      add(theme.selected[0], byId.get(f).name);
      add(theme.lineDim, "Övriga spelare");
    } else {
      leaders.forEach((p, i) => add(theme.series[i], `${p.rank}. ${p.name}`));
      if (players.length > leaders.length) add(theme.line, "Övriga spelare");
    }
  }

  const rows = new Map(
    Array.from(document.querySelectorAll("#leaderboard tbody tr")).map((tr) => [Number(tr.dataset.player), tr])
  );

  function renderRowKeys() {
    rows.forEach((tr, id) => {
      tr.querySelector(".line-key").style.background = keyColor(id);
      tr.classList.toggle("is-selected", id === selectedId);
    });
  }

  function refreshEmphasis() {
    if (chart) styleDatasets();
    renderLegend();
    renderRowKeys();
  }

  // ---------- player detail ----------

  const el = (id) => document.getElementById(id);

  function renderPlayer() {
    const p = selectedId != null ? byId.get(selectedId) : null;
    el("player-empty").hidden = !!p;
    el("player-detail").hidden = !p;
    if (!p) return;
    el("pd-name").textContent = p.name;
    el("pd-rank").textContent = `${p.rank}`;
    const of = document.createElement("small");
    of.textContent = ` av ${players.length}`;
    el("pd-rank").append(of);
    el("pd-points").textContent = fmtPts(p.points);
    el("pd-nights").textContent = p.nights;
    el("pd-wins").textContent = fmtOr(p.wins);
    el("pd-avg").textContent = fmtOr(p.avg, (v) => v.toFixed(1).replace(".", ","));
    el("pd-wipes").textContent = fmtOr(p.wipes);
    el("pd-manual-note").hidden = !p.has_manual;
    const tbody = el("pd-results");
    tbody.replaceChildren();
    p.results
      .slice()
      .reverse()
      .forEach((r) => {
        const tr = document.createElement("tr");
        const cells = [
          data.nights[r.night].label,
          fmtOr(r.table),
          r.placement == null ? "–" : `${r.placement} / ${r.size}`,
          (r.points >= 0 ? "+" : "") + fmtPts(r.points),
        ];
        cells.forEach((text, i) => {
          const td = document.createElement("td");
          td.textContent = text;
          if (i > 0) td.className = "num";
          tr.append(td);
        });
        tbody.append(tr);
      });
  }

  function syncUrl() {
    const url = new URL(window.location.href);
    url.searchParams.set("lp", data.period.id);
    if (selectedId != null) url.searchParams.set("player", selectedId);
    else url.searchParams.delete("player");
    history.replaceState(null, "", url);
  }

  function select(id) {
    selectedId = id != null && byId.has(id) ? id : null;
    hoverId = null;
    refreshEmphasis();
    renderPlayer();
    syncUrl();
  }

  el("pd-clear").addEventListener("click", () => select(null));

  rows.forEach((tr, id) => {
    tr.addEventListener("click", () => select(selectedId === id ? null : id));
    tr.addEventListener("mouseenter", () => {
      if (selectedId == null) {
        hoverId = id;
        refreshEmphasis();
      }
    });
    tr.addEventListener("mouseleave", () => {
      if (hoverId === id) {
        hoverId = null;
        refreshEmphasis();
      }
    });
  });

  // ---------- LP select ----------

  const lpSelect = el("lp-select");
  lpSelect.addEventListener("change", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("lp", lpSelect.value);
    window.location.assign(url);
  });

  // ---------- search ----------

  const input = el("player-search");
  const list = el("player-suggest");
  let matches = [];
  let active = -1;

  function norm(s) {
    return s.toLocaleLowerCase("sv").normalize("NFKD").replace(/[̀-ͯ]/g, "");
  }

  function closeSuggest() {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  }

  function renderSuggest() {
    const q = norm(input.value.trim());
    list.replaceChildren();
    if (!q) return closeSuggest();
    matches = players.filter((p) => norm(p.name).includes(q)).slice(0, 8);
    if (!matches.length) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = `Ingen spelare med poäng i ${data.period.label}`;
      list.append(li);
    }
    matches.forEach((p, i) => {
      const li = document.createElement("li");
      li.id = `sugg-${p.id}`;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", String(i === active));
      const name = document.createElement("span");
      name.textContent = p.name;
      const sub = document.createElement("span");
      sub.className = "sub";
      sub.textContent = `#${p.rank} · ${fmtPts(p.points)} p`;
      li.append(name, sub);
      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        choose(p);
      });
      list.append(li);
    });
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    if (active >= 0 && matches[active]) input.setAttribute("aria-activedescendant", `sugg-${matches[active].id}`);
  }

  function choose(p) {
    input.value = "";
    closeSuggest();
    select(p.id);
    const row = rows.get(p.id);
    if (row && window.innerWidth < 880) row.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  input.addEventListener("input", () => {
    active = -1;
    renderSuggest();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!matches.length) return;
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + matches.length) % matches.length;
      renderSuggest();
    } else if (e.key === "Enter") {
      e.preventDefault();
      const p = matches[active >= 0 ? active : 0];
      if (p) choose(p);
    } else if (e.key === "Escape") {
      closeSuggest();
    }
  });
  input.addEventListener("blur", () => setTimeout(closeSuggest, 100));

  // ---------- theme ----------

  document.addEventListener("damp:themechange", () => {
    theme = readTheme();
    applyThemeToChart();
    refreshEmphasis();
  });

  // ---------- init ----------

  buildChart();
  const initial = Number(new URL(window.location.href).searchParams.get("player"));
  select(byId.has(initial) ? initial : null);
})();
