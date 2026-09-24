// The admin API in production: a Cloudflare Pages Function at /admin/api/*, behind
// Cloudflare Access. It reads data/ from the GitHub repo and saves admin changes as
// commits, which trigger a rebuild of the site. Every save also appends an event to the
// change log in data/history/ (format in damp/history.py) in the same commit. Locally,
// damp/devapi.py implements the same contract (see the top of damp/static/admin/core.js).
//
// Settings (Pages → Settings → Variables and Secrets; see docs/cloudflare.md):
//   ACCESS_TEAM_DOMAIN   e.g. damp.cloudflareaccess.com
//   ACCESS_AUD           the Access application's "Application Audience (AUD) Tag"
//   ADMIN_EMAILS         comma-separated allowlist (checked here as well as by the Access policy)
//   GITHUB_REPO          owner/name, e.g. damp-ltu/damp
//   GITHUB_BRANCH        default "master"
//   GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, GITHUB_APP_PRIVATE_KEY   (docs/github-app.md)
//     or GITHUB_TOKEN    a fine-grained personal access token with Contents: read and write

// Every file the admin may write; the same pattern as DATA_PATH in damp/store.py.
const DATA_PATH = /^(members|periods|manual-points|news)\.json$|^tables\/\d{4}-\d{2}-\d{2}-[1-9]\d*\.json$/;
const LP_ID = /^lp[1-4]-\d{2}-\d{2}$/;
const MAX_BODY = 1_000_000;
const UA = "damp-admin";

export async function onRequest({ request, env, params }) {
  const path = [].concat(params.path || []).join("/");
  try {
    const user = await authenticate(request, env);
    checkGithubSettings(env);
    if (request.method === "GET" && path === "data") return json(await getData(env, user));
    if (request.method === "GET" && path === "history") return json(await getHistory(env));
    if (request.method === "POST" && path === "save") return await postSave(request, env, user);
    return json({ error: "Finns inte." }, 404);
  } catch (e) {
    if (e instanceof HttpError) return json({ error: e.message }, e.status);
    console.error(e);
    return json({ error: "Serverfel. Försök igen om en stund." }, 500);
  }
}

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

// ---------- base64url ----------

function b64urlDecode(s) {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(s.length / 4) * 4, "=");
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

function b64urlEncode(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

const decodeJson = (s) => JSON.parse(new TextDecoder().decode(b64urlDecode(s)));

// ---------- Cloudflare Access ----------

let accessCerts = null; // {team, keys, at}

async function accessKeys(team, refresh = false) {
  if (!refresh && accessCerts && accessCerts.team === team && Date.now() - accessCerts.at < 3600_000) return accessCerts.keys;
  const res = await fetch(`https://${team}/cdn-cgi/access/certs`);
  if (!res.ok) throw new Error(`Access certs: ${res.status}`);
  accessCerts = { team, keys: (await res.json()).keys || [], at: Date.now() };
  return accessCerts.keys;
}

function cookie(request, name) {
  const m = (request.headers.get("Cookie") || "").match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`));
  return m ? m[1] : null;
}

/** Verify the Access JWT (signature, audience, issuer, expiry) and the email allowlist. */
async function authenticate(request, env) {
  if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD || !env.ADMIN_EMAILS) {
    throw new HttpError(500, "Admin är inte färdigkonfigurerad (Cloudflare Access-inställningar saknas).");
  }
  const token = request.headers.get("Cf-Access-Jwt-Assertion") || cookie(request, "CF_Authorization");
  if (!token) throw new HttpError(401, "Inte inloggad.");
  const parts = token.split(".");
  if (parts.length !== 3) throw new HttpError(401, "Ogiltig inloggning.");
  let header, payload;
  try {
    header = decodeJson(parts[0]);
    payload = decodeJson(parts[1]);
  } catch (e) {
    throw new HttpError(401, "Ogiltig inloggning.");
  }
  if (header.alg !== "RS256") throw new HttpError(401, "Ogiltig inloggning.");

  const team = env.ACCESS_TEAM_DOMAIN;
  let jwk = (await accessKeys(team)).find((k) => k.kid === header.kid);
  if (!jwk) jwk = (await accessKeys(team, true)).find((k) => k.kid === header.kid); // keys rotate
  if (!jwk) throw new HttpError(401, "Ogiltig inloggning.");
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64urlDecode(parts[2]), new TextEncoder().encode(`${parts[0]}.${parts[1]}`));
  const now = Date.now() / 1000;
  if (
    !valid ||
    ![].concat(payload.aud).includes(env.ACCESS_AUD) ||
    payload.iss !== `https://${team}` ||
    !(payload.exp > now) ||
    (payload.nbf && payload.nbf > now + 60)
  ) {
    throw new HttpError(401, "Ogiltig eller utgången inloggning.");
  }

  const email = String(payload.email || "").toLowerCase();
  const allowed = env.ADMIN_EMAILS.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  if (!email || !allowed.includes(email)) throw new HttpError(403, `${email || "Kontot"} har inte behörighet till DAMP-admin.`);

  if (request.method !== "GET") {
    const origin = request.headers.get("Origin");
    if (origin && origin !== new URL(request.url).origin) throw new HttpError(403, "Fel ursprung.");
    if (!(request.headers.get("Content-Type") || "").startsWith("application/json")) throw new HttpError(415, "Förväntade JSON.");
  }
  // expires: when the Access session ends (seconds); the footer padlock stays open until then.
  return { email, expires: payload.exp };
}

