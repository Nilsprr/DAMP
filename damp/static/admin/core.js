// Shared admin code: loading and saving data through /admin/api, the points
// table, validation, formatting and small DOM helpers. Each admin page is a
// module that calls start(render).
//
// /admin/api is a Cloudflare Pages Function in production (it commits to GitHub,
// functions/admin/api/[[path]].js) and damp/devapi.py locally. Both answer:
//   GET  data     -> {version, files: {"members.json": [...], "tables/2026-09-22-1.json": {...}}, user}
//                 user = {email, expires} (Access session end, seconds), or {email, dev: true} locally
//   POST save     {base, message, lps, details, changes: {path: content | null}} -> {version, rebased}
//                 409 when a changed file was modified by someone else since `base`.
//                 The server logs {message, lps, details} in the history (damp/history.py).
//   GET  history  -> {events: [{at, by, message, lps, details?}]}, newest first

export class UserError extends Error {}

export const MEMBERS = "members.json";
export const PERIODS = "periods.json";
export const MANUAL = "manual-points.json";
export const NEWS = "news.json";
export const tablePath = (id) => `tables/${id}.json`;
const TABLE_FILE = /^tables\/(\d{4}-\d{2}-\d{2})-(\d+)\.json$/;

const yy = (n) => String(n % 100).padStart(2, "0");
export const periodId = (p) => `lp${p.lp}-${yy(p.start_year)}-${yy(p.start_year + 1)}`;
export const periodLabel = (p) => `LP${p.lp} ${yy(p.start_year)}/${yy(p.start_year + 1)}`;
/** 'lp1-26-27' -> 'LP1 26/27' (also for LPs that no longer exist). */
export const labelOfPeriodId = (id) => id.replace(/^lp(\d)-(\d\d)-(\d\d)$/, "LP$1 $2/$3");

// ---------- members ----------

/** 'Harald Malmström' */
export const memberName = (m) => (m.last_name ? `${m.first_name} ${m.last_name}` : m.first_name);
/** 'Oleksandra "Sasha" Pozniakova' */
export const fullName = (m) => [m.first_name, m.display_name ? `"${m.display_name}"` : null, m.last_name].filter(Boolean).join(" ");

/**
 * What the public site shows for each member (id -> name): the display name, else the
 * first name, with the last name's initial when two would show the same. Same rule as
 * assign_public_names in damp/store.py.
 */
export function publicNames(members) {
  const key = (s) => s.toLocaleLowerCase("sv");
  const count = (names) => names.reduce((c, n) => c.set(key(n), (c.get(key(n)) || 0) + 1), new Map());
  const base = new Map(members.map((m) => [m.id, m.display_name || m.first_name]));
  const first = count([...base.values()]);
  const out = new Map(
    members.map((m) => {
      const n = base.get(m.id);
      return [m.id, first.get(key(n)) > 1 && !m.display_name && m.last_name ? `${m.first_name} ${m.last_name[0]}.` : n];
    })
  );
  const second = count([...out.values()]);
  for (const m of members) {
    if (second.get(key(out.get(m.id))) > 1 && !m.display_name && m.last_name) out.set(m.id, memberName(m));
  }
  return out;
}

// ---------- data ----------

export class Data {
  constructor({ version, files, user }) {
    this.version = version;
    this.files = files;
    this.user = user || {};
    this.members = (files[MEMBERS] || []).slice().sort((a, b) => memberName(a).localeCompare(memberName(b), "sv"));
    this.memberById = new Map(this.members.map((m) => [m.id, m]));
    this.periods = (files[PERIODS] || [])
      .map((p) => ({ ...p, id: periodId(p), label: periodLabel(p) }))
      .sort((a, b) => (a.starts_on < b.starts_on ? 1 : -1)); // newest first
    this.tables = Object.keys(files)
      .map((p) => [p, p.match(TABLE_FILE)])
      .filter(([, m]) => m)
      .map(([p, m]) => ({ id: `${m[1]}-${m[2]}`, date: m[1], number: Number(m[2]), ...files[p] }))
      .sort((a, b) => (a.date === b.date ? b.number - a.number : a.date < b.date ? 1 : -1)); // newest first
    this.manual = files[MANUAL] || [];
    this.news = (files[NEWS] || []).slice().sort((a, b) => (a.published_at < b.published_at ? 1 : -1));
  }

