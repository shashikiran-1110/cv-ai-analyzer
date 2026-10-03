import { useEffect, useId, useState } from "react";
import { api } from "../api";
import type { SkillInfo } from "../types";
import { Chip } from "./ui";

let cache: SkillInfo[] | null = null;

/** Chip input with autocomplete over the server's skill taxonomy. */
export function SkillPicker({ value, onChange, placeholder = "Add a skill, e.g. Kubernetes…" }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [skills, setSkills] = useState<SkillInfo[]>(cache ?? []);
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const listId = useId();
  useEffect(() => { if (!cache) api<SkillInfo[]>("/api/skills").then((s) => { cache = s; setSkills(s); }).catch(() => {}); }, []);

  function add(raw: string) {
    const t = raw.trim();
    if (!t) return;
    const hit = skills.find((s) => s.name.toLowerCase() === t.toLowerCase());
    if (!hit && skills.length) { setNote(`“${t}” isn't in the skill list, pick one from the suggestions.`); return; }
    const name = hit?.name ?? t;
    if (!value.includes(name)) onChange([...value, name]);
    setText(""); setNote("");
  }
  return (
    <div>
      <div className="chips">
        {value.map((s) => <Chip key={s} tone="ok">{s} <button type="button" className="x" aria-label={`Remove ${s}`} onClick={() => onChange(value.filter((v) => v !== s))}>×</button></Chip>)}
      </div>
      <div className="key-row">
        <input list={listId} value={text} placeholder={placeholder} onChange={(e) => { setText(e.target.value); setNote(""); }}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(text); } }} aria-label="Add skill" />
        <button type="button" className="btn" onClick={() => add(text)} disabled={!text.trim()}>Add</button>
      </div>
      <datalist id={listId}>{skills.filter((s) => !value.includes(s.name)).map((s) => <option key={s.name} value={s.name}>{s.category}</option>)}</datalist>
      {note && <small className="warn-text">{note}</small>}
    </div>
  );
}
