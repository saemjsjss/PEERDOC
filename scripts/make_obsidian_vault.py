"""Build an Obsidian vault from a rules/RULES-vN.md: one note per rule, linked like the graph.

    .venv\\Scripts\\python.exe scripts\\make_obsidian_vault.py rules\\RULES-v6.md

Writes docs/obsidian-v6/. Open that folder in Obsidian ("Open folder as vault"); the graph
view then shows the same dependencies as docs/rules-graph-v6.html. Nodes and edges come from
make_rules_graph.build, so both outputs always agree.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from make_rules_graph import REPO, build

BAD_CHARS = re.compile(r'[\\/:*?"<>|#^\[\]]')


def section_note(num: int, name: str) -> str:
    return BAD_CHARS.sub("", f"Section {num} - {name}").strip()


def raw_sections(text: str) -> dict[int, str]:
    """Each section's own text, for sections that have no rule notes (conventions, verdict)."""
    parts = re.split(r"^## SECTION (\d+): .*$", text, flags=re.M)
    return {int(parts[i]): parts[i + 1].strip() for i in range(1, len(parts), 2)}


def linked(body: str, ids: list[str], self_id: str) -> str:
    """Turn every whole-word mention of another rule into an Obsidian [[link]]."""
    others = sorted((i for i in ids if i != self_id), key=len, reverse=True)
    if not others:
        return body
    pattern = re.compile(r"(?<![\w\-\[])(" + "|".join(map(re.escape, others)) + r")(?![\w\-\]])")
    return pattern.sub(r"[[\1]]", body)


def rule_note(node: dict, ids: list[str], uses: list[str], used_by: list[str], sec: str) -> str:
    tags = [f"section/{node['section']}", f"kind/{node['kind']}", f"status/{node['status'].replace(' ', '-')}"]
    tags += [f"outcome/{t}" for t in node["triggers"]]
    front = ["---", f"section: {node['section']}", f"status: {node['status']}",
             f"outcomes: [{', '.join(node['triggers'])}]", "tags:", *[f"  - {t}" for t in tags], "---"]
    heading = f"# {node['id']}" + (f" — {node['title']}" if node["title"] and node["title"] != node["id"] else "")
    out = [*front, "", heading, "", f"Section: [[{sec}]]"]
    if node["sub"]:
        out.append(f"Subsection: {node['sub']}")
    out += ["", linked(node["text"], ids, node["id"])]
    if node["notes"]:
        out += ["", "## Notes", *[f"- {linked(n, ids, node['id'])}" for n in node["notes"]]]
    if uses:
        out += ["", "## Depends on", *[f"- [[{u}]]" for u in uses]]
    if used_by:
        out += ["", "## Feeds", *[f"- [[{u}]]" for u in used_by]]
    return "\n".join(out) + "\n"


def write_vault(rules: Path, out: Path) -> tuple[int, int]:
    text = rules.read_text(encoding="utf-8")
    data = build(text)
    nodes, edges = data["nodes"], data["edges"]
    ids = [n["id"] for n in nodes]
    raw = raw_sections(text)

    # Regenerate from scratch, but keep Obsidian's own settings folder (.obsidian).
    if out.exists():
        for p in out.iterdir():
            if p.name != ".obsidian":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
    out.mkdir(parents=True, exist_ok=True)

    by_section: dict[int, list[str]] = {}
    for node in nodes:
        sec = section_note(node["section"], data["sections"][node["section"]])
        uses = sorted(s for s, t in edges if t == node["id"])
        used_by = sorted(t for s, t in edges if s == node["id"])
        (out / f"{node['id']}.md").write_text(rule_note(node, ids, uses, used_by, sec), encoding="utf-8")
        by_section.setdefault(node["section"], []).append(node["id"])

    home = [f"# {data['title']}", "", f"Generated from `rules/{rules.name}` by "
            "`scripts/make_obsidian_vault.py`. Do not edit here: change the rules in a new "
            "RULES-vN.md and regenerate.", "", "## Sections"]
    for num, name in sorted(data["sections"].items()):
        sec = section_note(num, name)
        home.append(f"- [[{sec}]]")
        body = [f"# Section {num}: {name}", "", "Back to [[Home]]", ""]
        if by_section.get(num):
            body += [f"- [[{i}]]" for i in by_section[num]]
        else:
            body.append(linked(raw.get(num, ""), ids, ""))
        (out / f"{sec}.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    (out / "Home.md").write_text("\n".join(home) + "\n", encoding="utf-8")
    return len(nodes), len(edges)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rules", type=Path, nargs="?", default=REPO / "rules" / "RULES-v6.md")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    out = args.out or REPO / "docs" / f"obsidian-{args.rules.stem.split('-')[-1].lower()}"
    n, e = write_vault(args.rules, out)
    print(f"{out}: {n} rule notes, {e} links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