  periodFor(date) {
    return this.periods.find((p) => p.starts_on <= date && date <= p.ends_on) || null;
  }

  period(id) {
    return this.periods.find((p) => p.id === id) || null;
  }

  /** LP ids covering `dates` (for the history). */
  lpsFor(dates) {
    return [...new Set(dates.map((d) => this.periodFor(d)).filter(Boolean).map((p) => p.id))];
  }

  /** The LP running today, else the latest one that has started, else the newest. */
  currentPeriod() {
    const t = todayISO();
    return this.periodFor(t) || this.periods.find((p) => p.starts_on <= t) || this.periods[0] || null;
  }

  table(id) {
    return this.files[tablePath(id)] || null;
  }

  tablesOn(date) {
    return this.tables.filter((t) => t.date === date).sort((a, b) => a.number - b.number);
  }

  nextTableNumber(date) {
    return Math.max(0, ...this.tablesOn(date).map((t) => t.number)) + 1;
  }

  memberName(id) {
    const m = this.memberById.get(id);
    return m ? memberName(m) : `okänd medlem #${id}`;
  }

  nextMemberId() {
    return Math.max(0, ...this.members.map((m) => m.id)) + 1;
  }

  /** Deep copy of a file's JSON, to build a changed version from. */
  copy(path, fallback = []) {
    const v = this.files[path];
    return structuredClone(v === undefined ? fallback : v);
  }

  withChanges(version, changes) {
    const files = { ...this.files };
    for (const [p, content] of Object.entries(changes)) {
      if (content === null) delete files[p];
      else files[p] = content;
    }
    return new Data({ version, files, user: this.user });
  }
}

/** Per member id: {tables, points, last} over all tables and manual points. */
export function memberUsage(data) {
  const use = new Map();
  const add = (id, date, points, table) => {
    const u = use.get(id) || { tables: 0, points: 0, last: null };
    if (table) u.tables += 1;
    u.points += points;
    if (!u.last || date > u.last) u.last = date;
    use.set(id, u);
  };
  data.tables.forEach((t) => t.players.forEach((s) => add(s.member, t.date, s.points, true)));
  data.manual.forEach((e) => add(e.member, e.date, e.points, false));
  return use;
}

// ---------- API ----------

const API = "/admin/api/";

