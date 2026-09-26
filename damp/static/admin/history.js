// Admin: the change log. Every save (tables, members, LP, manual points, news) is an event;
// filter on an LP to see only what touched it, including when it was created. Commits made
// outside the admin (code changes and the like) are listed too, marked with their id.
import { $, fill, fmtDateTime, h, history as loadHistory, labelOfPeriodId, start } from "./core.js";

const PAGE = 100;

start(async (data) => {
  const page = $("page");
  const { events, commits } = await loadHistory();
  // Newest first; the sort is stable, so an event stays above a commit from the same second.
  const entries = [...events, ...commits].sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));
  const wanted = new URLSearchParams(location.search).get("lp") || "";

  // Every LP that exists or appears in the log (a deleted LP can still be looked up), newest first.
  const lpIds = [...new Set([...data.periods.map((p) => p.id), ...events.flatMap((e) => e.lps || [])])].sort((a, b) => {
    const key = (id) => id.slice(4, 6) + id.slice(2, 3); // start year, then LP number
    return key(b).localeCompare(key(a));
  });

  let lp = lpIds.includes(wanted) ? wanted : "";
  let shown = PAGE;
  const list = h("div");

  function render() {
    const matching = lp ? entries.filter((e) => (e.lps || []).includes(lp)) : entries;
    fill(
      list,
      matching.length
        ? h(
            "div",
            { class: "table-scroll" },
            h(
              "table",
              { class: "data history" },
              h("thead", {}, h("tr", {}, h("th", {}, "När"), h("th", {}, "Vem"), h("th", {}, "Händelse"), h("th", {}, "LP"))),
              h(
                "tbody",
                {},
                matching.slice(0, shown).map((e) =>
                  h(
                    "tr",
                    {},
                    h("td", { class: "nowrap" }, fmtDateTime(e.at)),
                    h("td", { class: "nowrap muted" }, e.by),
                    h(
                      "td",
                      {},
                      h("div", {}, e.sha ? h("code", { class: "commit-sha", title: e.sha }, e.sha.slice(0, 7)) : null, e.message),
                      e.details && e.details.length ? h("ul", { class: "history-details" }, e.details.map((d) => h("li", {}, d))) : null
                    ),
                    h("td", { class: "nowrap" }, (e.lps || []).map((id) => h("span", { class: "badge badge-lp" }, labelOfPeriodId(id))))
                  )
                )
              )
            )
          )
        : h("p", { class: "placeholder" }, lp ? `Inga händelser för ${labelOfPeriodId(lp)}.` : "Ingen historik ännu."),
      matching.length > shown
        ? h("div", { class: "form-actions" }, h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => ((shown += PAGE), render()) }, `Visa fler (${matching.length - shown} till)`))
        : null
    );
  }

  const select = h(
    "select",
    {
      "aria-label": "Filtrera på LP",
      onchange: (e) => {
        lp = e.target.value;
        shown = PAGE;
        window.history.replaceState(null, "", lp ? `?lp=${lp}` : location.pathname);
        render();
      },
    },
    h("option", { value: "", selected: !lp }, "Alla händelser"),
    lpIds.map((id) => h("option", { value: id, selected: id === lp }, labelOfPeriodId(id)))
  );

  page.replaceChildren(
    h(
      "section",
      { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, "Historik"), select),
      list
    )
  );
  render();
});
