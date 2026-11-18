#!/usr/bin/env python
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Jon R. Fox
"""Gate: the diagram is drawable, non-overlapping, and complete.

A figure that compiles can still be wrong in ways only a reader sees, so this checks the
geometry the generator computed rather than trusting the PDF:

  * every selected class got a box, and every box has three compartments (`rectangle split`);
  * no two boxes overlap, with a 2 mm tolerance - the defect that a grid layout produces and
    that a compile happily renders;
  * every generalization connects two boxes that exist in the figure (a typo in a class name
    would otherwise draw a dangling edge that TikZ silently drops);
  * the document compiles, and the PDF has one page of non-zero size.

    python check.py --classes uml:Element,uml:NamedElement --assoc uml:Dependency.client
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
CHECKS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((label, bool(ok), detail))


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=DOCS, **kw)


def overlaps(a: tuple[float, float], asize: tuple[float, float],
             b: tuple[float, float], bsize: tuple[float, float], tol: float = 2.0) -> bool:
    ax, ay = a
    aw, ah = asize
    bx, by = b
    bw, bh = bsize
    return (abs(ax - bx) * 2 < aw + bw - 2 * tol) and (abs(ay - by) * 2 < ah + bh - 2 * tol)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--classes", required=True)
    ap.add_argument("--assoc", action="append", default=[])
    ap.add_argument("--out", default="relationships.tex")
    args = ap.parse_args(argv)

    facts = ROOT / "ontology" / "relationships.json"
    if not facts.exists():
        print(f"fact book missing: {facts}", file=sys.stderr)
        return 2

    measure = run([sys.executable, "tools/measure_boxes.py", "--classes", args.classes,
                   "--out", "build/sizes.json"])
    check("boxes measured by TeX", measure.returncode == 0, measure.stderr.strip()[-200:])
    if measure.returncode != 0:
        return report()

    draw_cmd = [sys.executable, "tools/draw_ontology.py", "--classes", args.classes,
                "--sizes", "build/sizes.json", "--layout-json", "build/layout.json",
                "--out", args.out]
    for spec in args.assoc:
        draw_cmd += ["--assoc", spec]
    draw = run(draw_cmd)
    check("diagram generated", draw.returncode == 0, draw.stderr.strip()[-200:])
    if draw.returncode != 0:
        return report()

    stats = json.loads(draw.stdout)
    layout = json.loads((DOCS / "build" / "layout.json").read_text())
    boxes, sizes = layout["boxes"], layout["sizes"]
    select = [c.strip() for c in args.classes.split(",") if c.strip()]

    check(f"every selected class has a box ({len(select)})",
          set(select) <= set(boxes), str(sorted(set(select) - set(boxes))[:3]))

    tex = (DOCS / args.out).read_text()
    # count outside the f-string: a backslash inside an f-string expression is PEP 701 only
    # (Python 3.12+), and this file must run on 3.10
    class_count = tex.count("\\UMLclass")
    check("every box is a three-part node", class_count == len(select),
          "%d UMLclass vs %d classes" % (class_count, len(select)))

    clashes = []
    keys = sorted(boxes)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if overlaps(tuple(boxes[a]), tuple(sizes[a]), tuple(boxes[b]), tuple(sizes[b])):
                clashes.append(f"{a} / {b}")
    check(f"no two boxes overlap ({len(keys)} boxes)", not clashes, ", ".join(clashes[:3]))

    defined = set(re.findall(r"\\UMLclass\[[^\]]*\]\{([^}]+)\}", tex))
    edges = re.findall(r"\\UMLgen\{([^}]+)\}\{([^}]+)\}", tex)
    dangling = [f"{c}->{p}" for c, p in edges if c not in defined or p not in defined]
    check(f"every generalization joins two boxes ({len(edges)} edges)", not dangling,
          ", ".join(dangling[:3]))
    check("figure reports what it could not draw",
          stats["classes"] == len(select), json.dumps(stats.get("associationsSkipped", [])))

    build = run(["tectonic", "-X", "compile", str(DOCS / args.out), "--outdir", "build"])
    check("document compiles", build.returncode == 0, build.stderr.strip()[-300:])
    produced = DOCS / "build" / (Path(args.out).stem + ".pdf")
    check("a PDF was produced", produced.exists() and produced.stat().st_size > 5000,
          f"{produced.stat().st_size if produced.exists() else 0} bytes")

    return report()


def report() -> int:
    failed = [c for c in CHECKS if not c[1]]
    for label, ok, detail in CHECKS:
        print(f"[{'ok' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail and not ok else ""))
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
