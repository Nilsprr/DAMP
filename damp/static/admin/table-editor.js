// Admin table editor: one poker table, its players in finishing order, points preview, save.
// Points come from the table built from scoring.points_for (core.pointsFor), so the
// preview is exactly what gets saved.
//   /admin/bord/redigera/                 new table (latest Tuesday)
//   /admin/bord/redigera/?datum=2026-09-22  new table on that date (after saving one, for the next)
//   /admin/bord/redigera/?id=2026-09-22-2   edit that table
import {
  $, UserError, cleanName, flashNext, fmtPts, latestTuesday, memberByName, memberName, pointsChanges, pointsFor,
  resultLines, save, savedNote, scoreSeats, searchMembers, shortDate, start, tableErrors, tableLabel, tablePath, todayISO,
} from "./core.js";
import { memberDialog } from "./member-form.js";

const DRAFT_KEY = "damp-table-draft";

start(
  async (initial) => {
    let data = initial;
    const params = new URLSearchParams(location.search);
    const editId = params.get("id");
    const original = editId ? data.table(editId) : null;
    if (editId && !original) throw new UserError(`Det finns inget bord ${editId}.`);
    const editing = !!original;
    const originalDate = editing ? editId.slice(0, 10) : null;
    const originalNumber = editing ? Number(editId.slice(11)) : null;

    // state.seats[i] = {member, wipes}, i = finishing position (0 = winner)
    let state = editing
      ? { date: originalDate, note: original.note || "", seats: original.players.map((s) => ({ member: s.member, wipes: s.wipes || 0 })) }
      : { date: params.get("datum") || latestTuesday(todayISO()), note: "", seats: [] };
    let dirty = false;
    let saving = false;

    // ---------- draft (new tables only) ----------

    if (!editing) {
      try {
        const saved = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
        if (saved && Array.isArray(saved.seats) && saved.seats.length) {
          state = { date: saved.date || state.date, note: saved.note || "", seats: saved.seats.filter((s) => data.memberById.has(s.member)) };
        }
      } catch (e) {}
    }

    function saveDraft() {
      if (editing) return;
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify(state));
      } catch (e) {}
    }

    function clearDraft() {
      try {
        localStorage.removeItem(DRAFT_KEY);
      } catch (e) {}
    }

    function changed() {
      dirty = true;
      saveDraft();
      render();
    }

    window.addEventListener("beforeunload", (e) => {
      if (dirty && !saving && (editing || state.seats.length)) {
        e.preventDefault();
        e.returnValue = "";
      }
    });

    // ---------- header: date / LP / note ----------

    const dateEl = $("te-date");
    const noteEl = $("te-note");
    const hintEl = $("te-date-hint");

    if (editing) {
      $("te-title").textContent = `Redigera ${tableLabel(originalDate, originalNumber)}`;
      $("te-commit").textContent = "Spara ändringar";
    } else {
      $("te-clear").hidden = false;
    }
    dateEl.value = state.date;
    noteEl.value = state.note;

    /** The number this table gets (or keeps) on state.date. */
    function number() {
      return editing && state.date === originalDate ? originalNumber : data.nextTableNumber(state.date);
    }

    function syncHeader() {
      const p = state.date ? data.periodFor(state.date) : null;
      $("te-where").textContent = p ? `${p.label} · bord ${number()}` : "–";
      hintEl.replaceChildren();
      if (state.date && !p) {
        hintEl.append("Inget LP täcker det datumet. ", Object.assign(document.createElement("a"), { href: "/admin/lp/", textContent: "Skapa det under LP" }), ".");
      }
      hintEl.hidden = !hintEl.childNodes.length;
    }
    syncHeader();

    dateEl.addEventListener("change", () => {
      state.date = dateEl.value;
      dirty = true;
      saveDraft();
      syncHeader();
      render();
    });
    noteEl.addEventListener("input", () => {
      state.note = noteEl.value;
      dirty = true;
      saveDraft();
    });

    // Warn when the points function changed since this table was saved: saving re-scores it.
    if (editing) {
      const diffs = pointsChanges(original);
      if (diffs.length) {
        const box = $("te-points-warning");
        const ul = document.createElement("ul");
        diffs.forEach((d) => {
          ul.append(Object.assign(document.createElement("li"), { textContent: `Plats ${d.placement} (${data.memberName(d.member)}): ${fmtPts(d.stored)} → ${fmtPts(d.now)} p` }));
        });
        box.append("Poängfunktionen har ändrats sedan bordet sparades. Sparar du räknas bordet om med den nuvarande regeln:", ul);
        box.hidden = false;
      }
    }

    // ---------- seats ----------

    const listEl = $("te-seats");

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

    function seated(memberId) {
      return state.seats.some((s) => s.member === memberId);
    }

    /** Other tables the same day where this member already played (a note, not an error). */
    function otherTables(memberId) {
      return data
        .tablesOn(state.date)
        .filter((t) => t.id !== editId && t.players.some((s) => s.member === memberId))
        .map((t) => t.number);
    }

    function seatPoints(i, size, wipes) {
      try {
        return fmtPts(pointsFor(i + 1, size, wipes));
      } catch (e) {
        return "?";
      }
    }

    let dragFrom = null;

    function moveDragged(toIndex) {
      if (dragFrom == null) return;
      const from = dragFrom;
      dragFrom = null;
      const [seat] = state.seats.splice(from, 1);
      if (from < toIndex) toIndex -= 1;
      state.seats.splice(toIndex, 0, seat);
      changed();
    }

    listEl.addEventListener("dragover", (e) => e.preventDefault());
    listEl.addEventListener("drop", (e) => {
      e.preventDefault();
      if (e.target === listEl) moveDragged(state.seats.length);
    });

    function seatRow(s, i, size) {
      const name = data.memberName(s.member);
      const li = document.createElement("li");
      li.className = "seat";
      li.draggable = true;
      li.addEventListener("dragstart", (e) => {
        dragFrom = i;
        li.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", String(s.member));
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
        moveDragged(i);
      });

      const place = document.createElement("span");
      place.className = "place";
      place.textContent = i + 1;
      place.title = "Dra för att flytta";

      const who = document.createElement("span");
      who.className = "who";
      who.textContent = name;
      const others = otherTables(s.member);
      if (others.length) {
        const sub = document.createElement("span");
        sub.className = "sub";
        sub.textContent = `spelade även bord ${others.join(", ")} den dagen`;
        who.append(sub);
      }

      const wipes = document.createElement("input");
      wipes.type = "number";
      wipes.min = 0;
      wipes.max = Math.max(size - 1, 0);
      wipes.value = s.wipes;
      wipes.setAttribute("aria-label", `Wipes för ${name}`);
      const pts = document.createElement("span");
      pts.className = "pts";
      pts.textContent = seatPoints(i, size, s.wipes);
      wipes.addEventListener("change", () => {
        const v = Math.max(0, Math.min(size - 1, parseInt(wipes.value, 10) || 0));
        s.wipes = v;
        wipes.value = v;
        pts.textContent = seatPoints(i, size, v);
        dirty = true;
        saveDraft();
      });

      const actions = document.createElement("span");
      actions.className = "actions";
      const move = (d) => () => {
        const j = i + d;
        if (j < 0 || j >= state.seats.length) return;
        [state.seats[i], state.seats[j]] = [state.seats[j], state.seats[i]];
        changed();
      };
      actions.append(
        btn("↑", `Flytta upp ${name}`, move(-1), "move"),
        btn("↓", `Flytta ner ${name}`, move(1), "move"),
        btn("✕", `Ta bort ${name}`, () => {
          state.seats.splice(i, 1);
          changed();
        })
      );

      li.append(place, who, wipes, pts, actions);
      return li;
    }

    function render() {
      listEl.replaceChildren(...state.seats.map((s, i) => seatRow(s, i, state.seats.length)));
      $("te-summary").textContent = `${state.seats.length} spelare`;
      syncHeader();
    }

    // ---------- search / add / new member ----------

    const input = $("te-input");
    const suggest = $("te-suggest");
    const addError = $("te-add-error");
    let options = []; // {member, similar} or {create: text}
    let active = -1;

    function showAddError(text) {
      addError.textContent = text;
      addError.hidden = false;
    }

    function closeSuggest() {
      suggest.hidden = true;
      input.setAttribute("aria-expanded", "false");
      active = -1;
    }

    function refresh() {
      const q = cleanName(input.value);
      if (!q) {
        options = [];
        return closeSuggest();
      }
      const hits = searchMembers(data.members, q);
      options = hits.map((hit) => ({ member: hit.member, similar: hit.rank === 2 }));
      if (!memberByName(data.members, q)) options.push({ create: q });
      // Enter picks the first real match; with only look-alikes it picks "+ Ny medlem", not a guess.
      active = hits.some((hit) => hit.rank < 2) ? 0 : options.length - 1;
      draw();
    }

    function draw() {
      suggest.replaceChildren();
      options.forEach((o, i) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", String(i === active));
        const left = document.createElement("span");
        const right = document.createElement("span");
        right.className = "sub";
        if (o.create) {
          li.className = "create";
          left.textContent = `+ Ny medlem: ${o.create}…`;
          if (options.some((x) => x.similar)) right.textContent = "eller menade du någon ovan?";
        } else {
          const m = o.member;
          left.textContent = memberName(m) + (m.display_name ? ` "${m.display_name}"` : "");
          if (seated(m.id)) right.textContent = "redan med vid bordet";
          else if (o.similar) right.textContent = "menade du?";
          else if (m.ltu_id) right.textContent = m.ltu_id;
        }
        li.append(left, right);
        li.addEventListener("mousedown", (e) => {
          e.preventDefault();
          choose(o);
        });
        suggest.append(li);
      });
      suggest.hidden = !options.length;
      input.setAttribute("aria-expanded", String(!suggest.hidden));
    }

    function add(memberId) {
      state.seats.push({ member: memberId, wipes: 0 });
      input.value = "";
      changed();
      input.focus();
    }

    async function choose(o) {
      closeSuggest();
      addError.hidden = true;
      if (o.create) {
        const result = await memberDialog(data, null, o.create);
        if (!result) return input.focus();
        data = result.data;
        return add(result.member.id);
      }
      if (seated(o.member.id)) return showAddError(`${memberName(o.member)} är redan med vid bordet.`);
      add(o.member.id);
    }

    input.addEventListener("input", () => {
      addError.hidden = true;
      refresh();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!options.length) return;
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
        draw();
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (options[active]) choose(options[active]);
      } else if (e.key === "Escape") {
        closeSuggest();
      }
    });
    input.addEventListener("blur", () => setTimeout(closeSuggest, 120));

    // ---------- save ----------

    function showErrors(errors) {
      const box = $("te-errors");
      const ul = document.createElement("ul");
      errors.forEach((msg) => ul.append(Object.assign(document.createElement("li"), { textContent: msg })));
      box.replaceChildren(document.createTextNode("Kunde inte spara:"), ul);
      box.hidden = false;
      box.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    const commitBtn = $("te-commit");
    commitBtn.addEventListener("click", async () => {
      $("te-errors").hidden = true;
      const errors = tableErrors(data, state.date, state.seats);
      if (errors.length) return showErrors(errors);
      let content;
      try {
        const note = cleanName(state.note);
        content = { ...(note ? { note } : {}), players: scoreSeats(state.seats) };
      } catch (e) {
        return showErrors([e.message]);
      }

      commitBtn.disabled = true;
      saving = true;
      let savedId;
      try {
        data = await save((d) => {
          if (editing && JSON.stringify(d.table(editId)) !== JSON.stringify(original)) {
            throw new UserError("Någon annan har ändrat bordet sedan du öppnade det. Ladda om sidan för att se deras version. Dina ändringar sparades inte.");
          }
          const errs = tableErrors(d, state.date, state.seats);
          if (errs.length) throw new UserError(errs.join("\n"));
          const n = editing && state.date === originalDate ? originalNumber : d.nextTableNumber(state.date);
          savedId = `${state.date}-${n}`;
          const changes = { [tablePath(savedId)]: content };
          let message = `Nytt bord: ${tableLabel(state.date, n)}`;
          if (editing) {
            message = `Ändrat bord: ${tableLabel(state.date, n)}`;
            if (savedId !== editId) {
              changes[tablePath(editId)] = null;
              message = `Flyttat bord: ${tableLabel(originalDate, originalNumber)} → ${tableLabel(state.date, n)}`;
            }
          }
          const details = resultLines(d, content.players);
          if (content.note) details.push(`Notering: ${content.note}`);
          return { changes, message, lps: d.lpsFor(editing ? [originalDate, state.date] : [state.date]), details };
        }, data);
        clearDraft();
        dirty = false;
        const n = Number(savedId.slice(11));
        if (editing) {
          flashNext(`Bord ${n} den ${shortDate(state.date)} är sparat. ${savedNote(data)}`);
          location.assign(`/admin/bord/#${savedId}`);
        } else {
          flashNext(`Bord ${n} den ${shortDate(state.date)} är sparat. ${savedNote(data)} Fyll i nästa bord nedan.`);
          location.assign(`/admin/bord/redigera/?datum=${state.date}`);
        }
      } catch (e) {
        saving = false;
        commitBtn.disabled = false;
        showErrors((e.message || String(e)).split("\n"));
      }
    });

    $("te-clear").addEventListener("click", () => {
      if (state.seats.length && !confirm("Rensa bordet?")) return;
      clearDraft();
      state = { date: state.date, note: "", seats: [] };
      noteEl.value = "";
      dirty = false;
      render();
    });

    render();
  },
  { points: true }
);
