// Admin: points without placements (e.g. totals from a spreadsheet), per LP: add, edit, delete.
// Importing many at once is done with the import-points CLI command (damp/manual.py).
import {
  $, MANUAL, UserError, busy, cleanName, fill, fmtPts, formDialog, h, memberByName, memberName, notify, parsePoints, save,
  savedNote, searchMembers, start, todayISO,
} from "./core.js";

const sameEntry = (a, b) => JSON.stringify(a) === JSON.stringify(b);

start(async (initial) => {
  let data = initial;
  const page = $("page");
  const wanted = new URLSearchParams(location.search).get("lp");
  let period = data.period(wanted) || data.currentPeriod();

  const inPeriod = (e) => period && period.starts_on <= e.date && e.date <= period.ends_on;
  const defaultDate = () => {
    const t = todayISO();
    return period.starts_on <= t && t <= period.ends_on ? t : period.ends_on;
  };
  const describe = (d, e) => `${d.memberName(e.member)}: ${fmtPts(e.points)} p (${e.date})`;

  /** Differences between two entries, for the history. */
  function differences(d, a, b) {
    const out = [];
    if (a.member !== b.member) out.push(`Medlem: ${d.memberName(a.member)} → ${d.memberName(b.member)}`);
    if (a.points !== b.points) out.push(`Poäng: ${fmtPts(a.points)} → ${fmtPts(b.points)}`);
    if (a.date !== b.date) out.push(`Datum: ${a.date} → ${b.date}`);
    if ((a.note || "") !== (b.note || "")) out.push(`Notering: ${a.note || "–"} → ${b.note || "–"}`);
    return out;
  }

  /** Save one changed entry. `original` identifies it (entries have no id); null = add `entry`, entry null = delete. */
  async function saveEntry(original, entry) {
    data = await save((d) => {
      const manual = d.copy(MANUAL, []);
      let message, details;
      if (original) {
        const i = manual.findIndex((e) => sameEntry(e, original));
        if (i === -1) throw new UserError("Posten har ändrats eller tagits bort av någon annan. Ladda om sidan.");
        if (entry) {
          details = differences(d, original, entry);
          if (!details.length) return null;
          manual[i] = entry;
          message = `Ändrade manuella poäng för ${d.memberName(entry.member)}`;
        } else {
          manual.splice(i, 1);
          message = `Tog bort manuella poäng för ${d.memberName(original.member)}`;
          details = [describe(d, original)];
        }
      } else {
        manual.push(entry);
        message = `Manuella poäng för ${d.memberName(entry.member)}`;
        details = [describe(d, entry)];
      }
      if (entry && entry.note && !original) details.push(`Notering: ${entry.note}`);
      manual.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
      const dates = [original && original.date, entry && entry.date].filter(Boolean);
      return { changes: { [MANUAL]: manual }, message, lps: d.lpsFor(dates), details };
    }, data);
  }

  function entryFrom(v) {
    const m = memberByName(data.members, v.member);
    if (!m) {
      const alike = searchMembers(data.members, v.member, 3).map((x) => memberName(x.member));
      throw new UserError(`Ingen medlem heter "${cleanName(v.member)}".` + (alike.length ? ` Menade du ${alike.join(", ")}?` : " Lägg till personen under Medlemmar först."));
    }
    const points = parsePoints(v.points);
    if (Number.isNaN(points)) throw new UserError("Ange poäng som ett tal, t.ex. 14,5.");
    if (!(period.starts_on <= v.date && v.date <= period.ends_on)) throw new UserError(`Datumet ska ligga i ${period.label} (${period.starts_on} – ${period.ends_on}).`);
    const note = cleanName(v.note);
    return { date: v.date, member: m.id, points, ...(note ? { note } : {}) };
  }

  function editDialog(original) {
    formDialog({
      title: original ? "Redigera manuella poäng" : `Lägg till poäng i ${period.label}`,
      submitLabel: original ? "Spara" : "Lägg till",
      fields: [
        { name: "member", label: "Medlem", required: true, value: original ? data.memberName(original.member) : "", attrs: { list: "mp-members", autocomplete: "off" } },
        { name: "date", label: "Datum", type: "date", required: true, value: original ? original.date : defaultDate(), attrs: { min: period.starts_on, max: period.ends_on } },
        { name: "points", label: "Poäng", required: true, value: original ? fmtPts(original.points) : "", attrs: { inputmode: "decimal", placeholder: "t.ex. 14,5" } },
        { name: "note", label: "Notering (valfritt)", value: original ? original.note || "" : "", attrs: { maxlength: 200 } },
      ],
      onSubmit: async (v) => {
        await saveEntry(original, entryFrom(v));
        notify(`Sparat. ${savedNote(data)}`);
        render();
      },
    });
  }

  async function remove(entry, button) {
    const name = data.memberName(entry.member);
    if (!confirm(`Ta bort ${name}s ${fmtPts(entry.points)} poäng ${entry.date}?`)) return;
    await busy(
      button,
      async () => {
        await saveEntry(entry, null);
        notify(`Borttaget. ${savedNote(data)}`);
        render();
      },
      "Tar bort…"
    );
  }

  const card = h("section", { class: "card" });
  const datalist = h("datalist", { id: "mp-members" });

  function render() {
    datalist.replaceChildren(...data.members.map((m) => h("option", { value: memberName(m) })));
    if (!period) {
      card.replaceChildren(h("p", { class: "placeholder" }, "Skapa ett LP först."));
      return;
    }
    const entries = data.manual.filter(inPeriod);
    const total = entries.reduce((a, e) => a + e.points, 0);
    fill(
      card,
      h(
        "div",
        { class: "card-head" },
        h("h2", {}, `Manuella poäng · ${period.label}`),
        h(
          "div",
          { class: "form-actions", style: "margin:0" },
          h(
            "select",
            {
              "aria-label": "Läsperiod",
              onchange: (e) => {
                period = data.period(e.target.value);
                history.replaceState(null, "", `?lp=${period.id}`);
                render();
              },
            },
            data.periods.map((p) => h("option", { value: p.id, selected: p.id === period.id }, p.label))
          ),
          h("button", { class: "btn btn-sm", type: "button", onclick: () => editDialog(null) }, "+ Lägg till")
        )
      ),
      h("p", { class: "muted" }, "Poäng på ett datum utan placering, t.ex. totaler från ett kalkylark. De räknas i topplistan och grafen, men inte som spelade bord, vinster, snittplacering eller wipes."),
      entries.length
        ? h(
            "div",
            { class: "table-scroll" },
            h(
              "table",
              { class: "data" },
              h("thead", {}, h("tr", {}, h("th", {}, "Datum"), h("th", {}, "Medlem"), h("th", { class: "num" }, "Poäng"), h("th", {}, "Notering"), h("th", {}))),
              h(
                "tbody",
                {},
                entries.map((e) =>
                  h(
                    "tr",
                    {},
                    h("td", { class: "nowrap" }, e.date),
                    h("td", {}, data.memberName(e.member)),
                    h("td", { class: "num" }, fmtPts(e.points)),
                    h("td", { class: "muted" }, e.note || ""),
                    h(
                      "td",
                      { class: "num nowrap" },
                      h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => editDialog(e) }, "Redigera"),
                      h("button", { class: "btn btn-danger btn-sm", type: "button", onclick: (ev) => remove(e, ev.currentTarget) }, "Ta bort")
                    )
                  )
                )
              )
            )
          )
        : h("p", { class: "placeholder" }, `Inga manuella poäng i ${period.label}.`),
      entries.length ? h("p", { class: "muted small table-foot" }, `${entries.length} poster · totalt ${fmtPts(total)} poäng`) : null
    );
  }

  page.replaceChildren(datalist, card);
  render();
});
