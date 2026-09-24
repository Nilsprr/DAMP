// Admin: all tables, newest first. A row opens to show the players; edit or delete from there.
import { $, UserError, busy, fmtPts, h, longDate, notify, resultLines, save, savedNote, start, tableLabel, tablePath } from "./core.js";

start(async (initial) => {
  let data = initial;
  const page = $("page");

  function detail(t) {
    return h(
      "div",
      { class: "table-detail" },
      h(
        "table",
        { class: "data" },
        h("thead", {}, h("tr", {}, h("th", { class: "num" }, "#"), h("th", {}, "Spelare"), h("th", { class: "num" }, "Wipes"), h("th", { class: "num" }, "Poäng"))),
        h(
          "tbody",
          {},
          t.players.map((s, i) =>
            h("tr", {}, h("td", { class: "num rank" }, i + 1), h("td", {}, data.memberName(s.member)), h("td", { class: "num" }, s.wipes || 0), h("td", { class: "num" }, h("strong", {}, fmtPts(s.points))))
          )
        )
      ),
      h(
        "div",
        { class: "form-actions" },
        h("a", { class: "btn btn-sm", href: `/admin/bord/redigera/?id=${t.id}` }, "Redigera"),
        h("button", { class: "btn btn-danger btn-sm", type: "button", onclick: (e) => remove(t, e.currentTarget) }, "Radera bordet")
      )
    );
  }

  async function remove(t, button) {
    if (!confirm(`Radera ${tableLabel(t.date, t.number)} och dess resultat?`)) return;
    await busy(
      button,
      async () => {
        const original = JSON.stringify(data.table(t.id));
        data = await save((d) => {
          const current = d.table(t.id);
          if (!current) return null; // already gone
          if (JSON.stringify(current) !== original) throw new UserError("Någon annan har ändrat bordet. Ladda om sidan och försök igen.");
          return {
            changes: { [tablePath(t.id)]: null },
            message: `Raderat bord: ${tableLabel(t.date, t.number)}`,
            lps: d.lpsFor([t.date]),
            details: resultLines(d, current.players),
          };
        }, data);
        notify(`${tableLabel(t.date, t.number)} är raderat. ${savedNote(data)}`);
        render();
      },
      "Raderar…"
    );
  }

  function render() {
    const open = decodeURIComponent(location.hash.slice(1));
    const rows = data.tables.map((t) => {
      const period = data.periodFor(t.date);
      const row = h(
        "tr",
        { class: "clickable", id: `bord-${t.id}`, "aria-expanded": "false" },
        h("td", { class: "nowrap" }, h("button", { type: "button", class: "player-btn" }, longDate(t.date))),
        h("td", { class: "num" }, t.number),
        h("td", { class: "nowrap" }, period ? period.label : "–"),
        h("td", { class: "num" }, t.players.length),
        h("td", {}, t.players.length ? data.memberName(t.players[0].member) : "–"),
        h("td", { class: "muted" }, t.note || "")
      );
      const detailRow = h("tr", { class: "detail-row", hidden: true }, h("td", { colspan: 6 }, detail(t)));
      const toggle = (show) => {
        detailRow.hidden = !show;
        row.setAttribute("aria-expanded", String(show));
        row.classList.toggle("is-selected", show);
      };
      row.addEventListener("click", () => {
        const show = detailRow.hidden;
        toggle(show);
        history.replaceState(null, "", show ? `#${t.id}` : location.pathname);
      });
      if (open === t.id) {
        toggle(true);
        setTimeout(() => row.scrollIntoView({ block: "start", behavior: "smooth" }), 50);
      }
      return [row, detailRow];
    });

    page.replaceChildren(
      h(
        "section",
        { class: "card" },
        h("div", { class: "card-head" }, h("h2", {}, "Bord ", h("span", { class: "muted" }, `(${data.tables.length})`)), h("a", { class: "btn btn-sm", href: "/admin/bord/redigera/" }, "+ Nytt bord")),
        data.tables.length
          ? h(
              "div",
              { class: "table-scroll" },
              h(
                "table",
                { class: "data" },
                h(
                  "thead",
                  {},
                  h("tr", {}, h("th", {}, "Datum"), h("th", { class: "num" }, "Bord"), h("th", {}, "LP"), h("th", { class: "num" }, "Spelare"), h("th", {}, "Vinnare"), h("th", {}, "Notering"))
                ),
                h("tbody", {}, rows)
              )
            )
          : h("p", { class: "placeholder" }, "Inga bord ännu.")
      )
    );
  }

  render();
});