async function call(path, { method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(API + path, {
      method,
      redirect: "manual", // an expired Cloudflare Access session answers with a redirect to its login page
      cache: "no-store",
      headers: { Accept: "application/json", ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new UserError("Kunde inte nå servern. Kontrollera anslutningen och försök igen.");
  }
  if (res.type === "opaqueredirect" || res.status === 401) {
    loggedOut();
    throw new UserError("Du är utloggad. Ladda om sidan och logga in igen.");
  }
  let json = null;
  try {
    json = await res.json();
  } catch (e) {}
  return { ok: res.ok, status: res.status, body: json };
}

export async function load() {
  const res = await call("data");
  if (!res.ok) throw new UserError((res.body && res.body.error) || `Kunde inte läsa datan (fel ${res.status}).`);
  return new Data(res.body);
}

/**
 * Save a change. `mutate(data)` builds it from `data` and returns
 *   {changes: {path: content | null}, message, lps = [], details = []}
 * (null content deletes; message/lps/details go in the history), or null when there
 * is nothing to save. If someone else saved one of those files in the meantime, the
 * data is reloaded and `mutate` runs again on the fresh data, so it should throw a
 * UserError when its change no longer makes sense. Returns the Data after the save.
 */
export async function save(mutate, data = null) {
  let current = data;
  for (let attempt = 0; attempt < 4; attempt++) {
    if (!current) current = await load();
    const change = await mutate(current);
    if (!change || !Object.keys(change.changes).length) return current;
    const { changes, message, lps = [], details = [] } = change;
    const res = await call("save", { method: "POST", body: { base: current.version, message, lps, details, changes } });
    if (res.ok) {
      // If the server put our commit on top of someone else's, our copy of other files is stale.
      return res.body.rebased ? await load() : current.withChanges(res.body.version, changes);
    }
    if (res.status === 409) {
      current = null;
      continue;
    }
    if (res.status === 422 && res.body && res.body.errors) throw new UserError("Ogiltig data:\n" + res.body.errors.join("\n"));
    throw new UserError((res.body && res.body.error) || `Kunde inte spara (fel ${res.status}).`);
  }
  throw new UserError("Någon annan sparar just nu. Vänta en stund och försök igen.");
}

export async function history() {
  const res = await call("history");
  if (!res.ok) throw new UserError((res.body && res.body.error) || `Kunde inte läsa historiken (fel ${res.status}).`);
  return res.body.events || [];
}

export function savedNote(data) {
  return data.user.dev ? "Sparat i data/." : "Sparat. live sidan lär ju updateras om en minut eller nåt";
}

// ---------- points (scoring.points_for, as a table built from Python) ----------

let pointsTable = null;

export async function loadPointsTable() {
  const res = await fetch("/admin/poang.json", { cache: "no-store" });
  if (!res.ok) throw new UserError("Kunde inte läsa poängtabellen.");
  pointsTable = await res.json();
}

export function pointsFor(placement, size, wipes = 0) {
  const v = pointsTable && pointsTable[size] && pointsTable[size][placement - 1] && pointsTable[size][placement - 1][wipes];
  if (v == null) throw new UserError(`Poäng saknas för plats ${placement} vid ett bord med ${size} spelare och ${wipes} wipes.`);
  return v;
}

/** Players in finishing order -> what a table file stores for them. */
export function scoreSeats(seats) {
  return seats.map((s, i) => ({ member: s.member, wipes: s.wipes || 0, points: pointsFor(i + 1, seats.length, s.wipes || 0) }));
}

/** Players whose stored points differ from what the current points function gives. */
export function pointsChanges(table) {
  const out = [];
  table.players.forEach((s, i) => {
    const now = pointsFor(i + 1, table.players.length, s.wipes || 0);
    if (now !== s.points) out.push({ placement: i + 1, member: s.member, stored: s.points, now });
  });
  return out;
}

/** '1. Harald Malmström: 8 p' lines for the history. */
export const resultLines = (data, players) => players.map((s, i) => `${i + 1}. ${data.memberName(s.member)}: ${fmtPts(s.points)} p`);

// ---------- validation (the build checks the same rules in damp/store.py) ----------

export const MIN_TABLE_SIZE = 2;

export function tableErrors(data, date, seats) {
  const errors = [];
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date || "")) errors.push("Välj ett datum.");
  else if (!data.periodFor(date)) errors.push(`Inget LP täcker ${date}. Skapa det under LP först.`);
  if (seats.length < MIN_TABLE_SIZE) errors.push(`Ett bord behöver minst ${MIN_TABLE_SIZE} spelare.`);
  const seen = new Set();
  seats.forEach((s) => {
    const m = data.memberById.get(s.member);
    if (!m) return errors.push(`Okänd medlem #${s.member}.`);
    if (seen.has(s.member)) errors.push(`${memberName(m)} är med två gånger.`);
    seen.add(s.member);
    const w = s.wipes || 0;
    if (!Number.isInteger(w) || w < 0 || w >= seats.length) errors.push(`Ogiltigt antal wipes för ${memberName(m)}.`);
  });
  return errors;
}

/** Date ranges of `periods` (raw periods.json entries): overlap errors, and dates left outside every LP. */
export function periodErrors(periods, data) {
  const errors = [];
  const sorted = periods.slice().sort((a, b) => (a.starts_on < b.starts_on ? -1 : 1));
  const labels = new Set();
  sorted.forEach((p, i) => {
    const label = periodLabel(p);
    if (labels.has(label)) errors.push(`${label} finns redan.`);
    labels.add(label);
    if (p.starts_on > p.ends_on) errors.push(`${label} slutar före den börjar.`);
    const next = sorted[i + 1];
    if (next && next.starts_on <= p.ends_on) errors.push(`${label} och ${periodLabel(next)} överlappar.`);
  });
  const covered = (d) => periods.some((p) => p.starts_on <= d && d <= p.ends_on);
  const orphans = new Set([...data.tables.map((t) => t.date), ...data.manual.map((e) => e.date)].filter((d) => !covered(d)));
  if (orphans.size) errors.push(`Då hamnar poäng utanför alla LP: ${[...orphans].sort().join(", ")}.`);
  return errors;
}

// ---------- names ----------

/** Lowercase, no accents: for search only. */
export const norm = (s) =>
  (s || "")
    .toLocaleLowerCase("sv")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .trim();

export const cleanName = (s) => (s || "").split(/\s+/).filter(Boolean).join(" ");

/** Same text as far as uniqueness goes (store.py compares casefolded). */
export const sameName = (a, b) => cleanName(a).toLocaleLowerCase("sv") === cleanName(b).toLocaleLowerCase("sv");

function distance(a, b) {
  const row = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    let prev = row[0];
    row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const cur = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = cur;
    }
  }
  return row[b.length];
}

