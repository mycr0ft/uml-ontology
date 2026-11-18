#!/usr/bin/env python
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Jon R. Fox
"""Draw a slice of the UML-family ontology as a UML class diagram.

The ontology fact book already carries everything a class diagram needs, so this reads
`ontology/relationships.json` rather than any diagram intermediate: classes and their bases,
features with type and multiplicity, stereotypes, and the abstract flag.

Layout is inheritance depth across, siblings down. That is enough for a documentation figure
and it is deterministic, which matters more here than optimal routing: the point is that a
`make` can regenerate the figure and a reviewer can diff it.

    python tools/draw_ontology.py --package CommonStructure --out docs/relationships.tex
    python tools/draw_ontology.py --classes uml:Classifier,uml:Feature --out /tmp/x.tex
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent          # docs/
ROOT = DOCS.parent                                   # repo root
DEFAULT_FACTS = ROOT / "ontology" / "relationships.json"

PREAMBLE = r"""\documentclass[tikz,border=8pt]{standalone}
\usepackage{umltikz}
\pgfdeclarelayer{back}
\pgfsetlayers{back,main}
\begin{document}
\begin{tikzpicture}
"""

POSTAMBLE = r"""\end{tikzpicture}
\end{document}
"""


def short(key: str) -> str:
    """`uml:Dependency` -> `Dependency`; the language prefix is the diagram's context."""
    return key.split(":", 1)[1] if ":" in key else key


def esc(text: str) -> str:
    for bad, good in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                      ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}")):
        text = text.replace(bad, good)
    return text


def multiplicity(prop: dict) -> str:
    lo, hi = prop["lo"], prop["hi"]
    if lo == 0 and hi == "*":
        return "*"
    if lo == hi:
        return str(lo)
    return f"{lo}..{hi}"


def feature_row(prop: dict) -> str:
    """A UML attribute row: visibility, name, type, multiplicity. Composite ends are marked."""
    mark = " (composite)" if prop.get("composite") else ""
    return (f"+ {esc(prop['name'])} : {esc(short(prop['range']))} "
            f"[{multiplicity(prop)}]{mark}")


def depths(classes: dict, select: set[str]) -> dict[str, int]:
    """Longest inheritance depth within the selection, so generals sit above their children."""
    memo: dict[str, int] = {}

    def walk(key: str, seen: frozenset[str] = frozenset()) -> int:
        if key in memo:
            return memo[key]
        if key in seen:                       # a cycle in the metamodel: stop, do not hang
            return 0
        parents = [b for b in classes[key].get("bases", []) if b in select]
        value = 0 if not parents else 1 + max(walk(p, seen | {key}) for p in parents)
        memo[key] = value
        return value

    for key in select:
        walk(key)
    return memo


#: rough TeX metrics at \scriptsize\ttfamily: enough to place boxes without a measure pass.
#: A figure that is 10% too loose is a fine figure; one that overlaps is not, so the constants
#: are deliberately generous and the render is inspected.
CHAR_MM = 1.55
ROW_MM = 3.9
HEADER_MM = 6.5
PAD_MM = 4.0
COL_GAP_MM = 26.0
ROW_GAP_MM = 16.0


PT_MM = 25.4 / 72.27


def box_size_measured(key: str, sizes: dict, name: str, stereo: str, rows: int) -> tuple[float, float]:
    """Width from TeX's own measurement of the widest line; height from the row count.

    The measured width is what stops columns colliding: a proportional bold name and a
    monospaced `(composite)` suffix are not functions of the character count.
    """
    width = sizes[key] * PT_MM + 5.5                 # inner sep 3pt each side + frame
    header = sizes["HEAD"] * PT_MM * (1.0 + (0.55 if stereo else 0.0)) + 2.4
    height = header + 1.2 + (rows + 0.4) * sizes["ROW"] * PT_MM + 2.4
    return width, height


def box_size(name: str, stereo: str, attrs: str, ops: str) -> tuple[float, float]:
    """Estimated (width, height) in millimetres."""
    lines = [name] + ([stereo] if stereo else [])
    body = [row for row in (attrs + "\\\\" + ops).split("\\\\") if row.strip()]
    widest = max([len(line) * CHAR_MM * 1.15 for line in lines]
                 + [len(row) * CHAR_MM for row in body] + [10.0])
    height = HEADER_MM * (1.0 + (0.35 if stereo else 0.0)) + max(1, len(body)) * ROW_MM
    return widest + PAD_MM, height + PAD_MM


