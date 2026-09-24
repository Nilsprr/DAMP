// Admin: news posts. Write in Markdown with a live preview; the public site renders
// the same text with Python-Markdown (damp/util.py), so the preview is close but not exact.
import { marked } from "../vendor/marked.esm.js";
import { $, NEWS, UserError, busy, h, longDate, notify, save, savedNote, start } from "./core.js";

marked.use({ breaks: true, gfm: true });

const nowLocal = () => {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16); // YYYY-MM-DDTHH:MM, local time
};

start(async (initial) => {
  let data = initial;
  const page = $("page");
  let editing = null; // post being edited, or null for a new one

  const title = h("input", { id: "news-title", type: "text", required: true, maxlength: 200 });
  const published = h("input", { id: "news-date", type: "datetime-local", required: true });
  const body = h("textarea", { id: "news-body", required: true });
  const previewEl = h("div", { class: "prose" });
  const formTitle = h("h2");
  const saveBtn = h("button", { class: "btn", type: "submit" });
  const cancelBtn = h("button", { class: "btn btn-ghost", type: "button", onclick: () => edit(null) }, "Avbryt");

  function renderPreview() {
    previewEl.innerHTML = body.value.trim() ? marked.parse(body.value) : '<p class="placeholder">Förhandsvisningen syns här.</p>';
  }
  body.addEventListener("input", renderPreview);

  function edit(post) {
    editing = post;
    formTitle.textContent = post ? "Redigera nyhet" : "Ny nyhet";
    saveBtn.textContent = post ? "Spara" : "Publicera";
    cancelBtn.hidden = !post;
    title.value = post ? post.title : "";
    published.value = post ? post.published_at.slice(0, 16) : nowLocal();
    body.value = post ? post.body : "";
    renderPreview();
    if (post) title.focus();
  }

  async function submit(e) {
    e.preventDefault();
    await busy(saveBtn, async () => {
      const post = { title: title.value.trim(), published_at: published.value, body: body.value.trim() };
      if (!post.title || !post.body) throw new UserError("Titel och text behövs.");
      const original = editing;
      data = await save((d) => {
        const news = d.copy(NEWS, []);
        if (original) {
          const i = news.findIndex((n) => n.id === original.id);
          if (i === -1) throw new UserError("Nyheten har tagits bort av någon annan.");
          const before = news[i];
          news[i] = { id: original.id, ...post };
          const details = [];
          if (before.title !== post.title) details.push(`Titel: ${before.title} → ${post.title}`);
          if (before.published_at !== post.published_at) details.push(`Publicerad: ${before.published_at} → ${post.published_at}`);
          if (before.body !== post.body) details.push("Texten ändrades.");
          if (!details.length) return null;
          return { changes: { [NEWS]: news }, message: `Ändrad nyhet: ${post.title}`, details };
        }
        news.push({ id: Math.max(0, ...news.map((n) => n.id)) + 1, ...post });
        return { changes: { [NEWS]: news }, message: `Ny nyhet: ${post.title}` };
      }, data);
      notify(`${original ? "Nyheten är sparad" : "Nyheten är publicerad"}. ${savedNote(data)}`);
      edit(null);
      renderList();
    });
  }

  async function remove(post, button) {
    if (!confirm(`Radera nyheten "${post.title}"?`)) return;
    await busy(
      button,
      async () => {
        data = await save(
          (d) => ({ changes: { [NEWS]: d.copy(NEWS, []).filter((n) => n.id !== post.id) }, message: `Raderad nyhet: ${post.title}` }),
          data
        );
        if (editing && editing.id === post.id) edit(null);
        notify(`Nyheten är raderad. ${savedNote(data)}`);
        renderList();
      },
      "Raderar…"
    );
  }

  const listCard = h("section", { class: "card" });

  function renderList() {
    listCard.replaceChildren(
      h("div", { class: "card-head" }, h("h2", {}, "Nyheter"), h("button", { class: "btn btn-sm", type: "button", onclick: () => edit(null) }, "+ Ny nyhet")),
      data.news.length
        ? h(
            "table",
            { class: "data" },
            h("thead", {}, h("tr", {}, h("th", {}, "Titel"), h("th", {}, "Publicerad"), h("th", {}))),
            h(
              "tbody",
              {},
              data.news.map((n) =>
                h(
                  "tr",
                  {},
                  h("td", {}, n.title),
                  h("td", { class: "nowrap" }, longDate(n.published_at)),
                  h(
                    "td",
                    { class: "num nowrap" },
                    h("a", { class: "btn btn-ghost btn-sm", href: `/nyheter/${n.id}/` }, "Visa"),
                    h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => edit(n) }, "Redigera"),
                    h("button", { class: "btn btn-danger btn-sm", type: "button", onclick: (e) => remove(n, e.currentTarget) }, "Radera")
                  )
                )
              )
            )
          )
        : h("p", { class: "placeholder" }, "Inga nyheter ännu.")
    );
  }

  page.replaceChildren(
    listCard,
    h(
      "div",
      { class: "grid-2" },
      h(
        "section",
        { class: "card" },
        formTitle,
        h(
          "form",
          { onsubmit: submit },
          h("div", { class: "field" }, h("label", { for: "news-title" }, "Titel"), title),
          h("div", { class: "field" }, h("label", { for: "news-date" }, "Publicerad"), published),
          h("div", { class: "field" }, h("label", { for: "news-body" }, "Text"), body, h("small", {}, 'Markdown: **fet**, *kursiv*, [länk](https://…), listor med "- ".')),
          h("div", { class: "form-actions" }, saveBtn, cancelBtn)
        )
      ),
      h("section", { class: "card" }, h("h2", {}, "Förhandsvisning"), previewEl)
    )
  );
  edit(null);
  renderList();
});