const searchKeys = (m) => [memberName(m), m.display_name, m.ltu_id].filter(Boolean).map(norm);

/**
 * Members matching `q` (name, display name or LTU-id), best first: {member, rank} with
 * rank 0 = a name (or a word in it) starts with q, 1 = contains q, 2 = spelled similarly.
 */
export function searchMembers(members, q, limit = 8) {
  const k = norm(q);
  if (!k) return [];
  const hits = [];
  for (const m of members) {
    const keys = searchKeys(m);
    const words = keys.flatMap((n) => n.split(/\s+/));
    let rank = null;
    if (keys.some((n) => n.startsWith(k)) || words.some((w) => w.startsWith(k))) rank = 0;
    else if (keys.some((n) => n.includes(k))) rank = 1;
    else if (k.length >= 3 && (keys.some((n) => distance(n, k) <= (k.length > 6 ? 2 : 1)) || words.some((w) => distance(w, k) <= 1))) rank = 2;
    if (rank !== null) hits.push({ member: m, rank });
  }
  hits.sort((a, b) => a.rank - b.rank || memberName(a.member).localeCompare(memberName(b.member), "sv"));
  return hits.slice(0, limit);
}

/** The member `text` names exactly: full name, display name or LTU-id. */
export function memberByName(members, text) {
  return members.find((m) => [memberName(m), m.display_name, m.ltu_id].some((v) => v && sameName(v, text))) || null;
}

// ---------- formatting ----------

const WEEKDAYS = ["sön", "mån", "tis", "ons", "tor", "fre", "lör"];
const MONTHS = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
const asDate = (iso) => new Date(iso.slice(0, 10) + "T12:00:00Z");

