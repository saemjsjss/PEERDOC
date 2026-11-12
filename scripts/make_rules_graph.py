"""Build an interactive dependency graph (single HTML file) from a rules/RULES-vN.md.

    .venv\\Scripts\\python.exe scripts\\make_rules_graph.py rules\\RULES-v3.md

Writes docs/rules-graph-v3.html. Nodes are rule IDs, the identity anchors, 5.2 Affidavit
Coverage and the two online hosts. An edge A -> B means B's text names A (A feeds B), plus
the hand-listed links in MANUAL_EDGES that the wording doesn't spell out.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = Path(__file__).with_name("rules_graph_template.html")

ANCHORS = ("StudentRef", "FatherRef", "MotherRef")
ID = r"(?:[A-Z]+-(?:\d+|ASSIGN|COVERAGE)|StudentRef|FatherRef|MotherRef)"
# A mention, with the "REQ-08/09" and "BANK-01..03" shorthands.
MENTION = re.compile(r"\b([A-Z]+)-(\d+)(?:(/|\.\.)(\d+))?\b|\b(NID-ASSIGN|ENGINE-COVERAGE|StudentRef|FatherRef|MotherRef)\b")
APOSTILLE, CHALLAN, AFFIDAVIT = "apostille.mygov.bd", "achallan.gov.bd", "AFFIDAVIT"
API_BULLETS = {"e-Apostille": APOSTILLE, "Challan": CHALLAN}
MANUAL_EDGES = [
    (APOSTILLE, "ACAD-01"), (CHALLAN, "TAX-04"),
    ("NID-ASSIGN", "REQ-08"), ("NID-ASSIGN", "REQ-09"),
    ("TIN-03", "CHAIN-02"), ("TRADE-04", "CHAIN-02"), ("EMP-05", "CHAIN-02"),
    ("TRADE-04", "CHAIN-04"), ("EMP-05", "CHAIN-04"), ("BANK-01", "CHAIN-04"),  # RULES-v6
]


def mentions(text: str) -> list[list[str]]:
    """Each mention as a group of IDs ("REQ-08/09" -> [REQ-08, REQ-09])."""
    groups = []
    for m in MENTION.finditer(text):
        if m.group(5):
            groups.append([m.group(5)])
            continue
        prefix, a, sep, b = m.group(1), m.group(2), m.group(3), m.group(4)
        nums = [int(a)] if not sep else ([int(a), int(b)] if sep == "/" else list(range(int(a), int(b) + 1)))
        groups.append([f"{prefix}-{n:0{len(a)}d}" for n in nums])
    return groups


def parse(text: str) -> tuple[dict, dict, dict]:
    nodes: dict[str, dict] = {}
    sections: dict[int, str] = {}
    sub_notes: dict[str, list[str]] = {}
    section = sub = None
    sub_approved = False
    cur = None  # node being filled
    note: list[str] | None = None  # notes list of the last loose bullet, for its wrapped lines
    takes_bullets = False  # a "2.2 NID-ASSIGN:" block owns the bullets under it; a "* ID" block doesn't
    loose: list[tuple[int, str]] = []  # (section, line) for IDs only mentioned in prose

    def new(node_id: str, title: str, first: str) -> dict:
        node = {"id": node_id, "title": title, "section": section, "sub": sub, "lines": [first],
                "approved": sub_approved}
        nodes.setdefault(node_id, node)
        return node

    for raw in text.splitlines():
        line = raw.rstrip()
        if m := re.match(r"## SECTION (\d+): (.*)", line):
            section, sub, cur = int(m.group(1)), None, None
            sections[section] = m.group(2)
            continue
        if section is None:
            continue
        if not line.strip():
            cur = note = None
            continue
        if m := re.match(r"(\d+\.\d+b?) (.*)", line):
            sub, sub_approved, cur = line.replace("*(approved)*", "").strip(), "(approved)" in line, None
            if h := re.match(rf"({ID}):\s*(.*)", m.group(2)):
                cur, takes_bullets = new(h.group(1), "", h.group(2)), True
            elif "Affidavit" in m.group(2):
                cur, takes_bullets = new(AFFIDAVIT, "5.2 Affidavit Coverage", ""), True
            continue
        if m := re.match(rf"\* ({ID})\b(?: \(([^)]*)\))?:?\s*(.*)", line):
            cur, takes_bullets = new(m.group(1), m.group(2) or "", m.group(3)), False
            continue
        if section == 7 and (m := re.match(r"\* ([\w-]+):\s*(.*)", line)) and m.group(1) in API_BULLETS:
            cur, takes_bullets = new(API_BULLETS[m.group(1)], f"{m.group(1)} register", m.group(2)), False
            continue
        if line.startswith("* "):
            if cur and takes_bullets:
                cur["lines"].append(line[2:])
            else:
                cur = None
                note = sub_notes.setdefault(sub, []) if sub else None
                if note is not None:
                    note.append(line[2:])
                loose.append((section, line))
            continue
        if cur:
            cur["lines"][-1] += " " + line.strip()
        elif note and line.startswith("  "):  # wrapped line of a note bullet
            note[-1] += " " + line.strip()
        else:
            loose.append((section, line))

    # IDs that only appear in prose (IGNORE-01, ENGINE-COVERAGE) still get a node.
    for sec, line in loose:
        for group in mentions(line):
            for node_id in group:
                if node_id not in nodes and sec != 0:
                    nodes[node_id] = {"id": node_id, "title": "", "section": sec, "sub": None,
                                      "lines": [line.lstrip("* ").strip()], "approved": False}
    return nodes, sections, sub_notes


def build(text: str) -> dict:
    nodes, sections, sub_notes = parse(text)
    edges: set[tuple[str, str]] = set()
    for node in nodes.values():
        body = "\n".join(node["lines"])
        for group in mentions(body):
            if node["id"] in group:  # "REQ-08/09" inside REQ-09 is a self reference
                continue
            edges.update((src, node["id"]) for src in group if src in nodes)
    # TAX-01 names TAX-03..04 because it gates them, so the arrow runs the other way.
    edges = {(t, s) if t == "TAX-01" else (s, t) for s, t in edges}
    # a hand-listed link only where both rules exist in this version (CHAIN-04 is v6+)
    edges.update((s, t) for s, t in MANUAL_EDGES if s in nodes and t in nodes)
    # 5.2 covers every name-matching rule: anything an identity anchor feeds, plus TIN-03.
    name_rules = {t for s, t in edges if s in ANCHORS} | {"TIN-03"}
    edges.update((AFFIDAVIT, t) for t in name_rules)
    missing = {n for e in edges for n in e} - nodes.keys()
    assert not missing, f"edges point at rules that aren't in the file: {missing}"

    out = []
    for node in nodes.values():
        body = "\n".join(node["lines"]).strip()
        status = ("needs approval" if "(needs approval)" in body
                  else "approved" if node["approved"] or "(approved)" in body else "rulebook")
        triggers = sorted(set(re.findall(r"(?<!never )\b(PASS|FLAG|FAIL)", body)))
        kind = "api" if node["id"] in (APOSTILLE, CHALLAN) else "anchor" if node["id"] in ANCHORS else "rule"
        out.append({"id": node["id"], "title": node["title"], "section": node["section"],
                    "sub": node["sub"], "text": body, "status": status, "triggers": triggers,
                    "kind": kind, "notes": sub_notes.get(node["sub"], []) if node["sub"] else []})
    return {"title": text.splitlines()[0].lstrip("# "), "sections": sections,
            "nodes": out, "edges": sorted(edges)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rules", type=Path, nargs="?", default=REPO / "rules" / "RULES-v3.md")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    data = build(args.rules.read_text(encoding="utf-8"))
    out = args.out or REPO / "docs" / f"rules-graph-{args.rules.stem.split('-')[-1].lower()}.html"
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    out.write_text(TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", payload), encoding="utf-8")
    print(f"{out}: {len(data['nodes'])} nodes, {len(data['edges'])} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
