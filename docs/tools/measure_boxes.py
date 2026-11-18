#!/usr/bin/env python
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Jon R. Fox
"""Measure class-box dimensions with TeX itself, then write them as JSON.

Estimating text width from a character count is what makes boxes overlap: a proportional bold
header and a monospaced `(composite)` suffix have nothing to do with a per-character constant.
So the measurement is done by the engine that will typeset the figure.

The probe file typesets no page: it sets each class's widest line into a length and writes the
value with \\typeout, which tectonic prints. A row height is measured the same way and multiplied
by the row count, which is exact because every row is a single line.

    python tools/measure_boxes.py --facts ../uml-ontology/ontology/relationships.json \\
        --classes uml:Classifier,uml:Feature --out build/sizes.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent          # docs/
ROOT = DOCS.parent                                   # repo root
DEFAULT_FACTS = ROOT / "ontology" / "relationships.json"

PROBE = r"""\documentclass[varwidth=30cm,border=0pt]{standalone}
\usepackage{umltikz}
\newlength{\umltkw}
\newwrite\umlmeas
\begin{document}
\immediate\openout\umlmeas=sizes.txt\relax
%% one line per class: the widest thing that decides the box width
%(body)s
\immediate\closeout\umlmeas
\end{document}
"""

WIDTH_LINE = r"""\settowidth{\umltkw}{%(text)s}\immediate\write\umlmeas{UMW %(key)s \the\umltkw}"""


def esc(text: str) -> str:
    for bad, good in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                      ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}")):
        text = text.replace(bad, good)
    return text


def rows_for(classes: dict, props: list[dict], key: str) -> tuple[str, str, str]:
    entry = classes[key]
    name = key.split(":", 1)[-1]
    stereo = f"«{entry['stereotype'].split(':')[-1]}»" if entry.get("stereotype") else ""
    attrs = [f"+ {p['name']} : {p['range'].split(':')[-1]} [{p['lo']}..{p['hi']}]"
             + (" (composite)" if p.get("composite") else "")
             for p in props if p["owner"] == key]
    return name, stereo, "\n".join(attrs)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--facts", default=str(DEFAULT_FACTS))
    ap.add_argument("--classes", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    facts = json.loads(Path(args.facts).read_text())
    select = [c.strip() for c in args.classes.split(",") if c.strip()]
    lines = []
    for key in select:
        name, stereo, attrs = rows_for(facts["classes"], facts["properties"], key)
        candidates = [rf"{{\small\bfseries {esc(name)}}}"]
        if stereo:
            candidates.append(rf"{{\scriptsize\ttfamily {esc(stereo)}}}")
        for attr in attrs.splitlines():
            candidates.append(rf"{{\scriptsize\ttfamily {esc(attr)}}}")
        widest = max(candidates, key=len)
        lines.append(WIDTH_LINE % {"text": widest, "key": key})
    # a row height, measured once: every compartment row is one line
    lines.append(r"\settoheight{\umltkw}{\scriptsize\ttfamily Ag}\immediate\write\umlmeas{UMW ROW \the\umltkw}")
    lines.append(r"\settoheight{\umltkw}{\small\bfseries Ag}\immediate\write\umlmeas{UMW HEAD \the\umltkw}")

    probe = DOCS / "probe.tex"          # beside umltikz.sty: tectonic looks there
    (DOCS / "build").mkdir(parents=True, exist_ok=True)
    probe.write_text(PROBE % {"body": "\n".join(lines)})
    run = subprocess.run(["tectonic", "-X", "compile", str(probe), "--outdir",
                          str(DOCS / "build"), "--keep-logs"], capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stdout[-800:] + run.stderr[-800:], file=sys.stderr)
        return run.returncode

    measured = (DOCS / "build" / "sizes.txt")
    if not measured.exists():
        print("measurement failed: the TeX run wrote no sizes.txt", file=sys.stderr)
        return 3
    sizes: dict[str, float] = {}
    for match in re.finditer(r"UMW (\S+) ([\d.]+)pt", measured.read_text()):
        sizes[match.group(1)] = float(match.group(2))
    if "ROW" not in sizes or "HEAD" not in sizes:
        print("measurement failed: no row/head height in the TeX output", file=sys.stderr)
        return 3
    Path(args.out).write_text(json.dumps(sizes, indent=2) + "\n")
    print(json.dumps({"measured": len(sizes) - 2, "rowPt": sizes["ROW"],
                      "headPt": sizes["HEAD"], "out": args.out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
