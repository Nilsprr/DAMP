// The member form: used on the members page and for "+ Ny medlem" in the table editor.
import { MEMBERS, UserError, cleanName, formDialog, memberName, sameName, save, todayISO } from "./core.js";

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

