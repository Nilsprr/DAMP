// Admin: overview. Current LP, latest tables and shortcuts.
import { $, h, longDate, start } from "./core.js";

start(async (data) => {
  const page = $("page");
  const period = data.currentPeriod();
  const lpTables = period ? data.tables.filter((t) => period.starts_on <= t.date && t.date <= period.ends_on) : [];
  const recent = data.tables.slice(0, 8);

  const kpi = (label, value, sub) => h("div", { class: "card" }, h("div", { class: "muted" }, label), h("div", { class: "stat-value" }, h("strong", {}, value)), sub ? h("div", { class: "muted" }, sub) : null);

  page.replaceChildren(
    h(
      "div",
      { class: "kpis" },
      kpi("Aktuellt LP", period ? period.label : "–", `${lpTables.length} bord`),
      kpi("Medlemmar", String(data.members.length)),
      kpi("Senaste bordet", recent.length ? longDate(recent[0].date) : "–")
    ),
    h(
      "div",
      { class: "grid-2", style: "margin-top:0" },
      h(
        "section",
        { class: "card" },
        h("div", { class: "card-head" }, h("h2", {}, "Senaste bord"), h("a", { class: "btn btn-sm", href: "/admin/bord/redigera/" }, "+ Nytt bord")),
        recent.length
          ? h(
              "table",
              { class: "data" },
              h("thead", {}, h("tr", {}, h("th", {}, "Datum"), h("th", { class: "num" }, "Bord"), h("th", { class: "num" }, "Spelare"), h("th", {}, "Vinnare"))),
              h(
                "tbody",
                {},
                recent.map((t) =>
                  h(
                    "tr",
                    {},
                    h("td", {}, h("a", { href: `/admin/bord/#${t.id}` }, longDate(t.date))),
                    h("td", { class: "num" }, t.number),
                    h("td", { class: "num" }, t.players.length),
                    h("td", {}, t.players.length ? data.memberName(t.players[0].member) : "–")
                  )
                )
              )
            )
          : h("p", { class: "placeholder" }, "Inga bord ännu.")
      ),
      h(
        "section",
        { class: "card" },
        h("h2", {}, "Så funkar det"),
        h(
          "div",
          { class: "prose" },
          h("p", {}, "Fyll i ett bord i taget när det är klart: spelarna i placeringsordning, 1:an överst. Poängen räknas ut direkt."),
          h("p", {}, data.user.dev ? "Lokalt skrivs ändringarna direkt till data/." : "Allt du sparar blir en ändring i DAMP:s GitHub-repo, och den publika sidan uppdateras ungefär en minut senare."),
          h("p", {}, "Alla ändringar loggas under ", h("a", { href: "/admin/historik/" }, "Historik"), ", med vem som gjorde dem och när."),
          h("p", {}, h("a", { href: "/" }, "Till den publika topplistan →"))
        )
      )
    )
  );
});