export const fmtPts = (v) => Number(v).toLocaleString("sv-SE", { maximumFractionDigits: 2 });
export const shortDate = (iso) => `${asDate(iso).getUTCDate()} ${MONTHS[asDate(iso).getUTCMonth()]}`;
export function longDate(iso) {
  const d = asDate(iso);
  return `${WEEKDAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}
export const fmtDateTime = (iso) => new Date(iso).toLocaleString("sv-SE", { dateStyle: "medium", timeStyle: "short" });
/** 'tis 22 sep 2026, bord 2' */
export const tableLabel = (date, number) => `${longDate(date)}, bord ${number}`;

/** Today as YYYY-MM-DD in the viewer's time zone. */
export const todayISO = () => new Date().toLocaleDateString("sv-SE");

export function latestTuesday(iso) {
  const d = asDate(iso);
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 5) % 7));
  return d.toISOString().slice(0, 10);
}

/** '14,5' / '14.5' / '−2' -> number, or NaN. */
export const parsePoints = (s) => {
  const t = String(s || "").trim().replace(",", ".").replace("−", "-");
  return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : NaN;
};

// ---------- DOM ----------

export const $ = (id) => document.getElementById(id);

/** h("a", {href: "/", class: "btn", onclick: fn}, "text", child, [more]) */
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (["value", "checked", "disabled", "hidden", "selected"].includes(k)) el[k] = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat(Infinity)) {
    if (c != null && c !== false) el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

/** el.replaceChildren(), but skipping null/false like h() does (replaceChildren would print "null"). */
export function fill(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter((c) => c != null && c !== false));
}

export function notify(text, kind = "ok") {
  const box = $("admin-messages");
  const li = h("li", { class: `flash flash-${kind}` }, text);
  box.append(li);
  if (kind === "ok") setTimeout(() => li.remove(), 8000);
  li.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

export function showError(e) {
  if (!(e instanceof UserError)) console.error(e);
  notify(e instanceof UserError ? e.message : `Något gick fel: ${e && e.message ? e.message : e}`, "error");
}

const FLASH_KEY = "damp-admin-flash";

/** Show `text` on the next page load (after a redirect). */
export function flashNext(text) {
  try {
    sessionStorage.setItem(FLASH_KEY, text);
  } catch (e) {}
}

function showFlashed() {
  try {
    const text = sessionStorage.getItem(FLASH_KEY);
    if (text) notify(text);
    sessionStorage.removeItem(FLASH_KEY);
  } catch (e) {}
}

// The footer padlock (static/js/admin-lock.js) shows "open" until this time (ms).
const LOGIN_KEY = "damp-admin-until";
const DEV_LOGIN_MS = 12 * 3600e3;

function rememberLogin(user) {
  // user.expires = when the Cloudflare Access session ends (seconds); locally there is no session.
  const until = user.dev ? Date.now() + DEV_LOGIN_MS : (user.expires || 0) * 1000;
  try {
    localStorage.setItem(LOGIN_KEY, String(until));
  } catch (e) {}
  document.dispatchEvent(new Event("damp:adminlogin"));
}

function forgetLogin() {
  try {
    localStorage.removeItem(LOGIN_KEY);
  } catch (e) {}
  document.dispatchEvent(new Event("damp:adminlogin"));
}

function loggedOut() {
  $("admin-user").textContent = "Utloggad";
  forgetLogin();
}

/** Run `fn` with `button` disabled and showing "Sparar…"; errors are shown, not thrown. */
export async function busy(button, fn, label = "Sparar…") {
  const text = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try {
    return await fn();
  } catch (e) {
    showError(e);
  } finally {
    button.disabled = false;
    button.textContent = text;
  }
}

/**
 * A modal form. fields: [{name, label, type = "text", value, required, options: [[value, label]],
 * hint, attrs}]. onSubmit(values) may throw a UserError, shown in the dialog; otherwise it closes.
 * Resolves with onSubmit's result, or undefined if cancelled.
 */
export function formDialog({ title, fields, submitLabel = "Spara", onSubmit }) {
  return new Promise((resolve) => {
    let result;
    const error = h("div", { class: "error-box", hidden: true, role: "alert" });
    const inputs = {};
    const rows = fields.map((f) => {
      const id = `dlg-${f.name}`;
      let input;
      if (f.type === "select") {
        input = h("select", { id, name: f.name }, f.options.map(([v, l]) => h("option", { value: v, selected: String(v) === String(f.value) }, l)));
      } else if (f.type === "textarea") {
        input = h("textarea", { id, name: f.name, required: f.required, ...f.attrs });
        input.value = f.value ?? "";
      } else {
        input = h("input", { id, name: f.name, type: f.type || "text", required: f.required, value: f.value ?? "", ...f.attrs });
      }
      inputs[f.name] = input;
      return h("div", { class: "field" }, h("label", { for: id }, f.label), input, f.hint ? h("small", {}, f.hint) : null);
    });
    const submit = h("button", { class: "btn", type: "submit" }, submitLabel);
    const dialog = h(
      "dialog",
      {},
      h(
        "form",
        {
          method: "dialog",
          onsubmit: async (e) => {
            e.preventDefault();
            error.hidden = true;
            const values = Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value]));
            const text = submit.textContent;
            submit.disabled = true;
            submit.textContent = "Sparar…";
            try {
              result = await onSubmit(values);
              dialog.close();
            } catch (err) {
              if (!(err instanceof UserError)) console.error(err);
              error.textContent = err.message || String(err);
              error.hidden = false;
            } finally {
              submit.disabled = false;
              submit.textContent = text;
            }
          },
        },
        h("h2", {}, title),
        rows,
        error,
        h("div", { class: "form-actions" }, submit, h("button", { class: "btn btn-ghost", type: "button", onclick: () => dialog.close() }, "Avbryt"))
      )
    );
    dialog.addEventListener("close", () => {
      dialog.remove();
      resolve(result);
    });
    document.body.append(dialog);
    dialog.showModal();
  });
}

// ---------- page start ----------

export async function start(render, { points = false } = {}) {
  showFlashed();
  $("admin-logout").addEventListener("click", forgetLogin);
  try {
    const [data] = await Promise.all([load(), points ? loadPointsTable() : null]);
    rememberLogin(data.user);
    $("admin-user").textContent = data.user.dev ? "Lokalt, ingen inloggning" : `Inloggad som ${data.user.email}`;
    $("admin-logout").hidden = !!data.user.dev;
    $("admin-loading").hidden = true;
    $("admin-root").hidden = false;
    await render(data);
  } catch (e) {
    $("admin-loading").replaceChildren(h("p", { class: "placeholder" }, "Kunde inte ladda admin."));
    showError(e);
  }
}
