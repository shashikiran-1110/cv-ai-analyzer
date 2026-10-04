import { Modal } from "../Modal";
import { useShell } from "./ShellProvider";

const mod = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";
const GROUPS: [string, [string, string[]][]][] = [
  ["Anywhere", [["Command menu", [mod, "K"]], ["Keyboard shortcuts", ["?"]]]],
  ["Jobs table", [["Move down / up", ["j", "k"]], ["Open job", ["↵"]], ["Select job", ["x"]], ["Focus search", ["/"]], ["Clear selection", ["esc"]]]],
  ["Job detail", [["Close", ["esc"]]]],
  ["Labelling (Eval Studio)", [["Strong · possible · stretch · no", ["1", "2", "3", "4"]], ["Skip", ["s"]]]],
];

export function ShortcutsHelp() {
  const shell = useShell();
  if (!shell.shortcuts) return null;
  return (
    <Modal title="Keyboard shortcuts" onClose={() => shell.setShortcuts(false)}>
      <dl className="shortcuts">
        {GROUPS.map(([g, rows]) => (
          <div key={g} style={{ display: "contents" }}>
            <h4>{g}</h4>
            {rows.map(([label, keys]) => <div key={label} style={{ display: "contents" }}><dt>{label}</dt><dd>{keys.map((k) => <kbd key={k}>{k}</kbd>)}</dd></div>)}
          </div>
        ))}
      </dl>
    </Modal>
  );
}
