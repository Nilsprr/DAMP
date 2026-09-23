// Admin night editor: tables of players in finishing order, live points preview, commit.
// Points always come from the server (scoring.points_for) so preview == saved.
(function () {
  "use strict";

  const init = JSON.parse(document.getElementById("editor-state").textContent);
  const urls = init.urls;
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const DRAFT_KEY = init.mode === "new" ? "damp-night-draft" : null;
  const $ = (id) => document.getElementById(id);
  const fmtPts = (v) => Number(v).toLocaleString("sv-SE", { maximumFractionDigits: 2 });

  let state = {
    date: init.date,
    period_id: init.period_id,
    note: init.note,
    tables: init.tables.map((t) => t.map(seatFrom)),
  };
  let points = []; // points[t][i], filled by preview
  let dirty = false;
  let committing = false;

  function seatFrom(m) {
    return {
      member_id: m.member_id ?? m.id,
      name: m.name,
      display_name: m.display_name || null,
      ltu_id: m.ltu_id || null,
      wipes: m.wipes || 0,
    };
  }

  // ---------- draft (new nights only) ----------

  if (DRAFT_KEY) {
    try {
      const saved = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
      if (saved && Array.isArray(saved.tables) && saved.tables.some((t) => t.length)) state = saved;
    } catch (e) {}
  }

  function saveDraft() {
    if (!DRAFT_KEY) return;
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(state));
    } catch (e) {}
  }

  function clearDraft() {
    if (!DRAFT_KEY) return;
    try {
      localStorage.removeItem(DRAFT_KEY);
    } catch (e) {}
  }

  function changed() {
    dirty = true;
    saveDraft();
    render();
    schedulePreview();
  }

  window.addEventListener("beforeunload", (e) => {
    if (dirty && !committing && init.mode === "edit") {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  // ---------- meta: date / LP / note ----------

  const dateEl = $("ne-date");
  const periodEl = $("ne-period");
  const noteEl = $("ne-note");
  const hintEl = $("ne-period-hint");

  init.periods.forEach((p) => {
    const o = document.createElement("option");
    o.value = p.id;
    o.textContent = p.label;
    periodEl.append(o);
  });

  function periodFor(d) {
    return init.periods.find((p) => p.starts_on <= d && d <= p.ends_on);
  }

  function syncPeriodHint() {
    const match = periodFor(state.date);
    if (!match) {
      hintEl.hidden = false;
      hintEl.textContent = "Inget LP täcker det datumet. Välj LP manuellt eller skapa ett nytt under LP.";
    } else if (match.id !== Number(state.period_id)) {
      hintEl.hidden = false;
      hintEl.textContent = `Datumet ligger i ${match.label}, men ett annat LP är valt.`;
    } else {
      hintEl.hidden = true;
    }
  }

  dateEl.value = state.date;
  periodEl.value = state.period_id ?? (periodFor(state.date) || {}).id ?? "";
  state.period_id = Number(periodEl.value) || null;
  noteEl.value = state.note || "";
  syncPeriodHint();

  dateEl.addEventListener("change", () => {
    state.date = dateEl.value;
    const p = periodFor(state.date);
    if (p) {
      state.period_id = p.id;
      periodEl.value = p.id;
    }
    syncPeriodHint();
    dirty = true;
    saveDraft();
  });
  periodEl.addEventListener("change", () => {
    state.period_id = Number(periodEl.value);
    syncPeriodHint();
    dirty = true;
    saveDraft();
  });
  noteEl.addEventListener("input", () => {
    state.note = noteEl.value;
    dirty = true;
    saveDraft();
  });

  // ---------- rendering ----------

  const tablesEl = $("ne-tables");
  const tpl = $("tpl-table");
  let focusTable = null;

  function tableOf(memberId) {
    return state.tables.findIndex((t) => t.some((s) => s.member_id === memberId));
  }

  function btn(label, title, onClick, cls) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.title = title;
    b.setAttribute("aria-label", title);
    if (cls) b.className = cls;
    b.addEventListener("click", onClick);
    return b;
  }

  function render() {
    tablesEl.replaceChildren();
    state.tables.forEach((seats, t) => {
      const node = tpl.content.firstElementChild.cloneNode(true);
      node.querySelector(".t-title").textContent = `Bord ${t + 1}`;
      const removeBtn = node.querySelector(".t-remove");
      removeBtn.hidden = state.tables.length === 1;
      removeBtn.addEventListener("click", () => {
        if (seats.length && !confirm(`Ta bort bord ${t + 1} med ${seats.length} spelare?`)) return;
        state.tables.splice(t, 1);
        changed();
      });

      const list = node.querySelector(".seat-list");
      seats.forEach((s, i) => list.append(seatRow(s, t, i, seats.length)));
      list.addEventListener("dragover", (e) => {
        e.preventDefault();
      });
      list.addEventListener("drop", (e) => {
        e.preventDefault();
        if (e.target === list) moveDragged(t, seats.length);
      });

      setupSearch(node, t);
      tablesEl.append(node);
      if (focusTable === t) node.querySelector(".t-input").focus();
    });
    focusTable = null;
    const n = state.tables.reduce((a, t) => a + t.length, 0);
    $("ne-summary").textContent = `${state.tables.length} bord · ${n} spelare`;
  }

  let dragFrom = null;

  function moveDragged(toTable, toIndex) {
    if (!dragFrom) return;
    const [ft, fi] = dragFrom;
    dragFrom = null;
    const [seat] = state.tables[ft].splice(fi, 1);
    if (ft === toTable && fi < toIndex) toIndex -= 1;
    state.tables[toTable].splice(toIndex, 0, seat);
    changed();
  }

  function seatRow(s, t, i, size) {
    const li = document.createElement("li");
    li.className = "seat";
    li.draggable = true;
    li.addEventListener("dragstart", (e) => {
      dragFrom = [t, i];
      li.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(s.member_id));
    });
    li.addEventListener("dragend", () => li.classList.remove("dragging"));
    li.addEventListener("dragover", (e) => {
      e.preventDefault();
      li.classList.add("drop-before");
    });
    li.addEventListener("dragleave", () => li.classList.remove("drop-before"));
    li.addEventListener("drop", (e) => {
      e.preventDefault();
      e.stopPropagation();
      li.classList.remove("drop-before");
      moveDragged(t, i);
    });

    const place = document.createElement("span");
    place.className = "place";
    place.textContent = i + 1;
    place.title = "Dra för att flytta";

    const who = document.createElement("span");
    who.className = "who";
    who.textContent = s.name;
    if (s.ltu_id) {
      const sub = document.createElement("span");
      sub.className = "sub";
      sub.textContent = s.ltu_id;
      who.append(sub);
    }

    const wipes = document.createElement("input");
    wipes.type = "number";
    wipes.min = 0;
    wipes.max = Math.max(size - 1, 0);
    wipes.value = s.wipes;
    wipes.setAttribute("aria-label", `Wipes för ${s.name}`);
    wipes.addEventListener("change", () => {
      const v = Math.max(0, Math.min(size - 1, parseInt(wipes.value, 10) || 0));
      s.wipes = v;
      wipes.value = v;
      dirty = true;
      saveDraft();
      schedulePreview();
    });

    const pts = document.createElement("span");
    pts.className = "pts pending";
    pts.dataset.t = t;
    pts.dataset.i = i;
    pts.textContent = points[t] && points[t][i] != null ? fmtPts(points[t][i]) : "…";

    const actions = document.createElement("span");
    actions.className = "actions";
    const move = (d) => () => {
      const seats = state.tables[t];
      const j = i + d;
      if (j < 0 || j >= seats.length) return;
      [seats[i], seats[j]] = [seats[j], seats[i]];
      changed();
    };
    actions.append(
      btn("↑", `Flytta upp ${s.name}`, move(-1), "move"),
      btn("↓", `Flytta ner ${s.name}`, move(1), "move"),
      btn("✕", `Ta bort ${s.name}`, () => {
        state.tables[t].splice(i, 1);
        changed();
      })
    );

    li.append(place, who, wipes, pts, actions);
    return li;
  }

  // ---------- points preview ----------

  let previewTimer = null;
  let previewSeq = 0;

  function schedulePreview() {
    clearTimeout(previewTimer);
    document.querySelectorAll(".seat .pts").forEach((el) => el.classList.add("pending"));
    previewTimer = setTimeout(runPreview, 120);
  }

  async function runPreview() {
    const seq = ++previewSeq;
    const body = { tables: state.tables.map((t) => t.map((s) => s.wipes)) };
    try {
      const res = await post(urls.preview, body);
      if (seq !== previewSeq || !res.ok) return;
      points = res.data.tables;
      document.querySelectorAll(".seat .pts").forEach((el) => {
        const v = points[el.dataset.t] && points[el.dataset.t][el.dataset.i];
        el.textContent = v != null ? fmtPts(v) : "…";
        el.classList.remove("pending");
      });
    } catch (e) {}
  }

  // ---------- search / add ----------

  function setupSearch(node, t) {
    const input = node.querySelector(".t-input");
    const list = node.querySelector(".suggest");
    const errEl = node.querySelector(".t-error");
    let results = [];
    let active = -1;
    let timer = null;
    let seq = 0;

    function showError(parts) {
      errEl.replaceChildren(...parts);
      errEl.hidden = false;
    }

    function hideError() {
      errEl.hidden = true;
      errEl.replaceChildren();
    }

    function close() {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      active = -1;
    }

    function draw() {
      list.replaceChildren();
      if (!results.length) {
        const li = document.createElement("li");
        li.className = "empty";
        li.textContent = "Ingen medlem matchar";
        list.append(li);
      }
      results.forEach((m, i) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", String(i === active));
        const left = document.createElement("span");
        left.textContent = m.name + (m.display_name ? ` "${m.display_name}"` : "");
        const right = document.createElement("span");
        right.className = "sub";
        right.textContent = m.ltu_id || "";
        if (!m.active) {
          const b = document.createElement("span");
          b.className = "badge badge-expired";
          b.textContent = m.status === "never" ? "Ej betalt" : "Utgången";
          right.append(" ", b);
        } else if (tableOf(m.id) !== -1) {
          right.append(" · redan med");
        }
        li.append(left, right);
        li.addEventListener("mousedown", (e) => {
          e.preventDefault();
          choose(m);
        });
        list.append(li);
      });
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }

    async function search() {
      const q = input.value.trim();
      const mySeq = ++seq;
      if (!q) {
        results = [];
        return close();
      }
      const url = `${urls.members}?q=${encodeURIComponent(q)}&date=${encodeURIComponent(state.date)}`;
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      if (mySeq !== seq || !res.ok) return;
      results = await res.json();
      active = results.length ? 0 : -1;
      draw();
    }

    function add(m) {
      state.tables[t].push(seatFrom(m));
      focusTable = t;
      changed();
    }

    function choose(m) {
      close();
      hideError();
      const at = tableOf(m.id);
      if (at !== -1) {
        showError([document.createTextNode(`${m.name} är redan med vid bord ${at + 1}.`)]);
        return;
      }
      if (!m.active) {
        const msg = m.status === "never" ? "har aldrig betalat medlemsavgift" : `har ett utgånget medlemskap (gick ut ${m.expires_on})`;
        const renew = btn("Förnya nu", `Förnya medlemskap för ${m.name}`, () => openRenew(m, (updated) => {
          hideError();
          add(updated);
        }), "btn btn-sm");
        showError([document.createTextNode(`${m.name} ${msg} och kan inte läggas till.`), renew]);
        return;
      }
      input.value = "";
      add(m);
    }

    input.addEventListener("input", () => {
      hideError();
      clearTimeout(timer);
      timer = setTimeout(search, 120);
    });
    input.addEventListener("keydown", async (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!results.length) return;
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + results.length) % results.length;
        draw();
      } else if (e.key === "Enter") {
        e.preventDefault();
        clearTimeout(timer);
        const q = input.value.trim();
        if (!q) return;
        await search();
        if (results.length) {
          choose(results[active >= 0 ? active : 0]);
        } else {
          close();
          const link = document.createElement("a");
          link.href = urls.members_page;
          link.target = "_blank";
          link.textContent = "Öppna Medlemmar";
          showError([document.createTextNode(`Ingen medlem matchar "${q}". Endast medlemmar kan läggas till. Lägg till personen under Medlemmar först.`), link]);
        }
      } else if (e.key === "Escape") {
        close();
      }
    });
    input.addEventListener("blur", () => setTimeout(close, 120));
  }

  // ---------- renew dialog ----------

  const dialog = $("renew-dialog");
  let renewCtx = null;

  function openRenew(member, onDone) {
    renewCtx = { member, onDone };
    $("renew-text").textContent = `Registrera betalning för ${member.name}. Betalningsdagen är förvald till kvällens datum.`;
    $("renew-date").value = state.date;
    $("renew-years").value = 1;
    $("renew-error").hidden = true;
    dialog.showModal();
  }

  $("renew-cancel").addEventListener("click", () => dialog.close());
  $("renew-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!renewCtx) return;
    const res = await post(urls.payment.replace(/\/0\/payments$/, `/${renewCtx.member.id}/payments`), {
      paid_on: $("renew-date").value,
      years: Number($("renew-years").value),
      date: state.date,
    });
    if (!res.ok) {
      $("renew-error").textContent = (res.data.errors || ["Något gick fel."]).join(" ");
      $("renew-error").hidden = false;
      return;
    }
    dialog.close();
    if (res.data.active) {
      renewCtx.onDone(res.data);
    } else {
      alert(`Betalningen är registrerad, men ${res.data.name} är fortfarande inte aktiv ${state.date}. Kontrollera betalningsdagen.`);
    }
    renewCtx = null;
  });

  // ---------- commit ----------

  async function post(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(body),
    });
    let data = {};
    try {
      data = await res.json();
    } catch (e) {
      data = { errors: [`Serverfel (${res.status}).`] };
    }
    return { ok: res.ok, status: res.status, data };
  }

  function showErrors(errors) {
    const box = $("ne-errors");
    const ul = document.createElement("ul");
    errors.forEach((msg) => {
      const li = document.createElement("li");
      li.textContent = msg;
      ul.append(li);
    });
    box.replaceChildren(document.createTextNode("Kunde inte spara:"), ul);
    box.hidden = false;
    box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  const commitBtn = $("ne-commit");
  commitBtn.addEventListener("click", async () => {
    $("ne-errors").hidden = true;
    const local = [];
    if (!state.date) local.push("Välj datum.");
    if (!state.period_id) local.push("Välj LP.");
    state.tables.forEach((t, i) => {
      if (t.length < 2) local.push(`Bord ${i + 1}: minst 2 spelare.`);
    });
    if (local.length) return showErrors(local);

    commitBtn.disabled = true;
    committing = true;
    const res = await post(urls.save, {
      date: state.date,
      period_id: state.period_id,
      note: state.note,
      tables: state.tables.map((t) => t.map((s) => ({ member_id: s.member_id, wipes: s.wipes }))),
    });
    if (res.ok) {
      clearDraft();
      window.location.assign(res.data.url);
      return;
    }
    committing = false;
    commitBtn.disabled = false;
    showErrors(res.data.errors || [res.data.error || `Serverfel (${res.status}).`]);
  });

  $("ne-add-table").addEventListener("click", () => {
    state.tables.push([]);
    focusTable = state.tables.length - 1;
    changed();
  });

  const clearBtn = $("ne-clear");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      if (!confirm("Rensa hela utkastet?")) return;
      clearDraft();
      state.tables = [[]];
      state.note = "";
      noteEl.value = "";
      points = [];
      dirty = false;
      render();
    });
  }

  render();
  schedulePreview();
})();