// ---------- GitHub authentication ----------

function checkGithubSettings(env) {
  const need = ["GITHUB_REPO", ...(env.GITHUB_TOKEN ? [] : ["GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID", "GITHUB_APP_PRIVATE_KEY"])];
  const missing = need.filter((k) => !env[k]);
  if (missing.length) throw new HttpError(500, `Admin är inte färdigkonfigurerad. Saknar: ${missing.join(", ")}.`);
}

function derLength(n) {
  if (n < 0x80) return [n];
  const bytes = [];
  for (; n > 0; n >>= 8) bytes.unshift(n & 0xff);
  return [0x80 | bytes.length, ...bytes];
}

/** GitHub hands out PKCS#1 keys ("BEGIN RSA PRIVATE KEY"); WebCrypto only imports PKCS#8. */
function pkcs1ToPkcs8(pkcs1) {
  const rsaAlgorithm = [0x30, 0x0d, 0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x01, 0x05, 0x00];
  const head = [0x02, 0x01, 0x00, ...rsaAlgorithm, 0x04, ...derLength(pkcs1.length)];
  const bodyLength = head.length + pkcs1.length;
  const prefix = [0x30, ...derLength(bodyLength), ...head];
  const out = new Uint8Array(prefix.length + pkcs1.length);
  out.set(prefix);
  out.set(pkcs1, prefix.length);
  return out;
}

async function importPrivateKey(pem) {
  pem = pem.replace(/\\n/g, "\n"); // tolerate a key pasted with escaped newlines
  const der = b64urlDecode(pem.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""));
  const pkcs8 = pem.includes("BEGIN RSA PRIVATE KEY") ? pkcs1ToPkcs8(der) : der;
  return crypto.subtle.importKey("pkcs8", pkcs8, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
}

async function appJwt(appId, pem) {
  const now = Math.floor(Date.now() / 1000);
  const enc = (obj) => b64urlEncode(new TextEncoder().encode(JSON.stringify(obj)));
  const unsigned = `${enc({ alg: "RS256", typ: "JWT" })}.${enc({ iat: now - 60, exp: now + 540, iss: String(appId) })}`;
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", await importPrivateKey(pem), new TextEncoder().encode(unsigned));
  return `${unsigned}.${b64urlEncode(new Uint8Array(sig))}`;
}

let installationToken = null; // {token, expires}

async function githubToken(env) {
  if (env.GITHUB_TOKEN) return env.GITHUB_TOKEN;
  if (installationToken && installationToken.expires - Date.now() > 5 * 60_000) return installationToken.token;
  const res = await fetch(`https://api.github.com/app/installations/${env.GITHUB_APP_INSTALLATION_ID}/access_tokens`, {
    method: "POST",
    headers: { Authorization: `Bearer ${await appJwt(env.GITHUB_APP_ID, env.GITHUB_APP_PRIVATE_KEY)}`, ...GH_HEADERS },
  });
  if (!res.ok) throw new Error(`GitHub App token: ${res.status} ${await res.text()}`);
  const body = await res.json();
  installationToken = { token: body.token, expires: Date.parse(body.expires_at) };
  return body.token;
}

// ---------- GitHub API ----------