def build(facts: dict, select: set[str], associations: list[tuple[str, str]],
          sizes: dict | None = None) -> dict:
    classes = facts["classes"]
    props = facts["properties"]
    depth = depths(classes, select)

    columns: dict[int, list[str]] = {}
    for key in sorted(select, key=lambda k: (depth[k], k)):
        columns.setdefault(depth[key], []).append(key)

    payload: dict[str, dict] = {}
    for key in select:
        entry = classes[key]
        own = [p for p in props if p["owner"] == key]
        attrs = "\\\\".join(feature_row(p) for p in own)
        stereo = f"«{esc(short(entry['stereotype']))}»" if entry.get("stereotype") else ""
        payload[key] = {"name": short(key), "stereo": stereo, "attrs": attrs, "ops": "",
                        "abstract": bool(entry.get("abstract"))}
        rows = len([r for r in attrs.split("\\\\") if r.strip()])
        if sizes and key in sizes:
            payload[key]["size"] = box_size_measured(key, sizes, payload[key]["name"], stereo, rows)
        else:
            payload[key]["size"] = box_size(payload[key]["name"], stereo, attrs, "")

    # x: one column per inheritance depth, wide enough for its widest box
    x_at: dict[int, float] = {}
    x = 0.0
    for col in sorted(columns):
        x_at[col] = x
        widest = max(payload[k]["size"][0] for k in columns[col])
        x = x + widest + COL_GAP_MM

    # y: stack each column downward, centred on the tallest column so the picture is balanced
    tallest = max(sum(payload[k]["size"][1] + ROW_GAP_MM for k in columns[c]) for c in columns)
    pos: dict[str, tuple[float, float]] = {}
    for col in sorted(columns):
        stack = sum(payload[k]["size"][1] + ROW_GAP_MM for k in columns[col])
        y = (tallest - stack) / 2.0
        for key in columns[col]:
            height = payload[key]["size"][1]
            pos[key] = (x_at[col] + payload[key]["size"][0] / 2.0, -(y + height / 2.0))
            y += height + ROW_GAP_MM

    body: list[str] = []

    def node(key: str) -> str:
        return key.replace(":", "_")

    body.append("% class boxes")
    for key in sorted(select):
        entry = payload[key]
        x_mm, y_mm = pos[key]
        prefix = r"\UMLabstract " if entry["abstract"] else ""
        body.append(rf"{prefix}\UMLclass[at={{({x_mm / 10.0:.2f},{-y_mm / 10.0:.2f})}}]"
                    f"{{{node(key)}}}{{{entry['name']}}}{{{entry['stereo']}}}"
                    f"{{{entry['attrs']}}}{{{entry['ops']}}}")

    body.append("% class boxes")

    body.append("% relationships, in the background layer: the boxes hide what crosses them")
    body.append(r"\begin{pgfonlayer}{back}")
    gens = 0
    for key in sorted(select):
        for base in classes[key].get("bases", []):
            if base in select:
                body.append(rf"\UMLgen{{{node(key)}}}{{{node(base)}}}")
                gens += 1
    def crosses(a: str, b: str) -> bool:
        """Does the straight route a->b pass through a box that is neither end?"""
        (x1, y1), (x2, y2) = pos[a], pos[b]
        for other, (ox, oy) in pos.items():
            if other in (a, b):
                continue
            w, hh = payload[other]["size"]
            left, right = ox - w / 2.0, ox + w / 2.0
            top, bottom = oy - hh / 2.0, oy + hh / 2.0
            for step in range(1, 40):
                f = step / 40.0
                px, py = x1 + (x2 - x1) * f, y1 + (y2 - y1) * f
                if left < px < right and top < py < bottom:
                    return True
        return False

    assocs = 0
    skipped: list[str] = []
    for owner, name in associations:
        prop = next((p for p in props if p["owner"] == owner and p["name"] == name), None)
        if prop is None or owner not in select or prop["range"] not in select:
            continue
        if crosses(owner, prop["range"]):
            skipped.append(f"{owner}.{name}")
        body.append(rf"\UMLnav{{{node(owner)}}}{{{node(prop['range'])}}}{{}}"
                    f"{{{multiplicity(prop)}}}{{{esc(name)}}}")
        assocs += 1

    body.append(r"\end{pgfonlayer}")
    return {"tex": "\n".join(body), "classes": len(select),
            "generalizations": gens, "associations": assocs,
            "associationsSkipped": skipped,
            "geometry": {k: list(v) for k, v in pos.items()},
            "sizeOf": {k: list(payload[k]["size"]) for k in payload}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--facts", default=str(DEFAULT_FACTS))
    ap.add_argument("--package", help="select every class with this omgPackage")
    ap.add_argument("--classes", help="comma-separated IRIs, e.g. uml:Classifier,uml:Feature")
    ap.add_argument("--assoc", action="append", default=[],
                    help="owner.feature to draw as a navigable association (repeatable)")
    ap.add_argument("--sizes", help="JSON of TeX-measured box widths from measure_boxes.py")
    ap.add_argument("--layout-json", help="write the computed box geometry here")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    facts = json.loads(Path(args.facts).read_text())
    classes = facts["classes"]
    if args.classes:
        select = {c.strip() for c in args.classes.split(",") if c.strip()}
        missing = sorted(select - set(classes))
        if missing:
            print(f"unknown classes: {missing}", file=sys.stderr)
            return 2
    elif args.package:
        select = {k for k, v in classes.items() if v.get("omgPackage") == args.package}
    else:
        print("select with --package or --classes", file=sys.stderr)
        return 2
    if not select:
        print("selection is empty", file=sys.stderr)
        return 2

    assoc = []
    for spec in args.assoc:
        owner, _, name = spec.partition(".")
        assoc.append((owner, name))

    sizes = json.loads(Path(args.sizes).read_text()) if args.sizes else None
    diagram = build(facts, select, assoc, sizes)
    if args.layout_json:
        Path(args.layout_json).write_text(json.dumps(
            {"boxes": {k: diagram["geometry"][k] for k in diagram["geometry"]},
             "sizes": {k: diagram["sizeOf"][k] for k in diagram["sizeOf"]}},
            indent=2) + "\n")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(PREAMBLE + diagram["tex"] + "\n" + POSTAMBLE)
    print(json.dumps({"out": args.out, "classes": diagram["classes"],
                      "generalizations": diagram["generalizations"],
                      "associations": diagram["associations"],
                      "associationsSkipped": diagram["associationsSkipped"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
