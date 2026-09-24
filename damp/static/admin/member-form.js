// The member form: used on the members page and for "+ Ny medlem" in the table editor.
import {
  MANUAL, MEMBERS, UserError, cleanName, formDialog, memberByName, memberName, sameName, save, tableLabel, tablePath, todayISO,
} from "./core.js";

// Fields in the order they're stored, with the labels used in the history.
const FIELDS = [
  ["first_name", "Förnamn"],
  ["last_name", "Efternamn"],
  ["display_name", "Visningsnamn"],
  ["ltu_id", "LTU-id"],
  ["joined_on", "Medlem sedan"],
];

function check(d, entry, selfId) {
  if (!entry.first_name || !entry.last_name) throw new UserError("Förnamn och efternamn behövs.");
  for (const m of d.members) {
    if (m.id === selfId) continue;
    if (sameName(memberName(m), memberName(entry))) throw new UserError(`Det finns redan en medlem som heter ${memberName(m)}.`);
    if (entry.ltu_id && m.ltu_id && sameName(m.ltu_id, entry.ltu_id)) throw new UserError(`LTU-id ${entry.ltu_id} används redan av ${memberName(m)}.`);
    if (entry.display_name && m.display_name && sameName(m.display_name, entry.display_name)) {
      throw new UserError(`Visningsnamnet ${entry.display_name} används redan av ${memberName(m)}.`);
    }
  }
}

/**
 * Open the form for `member` (null = new member, prefilled from `prefill`, e.g. what was
 * typed in the table editor). Resolves {data, member} once saved, or undefined if cancelled.
 */
export function memberDialog(data, member = null, prefill = "") {
  const [first = "", ...rest] = cleanName(prefill).split(" ");
  const value = (key, fallback = "") => (member ? member[key] || "" : fallback);
  return formDialog({
    title: member ? `Redigera ${memberName(member)}` : "Ny medlem",
    submitLabel: member ? "Spara" : "Lägg till",
    fields: [
      { name: "first_name", label: "Förnamn", required: true, value: value("first_name", first), attrs: { maxlength: 60, autocomplete: "off" } },
      { name: "last_name", label: "Efternamn", required: true, value: value("last_name", rest.join(" ")), attrs: { maxlength: 80, autocomplete: "off" } },
      {
        name: "display_name",
        label: "Visningsnamn (valfritt)",
        value: value("display_name"),
        hint: "Visas på topplistan i stället för förnamnet.",
        attrs: { maxlength: 40, autocomplete: "off" },
      },
      { name: "ltu_id", label: "LTU-id (valfritt)", value: value("ltu_id"), attrs: { maxlength: 32, autocomplete: "off", placeholder: "t.ex. abcdef-5" } },
      { name: "joined_on", label: "Medlem sedan", type: "date", value: value("joined_on", todayISO()) },
    ],
    onSubmit: async (values) => {
      const entry = {
        first_name: cleanName(values.first_name),
        last_name: cleanName(values.last_name),
        ...(cleanName(values.display_name) ? { display_name: cleanName(values.display_name) } : {}),
        ...(cleanName(values.ltu_id) ? { ltu_id: cleanName(values.ltu_id).toLowerCase() } : {}),
        ...(values.joined_on ? { joined_on: values.joined_on } : {}),
      };
      const selfId = member ? member.id : null;
      check(data, entry, selfId);
      let saved;
      data = await save((d) => {
        check(d, entry, selfId);
        const members = d.copy(MEMBERS, []);
        if (member) {
          const i = members.findIndex((x) => x.id === member.id);
          if (i === -1) throw new UserError(`${memberName(member)} har tagits bort av någon annan.`);
          const before = members[i];
          saved = { id: member.id, ...entry };
          members[i] = saved;
          const details = FIELDS.filter(([k]) => (before[k] || "") !== (saved[k] || "")).map(([k, label]) => `${label}: ${before[k] || "–"} → ${saved[k] || "–"}`);
          if (!details.length) return null;
          return { changes: { [MEMBERS]: members }, message: `Ändrad medlem: ${memberName(saved)}`, details };
        }
        saved = { id: d.nextMemberId(), ...entry };
        members.push(saved);
        const details = FIELDS.filter(([k]) => saved[k] && k !== "first_name" && k !== "last_name").map(([k, label]) => `${label}: ${saved[k]}`);
        return { changes: { [MEMBERS]: members }, message: `Ny medlem: ${memberName(saved)}`, details };
      }, data);
      return { data, member: saved };
    },
  });
}