const GH_HEADERS = { Accept: "application/vnd.github+json", "User-Agent": UA, "X-GitHub-Api-Version": "2022-11-28" };
const repo = (env) => `/repos/${env.GITHUB_REPO}`;
const branch = (env) => env.GITHUB_BRANCH || "master";

async function gh(env, path, { method = "GET", body } = {}) {
  return fetch(`https://api.github.com${path}`, {
    method,
    headers: { Authorization: `Bearer ${await githubToken(env)}`, ...GH_HEADERS, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
}

async function ghJson(env, path, opts = {}) {
  const res = await gh(env, path, opts);
  if (!res.ok) throw new Error(`GitHub ${opts.method || "GET"} ${path}: ${res.status} ${await res.text()}`);
  return res.json();
}

async function headSha(env) {
  return (await ghJson(env, `${repo(env)}/git/ref/heads/${encodeURIComponent(branch(env))}`)).object.sha;
}

async function graphql(env, query, variables) {
  const [owner, name] = env.GITHUB_REPO.split("/");
  const res = await gh(env, "/graphql", { method: "POST", body: { query, variables: { owner, name, ...variables } } });
  const body = await res.json();
  if (!res.ok || body.errors) throw new Error(`GitHub GraphQL: ${res.status} ${JSON.stringify(body.errors || body)}`);
  return body.data;
}

// A directory's files with their text. Subdirectories come back without contents, so
// data/history/ (which only the history page needs) isn't downloaded with the data.
const ENTRIES = "... on Tree { entries { name type object { ... on Blob { text isTruncated } } } }";
const DATA_QUERY = `query($owner: String!, $name: String!, $top: String!, $tables: String!) {
  repository(owner: $owner, name: $name) {
    top: object(expression: $top) { ${ENTRIES} }
    tables: object(expression: $tables) { ${ENTRIES} }
  }
}`;
const DIR_QUERY = `query($owner: String!, $name: String!, $expr: String!) {
  repository(owner: $owner, name: $name) { object(expression: $expr) { ${ENTRIES} } }
}`;
const BLOB_QUERY = `query($owner: String!, $name: String!, $expr: String!) {
  repository(owner: $owner, name: $name) { object(expression: $expr) { ... on Blob { text isTruncated } } }
}`;

function parseBlob(path, blob) {
  if (!blob || blob.isTruncated || blob.text == null) throw new HttpError(500, `Kunde inte läsa data/${path}.`);
  try {
    return JSON.parse(blob.text);
  } catch (e) {
    throw new HttpError(500, `data/${path} är inte giltig JSON.`);
  }
}

/** Every data file at the branch head: one REST call for the head commit, one GraphQL call for the contents. */
async function getData(env, user) {
  const version = await headSha(env);
  const data = await graphql(env, DATA_QUERY, { top: `${version}:data`, tables: `${version}:data/tables` });
  const files = {};
  const add = (path, blob) => {
    if (DATA_PATH.test(path)) files[path] = parseBlob(path, blob);
  };
  for (const e of (data.repository.top && data.repository.top.entries) || []) if (e.type === "blob") add(e.name, e.object);
  for (const e of (data.repository.tables && data.repository.tables.entries) || []) if (e.type === "blob") add(`tables/${e.name}`, e.object);
  return { version, files, user };
}

/** The whole change log, newest first. */
async function getHistory(env) {
  const head = await headSha(env);
  const data = await graphql(env, DIR_QUERY, { expr: `${head}:data/history` });
  const events = [];
  for (const e of (data.repository.object && data.repository.object.entries) || []) {
    if (e.type === "blob" && /^\d{4}-\d{2}\.json$/.test(e.name)) events.push(...parseBlob(`history/${e.name}`, e.object));
  }
  // Newest first; the sort is stable, so reversing first puts the last appended first within a second.
  events.reverse().sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));
  return { events };
}

/** The change log event for a save; the same rules as make_event in damp/history.py. */
function makeEvent({ message, lps = [], details = [] }, email) {
  if (typeof message !== "string" || !message.trim()) throw new HttpError(400, "Händelsen saknar beskrivning.");
  if (!Array.isArray(lps) || lps.length > 10 || !lps.every((lp) => typeof lp === "string" && LP_ID.test(lp))) throw new HttpError(400, "Ogiltiga LP i händelsen.");
  if (!Array.isArray(details) || details.length > 100 || !details.every((d) => typeof d === "string")) throw new HttpError(400, "Ogiltiga detaljer i händelsen.");
  const clean = (text, max) => text.replace(/\s+/g, " ").trim().slice(0, max);
  const event = { at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"), by: email, message: clean(message, 200), lps: [...new Set(lps)].sort() };
  if (details.length) event.details = details.map((d) => clean(d, 300));
  return event;
}

/** data/ paths changed between `base` and `head`, or null if that can't be told (unknown base, huge diff). */
async function changedSince(env, base, head) {
  const res = await gh(env, `${repo(env)}/compare/${base}...${head}`);
  if (!res.ok) return null;
  const cmp = await res.json();
  if (cmp.status !== "ahead" || !cmp.files || cmp.files.length >= 300) return null;
  const paths = new Set();
  for (const f of cmp.files) {
    paths.add(f.filename);
    if (f.previous_filename) paths.add(f.previous_filename);
  }
  return paths;
}

async function postSave(request, env, user) {
  const text = await request.text();
  if (text.length > MAX_BODY) throw new HttpError(413, "Ändringen är för stor.");
  let body;
  try {
    body = JSON.parse(text);
  } catch (e) {
    throw new HttpError(400, "Ogiltig JSON.");
  }
  const { base, changes } = body || {};
  if (typeof base !== "string" || !/^[0-9a-f]{40}$/.test(base) || !changes || typeof changes !== "object" || Array.isArray(changes) || !Object.keys(changes).length) {
    throw new HttpError(400, "Förväntade {base, message, changes}.");
  }
  const paths = Object.keys(changes);
  const bad = paths.filter((p) => !DATA_PATH.test(p));
  if (bad.length) throw new HttpError(400, `Otillåten sökväg: ${bad.join(", ")}`);
  if (Object.values(changes).some((c) => c !== null && typeof c !== "object")) throw new HttpError(400, "Filinnehåll ska vara ett objekt eller en lista.");

  const event = makeEvent(body, user.email);
  const historyPath = `history/${event.at.slice(0, 7)}.json`;
  const commitMessage = [event.message, "", ...(event.details || []).slice(0, 30), ...(event.details ? [""] : []), `Via DAMP-admin av ${user.email}`].join("\n");
  const tree = paths.map((p) =>
    changes[p] === null
      ? { path: `data/${p}`, mode: "100644", type: "blob", sha: null }
      : { path: `data/${p}`, mode: "100644", type: "blob", content: JSON.stringify(changes[p], null, 2) + "\n" }
  );

  for (let attempt = 0; attempt < 3; attempt++) {
    const head = await headSha(env);
    if (head !== base) {
      const changed = await changedSince(env, base, head);
      const conflicts = changed ? paths.filter((p) => changed.has(`data/${p}`)) : paths;
      if (conflicts.length) return json({ error: "conflict", paths: conflicts }, 409);
    }
    const headCommit = await ghJson(env, `${repo(env)}/git/commits/${head}`);
    const log = (await graphql(env, BLOB_QUERY, { expr: `${head}:data/${historyPath}` })).repository.object;
    const events = log ? parseBlob(historyPath, log) : [];
    const historyEntry = { path: `data/${historyPath}`, mode: "100644", type: "blob", content: JSON.stringify([...events, event], null, 2) + "\n" };
    const newTree = await ghJson(env, `${repo(env)}/git/trees`, { method: "POST", body: { base_tree: headCommit.tree.sha, tree: [...tree, historyEntry] } });
    const commit = await ghJson(env, `${repo(env)}/git/commits`, {
      method: "POST",
      body: {
        message: commitMessage,
        tree: newTree.sha,
        parents: [head],
        author: { name: user.email.split("@")[0], email: user.email, date: new Date().toISOString() },
      },
    });
    const res = await gh(env, `${repo(env)}/git/refs/heads/${encodeURIComponent(branch(env))}`, { method: "PATCH", body: { sha: commit.sha, force: false } });
    if (res.ok) return json({ version: commit.sha, rebased: head !== base });
    if (res.status !== 422 && res.status !== 409) throw new Error(`GitHub update ref: ${res.status} ${await res.text()}`);
    // Someone pushed between reading the head and updating it: start over on the new head.
  }
  return json({ error: "conflict", paths }, 409);
}
