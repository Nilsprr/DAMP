// Admin: members. Add, edit (name, LTU-id, display name, member since), delete members without points.
import { $, MEMBERS, UserError, busy, fill, fmtPts, h, memberName, memberUsage, norm, notify, publicNames, save, savedNote, shortDate, start } from "./core.js";
import { memberDialog } from "./member-form.js";

start(async (initial) => {
  let data = initial;
  const page = $("page");
  let query = "";

  async function edit(member) {
    const result = await memberDialog(data, member);
    if (!result) return;
    data = result.data;
    notify(`${memberName(result.member)} är ${member ? "sparad" : "tillagd"}. ${savedNote(data)}`);
    renderRows();
  }

  async function remove(member, button) {
    if (!confirm(`Radera ${memberName(member)} permanent?`)) return;
    await busy(
      button,
      async () => {
        data = await save((d) => {
          if (memberUsage(d).has(member.id)) throw new UserError(`${memberName(member)} har fått poäng och kan inte raderas.`);
          if (!d.memberById.has(member.id)) return null;
          return {
            changes: { [MEMBERS]: d.copy(MEMBERS, []).filter((m) => m.id !== member.id) },
            message: `Raderad medlem: ${memberName(member)}`,
            details: [member.ltu_id ? `LTU-id: ${member.ltu_id}` : null].filter(Boolean),
          };
        }, data);
        notify(`${memberName(member)} är raderad. ${savedNote(data)}`);
        renderRows();
      },
      "Raderar…"
    );
  }

  const tbody = h("tbody");
  const count = h("span", { class: "muted" });
  const fmtDate = (iso) => (iso ? `${shortDate(iso)} ${iso.slice(0, 4)}` : "–");

  function renderRows() {
    const usage = memberUsage(data);
    const shownAs = publicNames(data.members);
    const q = norm(query);
    const shown = data.members.filter((m) => !q || [memberName(m), m.display_name, m.ltu_id].some((v) => v && norm(v).includes(q)));
    count.textContent = `(${data.members.length})`;
    fill(
      tbody,
      ...shown.map((m) => {
        const u = usage.get(m.id);
        return h(
          "tr",
          {},
          h("td", {}, memberName(m), m.last_name ? null : [" ", h("span", { class: "badge badge-soon", title: "Efternamn saknas" }, "Ofullständig")]),
          h("td", { class: "nowrap muted" }, m.ltu_id || "–"),
          h("td", { class: "nowrap" }, shownAs.get(m.id)),
          h("td", { class: "nowrap hide-sm" }, fmtDate(m.joined_on)),
          h("td", { class: "num" }, u ? u.tables : 0),
          h("td", { class: "num" }, u ? fmtPts(u.points) : 0),
          h(
            "td",
            { class: "num nowrap" },
            h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => edit(m) }, "Redigera"),
            u ? null : h("button", { class: "btn btn-danger btn-sm", type: "button", onclick: (e) => remove(m, e.currentTarget) }, "Radera")
          )
        );
      }),
      shown.length ? [] : h("tr", {}, h("td", { colspan: 7, class: "muted" }, "Inga medlemmar matchar."))
    );
  }

  page.replaceChildren(
    h(
      "section",
      { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, "Medlemmar ", count), h("button", { class: "btn btn-sm", type: "button", onclick: () => edit(null) }, "+ Ny medlem")),
      h(
        "div",
        { class: "toolbar" },
        h("input", {
          type: "search",
          placeholder: "Sök namn eller LTU-id",
          "aria-label": "Sök medlem",
          oninput: (e) => {
            query = e.target.value;
            renderRows();
          },
        })
      ),
      h(
        "div",
        { class: "table-scroll" },
        h(
          "table",
          { class: "data" },
          h(
            "thead",
            {},
            h(
              "tr",
              {},
              h("th", {}, "Namn"),
              h("th", {}, "LTU-id"),
              h("th", { title: "Namnet på den publika topplistan" }, "Visas som"),
              h("th", { class: "hide-sm" }, "Medlem sedan"),
              h("th", { class: "num", title: "Spelade bord, alla LP" }, "Bord"),
              h("th", { class: "num", title: "Alla LP" }, "Poäng"),
              h("th", {})
            )
          ),
          tbody
        )
      ),
      h(
        "p",
        { class: "muted small table-foot" },
        "Topplistan visar visningsnamnet, annars förnamnet (med efternamnets initial om två har samma). Medlemmar med poäng kan inte raderas. Nya medlemmar kan också läggas till direkt när du fyller i ett bord."
      )
    )
  );
  renderRows();
});
