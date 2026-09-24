// Admin: läsperioder. Create/edit date ranges, delete empty ones, and re-apply the
// current points function to an LP's tables ("Räkna om poäng").
import {
  $, PERIODS, UserError, busy, fmtPts, formDialog, h, notify, periodErrors, periodId, periodLabel, pointsChanges, save,
  savedNote, scoreSeats, start, tableLabel, tablePath, todayISO,
} from "./core.js";

start(
  async (initial) => {
    let data = initial;
    const page = $("page");

    const inPeriod = (p, date) => p.starts_on <= date && date <= p.ends_on;
    const tablesIn = (d, p) => d.tables.filter((t) => inPeriod(p, t.date));
    const manualIn = (d, p) => d.manual.filter((e) => inPeriod(p, e.date));
    const range = (p) => `${p.starts_on} – ${p.ends_on}`;

    function editDialog(period) {
      const thisYear = Number(todayISO().slice(0, 4));
      const baseYear = period ? period.start_year : Number(todayISO().slice(5, 7)) >= 7 ? thisYear : thisYear - 1;
      const years = [];
      for (let y = baseYear - 3; y <= baseYear + 3; y++) years.push([y, `${String(y % 100).padStart(2, "0")}/${String((y + 1) % 100).padStart(2, "0")}`]);
      formDialog({
        title: period ? `Redigera ${period.label}` : "Nytt LP",
        submitLabel: period ? "Spara" : "Skapa",
        fields: [
          { name: "start_year", label: "Läsår", type: "select", options: years, value: baseYear },
          { name: "lp", label: "LP", type: "select", options: [1, 2, 3, 4].map((n) => [n, `LP${n}`]), value: period ? period.lp : 1 },
          { name: "starts_on", label: "Startdatum", type: "date", required: true, value: period ? period.starts_on : "" },
          { name: "ends_on", label: "Slutdatum", type: "date", required: true, value: period ? period.ends_on : "", hint: "Bord hör till det LP vars datum de ligger inom. LP får inte överlappa." },
        ],
        onSubmit: async (v) => {
          const entry = { start_year: Number(v.start_year), lp: Number(v.lp), starts_on: v.starts_on, ends_on: v.ends_on };
          const build = (d) => {
            const periods = d.copy(PERIODS, []);
            const i = period ? periods.findIndex((p) => periodId(p) === period.id) : -1;
            if (period && i === -1) throw new UserError(`${period.label} har tagits bort av någon annan.`);
            const before = i === -1 ? null : periods[i];
            if (i === -1) periods.push(entry);
            else periods[i] = entry;
            const errors = periodErrors(periods, d);
            if (errors.length) throw new UserError(errors.join("\n"));
            periods.sort((a, b) => (a.starts_on < b.starts_on ? -1 : 1));
            if (!before) return { changes: { [PERIODS]: periods }, message: `Nytt LP: ${periodLabel(entry)}`, lps: [periodId(entry)], details: [range(entry)] };
            const details = [];
            if (periodLabel(before) !== periodLabel(entry)) details.push(`Namn: ${periodLabel(before)} → ${periodLabel(entry)}`);
            if (range(before) !== range(entry)) details.push(`Datum: ${range(before)} → ${range(entry)}`);
            if (!details.length) return null;
            return { changes: { [PERIODS]: periods }, message: `Ändrat LP: ${periodLabel(entry)}`, lps: [...new Set([periodId(before), periodId(entry)])], details };
          };
          build(data); // check before sending
          data = await save(build, data);
          notify(`${periodLabel(entry)} är sparat. ${savedNote(data)}`);
          render();
        },
      });
    }

    async function remove(period, button) {
      if (!confirm(`Radera ${period.label}?`)) return;
      await busy(
        button,
        async () => {
          data = await save((d) => {
            const p = d.period(period.id);
            if (!p) return null;
            if (tablesIn(d, p).length || manualIn(d, p).length) throw new UserError(`${period.label} har poäng och kan inte raderas.`);
            return {
              changes: { [PERIODS]: d.copy(PERIODS, []).filter((x) => periodId(x) !== period.id) },
              message: `Raderat LP: ${period.label}`,
              lps: [period.id],
              details: [range(period)],
            };
          }, data);
          notify(`${period.label} är raderat. ${savedNote(data)}`);
          render();
        },
        "Raderar…"
      );
    }

    /** Every table in `period` whose stored points differ from the current function, rescored. */
    function rescored(d, period) {
      const changes = {};
      const details = [];
      let players = 0;
      for (const t of tablesIn(d, period)) {
        const table = d.table(t.id);
        const diffs = pointsChanges(table);
        if (!diffs.length) continue;
        players += diffs.length;
        changes[tablePath(t.id)] = { ...table, players: scoreSeats(table.players) };
        diffs.forEach((x) => details.push(`${tableLabel(t.date, t.number)}, plats ${x.placement} (${d.memberName(x.member)}): ${fmtPts(x.stored)} → ${fmtPts(x.now)} p`));
      }
      return { changes, details, players };
    }

    async function recalc(period, button) {
      const { changes, players } = rescored(data, period);
      const tables = Object.keys(changes).length;
      if (!tables) return notify(`Alla poäng i ${period.label} stämmer redan med den nuvarande poängfunktionen.`);
      if (!confirm(`${players} resultat på ${tables} bord får nya poäng enligt den nuvarande poängfunktionen. Fortsätt?`)) return;
      await busy(
        button,
        async () => {
          data = await save((d) => {
            const r = rescored(d, period);
            if (!Object.keys(r.changes).length) return null;
            return {
              changes: r.changes,
              message: `Räknade om poäng i ${period.label}: ${r.players} resultat på ${Object.keys(r.changes).length} bord`,
              lps: [period.id],
              details: r.details,
            };
          }, data);
          notify(`Poängen i ${period.label} är omräknade. ${savedNote(data)}`);
          render();
        },
        "Räknar om…"
      );
    }

    function render() {
      const today = todayISO();
      page.replaceChildren(
        h(
          "section",
          { class: "card" },
          h("div", { class: "card-head" }, h("h2", {}, "Läsperioder"), h("button", { class: "btn btn-sm", type: "button", onclick: () => editDialog(null) }, "+ Nytt LP")),
          data.periods.length
            ? h(
                "div",
                { class: "table-scroll" },
                h(
                  "table",
                  { class: "data" },
                  h(
                    "thead",
                    {},
                    h("tr", {}, h("th", {}, "LP"), h("th", {}, "Start"), h("th", {}, "Slut"), h("th", { class: "num" }, "Bord"), h("th", { class: "num", title: "Poäng utan placering" }, "Manuella poäng"), h("th", {}))
                  ),
                  h(
                    "tbody",
                    {},
                    data.periods.map((p) => {
                      const tables = tablesIn(data, p).length;
                      const manual = manualIn(data, p).length;
                      const outdated = rescored(data, p).players;
                      return h(
                        "tr",
                        {},
                        h("td", {}, h("strong", {}, p.label), inPeriod(p, today) ? [" ", h("span", { class: "badge badge-active" }, "Pågår")] : null),
                        h("td", { class: "nowrap" }, p.starts_on),
                        h("td", { class: "nowrap" }, p.ends_on),
                        h("td", { class: "num" }, tables),
                        h("td", { class: "num" }, h("a", { href: `/admin/manuella-poang/?lp=${p.id}` }, manual)),
                        h(
                          "td",
                          { class: "num nowrap" },
                          h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => editDialog(p) }, "Redigera"),
                          tables
                            ? h(
                                "button",
                                { class: "btn btn-ghost btn-sm", type: "button", title: outdated ? `${outdated} resultat har gamla poäng` : "Alla poäng är aktuella", onclick: (e) => recalc(p, e.currentTarget) },
                                outdated ? `Räkna om poäng (${outdated})` : "Räkna om poäng"
                              )
                            : null,
                          !tables && !manual ? h("button", { class: "btn btn-danger btn-sm", type: "button", onclick: (e) => remove(p, e.currentTarget) }, "Radera") : null
                        )
                      );
                    })
                  )
                )
              )
            : h("p", { class: "placeholder" }, "Inga LP ännu. Skapa det första."),
          h(
            "p",
            { class: "muted small table-foot" },
            "Poängen räknas av points_for() i damp/scoring.py och sparas i varje bord. Efter en ändring där (och en ny deploy) behåller gamla bord sina poäng tills du trycker \"Räkna om poäng\". Manuella poäng påverkas inte."
          )
        )
      );
    }

    render();
  },
  { points: true }
);