/** A member entry with its keys in the stored order. */
function ordered(m) {
  const out = { id: m.id };
  for (const [k] of FIELDS) if (m[k]) out[k] = m[k];
  return out;
}

/**
 * Merge `source` into another member: every table result and manual point moves to the
 * other member and `source` is removed. For nicknames that turn out to be a listed member
 * (e.g. "Kjelle" -> Nils Kjellberg), and for accidental duplicates. Resolves {data} once
 * saved, or undefined if cancelled.
 */
export function mergeDialog(data, source) {
  const nickname = source.display_name || (source.last_name ? "" : source.first_name);
  return formDialog({
    title: `Slå ihop ${memberName(source)} med en annan medlem`,
    submitLabel: "Slå ihop",
    fields: [
      {
        name: "target",
        label: "Medlemmen som ska finnas kvar",
        required: true,
        attrs: { list: "merge-members", autocomplete: "off", placeholder: "Namn eller LTU-id" },
        hint: `${memberName(source)}s bord och poäng flyttas dit, och ${memberName(source)} tas bort.`,
      },
      {
        name: "display_name",
        label: "Visningsnamn efteråt (valfritt)",
        value: nickname,
        hint: "Visas på topplistan och som smeknamn: förnamn \"visningsnamn\" efternamn. Lämna tomt för inget.",
        attrs: { maxlength: 40, autocomplete: "off" },
      },
    ],
    onSubmit: async (values) => {
      const target = memberByName(data.members.filter((m) => m.id !== source.id), values.target);
      if (!target) throw new UserError(`Hittar ingen annan medlem som heter "${cleanName(values.target)}".`);
      const display = cleanName(values.display_name) || null;
      data = await save((d) => {
        const src = d.memberById.get(source.id);
        const dst = d.memberById.get(target.id);
        if (!src) throw new UserError(`${memberName(source)} har redan tagits bort.`);
        if (!dst) throw new UserError(`${memberName(target)} har tagits bort av någon annan.`);
        if (display) {
          const clash = d.members.find((m) => m.id !== src.id && m.id !== dst.id && m.display_name && sameName(m.display_name, display));
          if (clash) throw new UserError(`Visningsnamnet ${display} används redan av ${memberName(clash)}.`);
        }
        const changes = {};
        const dates = [];
        const clashes = [];
        let tables = 0;
        for (const t of d.tables) {
          if (!t.players.some((s) => s.member === src.id)) continue;
          if (t.players.some((s) => s.member === dst.id)) {
            clashes.push(tableLabel(t.date, t.number));
            continue;
          }
          const table = d.copy(tablePath(t.id), null);
          table.players = table.players.map((s) => (s.member === src.id ? { ...s, member: dst.id } : s));
          changes[tablePath(t.id)] = table;
          dates.push(t.date);
          tables += 1;
        }
        if (clashes.length) throw new UserError(`Båda är med vid samma bord (${clashes.join(", ")}). Rätta de borden först.`);
        const manual = d.copy(MANUAL, []);
        let points = 0;
        for (const e of manual) {
          if (e.member !== src.id) continue;
          e.member = dst.id;
          dates.push(e.date);
          points += 1;
        }
        if (points) changes[MANUAL] = manual;
        const members = d.copy(MEMBERS, []).filter((m) => m.id !== src.id);
        const i = members.findIndex((m) => m.id === dst.id);
        const before = members[i];
        const merged = { ...before, display_name: display || undefined };
        for (const k of ["last_name", "ltu_id", "joined_on"]) if (!merged[k] && src[k]) merged[k] = src[k];
        members[i] = ordered(merged);
        changes[MEMBERS] = members;
        const details = [`${tables} bord och ${points} manuella poäng flyttades från ${memberName(src)} till ${memberName(dst)}.`];
        for (const [k, label] of FIELDS) {
          if ((before[k] || "") !== (members[i][k] || "")) details.push(`${label}: ${before[k] || "–"} → ${members[i][k] || "–"}`);
        }
        return { changes, message: `Slog ihop ${memberName(src)} med ${memberName(dst)}`, lps: d.lpsFor(dates), details };
      }, data);
      return { data };
    },
  });
}
