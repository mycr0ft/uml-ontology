# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Jon R. Fox
"""Generate SHACL shapes for the UML-family ontology.

Two sources, graded like the ontology itself:

1. **stated cardinality** — every metamodel feature whose type is a metaclass becomes a
   ``sh:property`` on its owner with ``sh:minCount``/``sh:maxCount`` from the metamodel's
   own ``lo``/``hi``. This is the metamodel's rule, not an interpretation, and it covers
   the whole property space.
2. **stated OCL, translated** — a deliberately small whitelist of constraint forms whose
   meaning maps onto SHACL without interpretation:

       self.p->isEmpty()            sh:maxCount 0
       self.p->notEmpty()           sh:minCount 1
       self.p->size() = N           min N, max N
       self.p->size() >= N | > N    sh:minCount N (N+1 for >)
       self.p->size() <= N | < N    sh:maxCount N (N-1 for <)
       not self.p.oclIsUndefined()  sh:minCount 1
       self.p.oclIsUndefined()      sh:maxCount 0
       self.p.oclIsKindOf(T)        sh:class T      (T a known class)
       X->forAll(x | x.p->notEmpty())  sh:minCount 1 on p  (one level, universal only)

Everything else is **not** translated and is written to ``untranslated.json`` with the
reason it was refused. A constraint silently dropped is worse than one honestly queued:
the count of what SHACL covers is only meaningful next to what it does not.

Usage:
    python scripts/build_shacl.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import build_ontology as onto                                    # noqa: E402

SH = "http://www.w3.org/ns/shacl#"
BASE = onto.DEFAULT_BASE

#: reasons a constraint was refused, in the order they are tested
REFUSAL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("no serialized body", "the metamodel carries a placeholder, not OCL text"),
    ("allInstances", "a global quantification over the whole model: needs a rule engine"),
    ("closure", "transitive closure over a navigation: needs a rule engine"),
    ("specializesFromLibrary", "a model-library predicate with no graph equivalent here"),
    ("mustBeOwned", "an operation, not a property test"),
    ("maySpecializeType", "an operation, not a property test"),
    ("-- ", "the specification itself declines to express it in OCL"),
    ("implies", "an implication between property tests: not expressible as a shape count"),
    ("select(", "a filtered selection: needs a rule engine"),
    ("excludes(", "a set operation over a navigation: needs a rule engine"),
    ("includes(", "a set operation over a navigation: needs a rule engine"),
    ("oclAsType", "a cast, which SHACL has no equivalent for"),
)

INT = r"(\d+)"
PROP = r"self\.([A-Za-z_][A-Za-z_0-9]*)"


def classify(body: str) -> str | None:
    """Return the refusal reason for a body, or None when it is out of scope but unknown."""
    for needle, reason in REFUSAL_PATTERNS:
        if needle in body:
            return reason
    return None


FACETS = ("minCount", "maxCount", "class")


def _declaring(owner: str, name: str, resolver) -> dict | None:
    """The property *name* as seen from *owner*, tagged with the class that declares it."""
    return resolver(owner, name)


def _clause(text: str, props: dict[str, dict], known: set[str],
            resolver=None) -> list[dict] | None:
    """Translate ONE clause; return property facets along a path chain, or None.

    A chain (``self.a.b->size() = 1``) becomes nested facets: the outer property, then the
    facets on the property of its range. ``source``/``target`` are derived unions in UML, and
    they are emitted as properties, so the second hop resolves to a real IRI.
    """
    m = re.fullmatch(PROP + r"(?:\.([A-Za-z_][A-Za-z_0-9]*))?" + r"(.*)", text)
    if not m:
        return None
    first, second, rest = m.group(1), m.group(2), m.group(3)
    if first not in props:
        return None

    facets: dict = {}
    if rest == "->isEmpty()":
        facets = {"maxCount": 0, "form": "isEmpty"}
    elif rest == "->notEmpty()":
        facets = {"minCount": 1, "form": "notEmpty"}
    elif (sm := re.fullmatch(r"->size\(\)\s*(=|>=|<=|>|<)\s*(\d+)", rest)):
        op, n = sm.group(1), int(sm.group(2))
        facets = {"=": {"minCount": n, "maxCount": n, "form": "size ="},
                  ">=": {"minCount": n, "form": "size >="},
                  ">": {"minCount": n + 1, "form": "size >"},
                  "<=": {"maxCount": n, "form": "size <="},
                  "<": {"maxCount": max(0, n - 1), "form": "size <"}}[op]
    elif (km := re.fullmatch(r"\.oclIs(?:KindOf|TypeOf)\(([A-Za-z_:]+)\)", rest)):
        target = km.group(1).split("::")[-1]
        if f"uml:{target}" not in known:
            return None
        facets = {"class": f"uml:{target}", "form": "oclIsKindOf"}
    elif rest == ".oclIsUndefined()" and False:
        facets = {"maxCount": 0, "form": "oclIsUndefined()"}
    else:
        return None

    decl = props[first].get("declOwner", props[first]["owner"])
    leaf = {"path": first, "declOwner": decl, **facets}
    if second:
        range_key = props[first]["range"]
        if range_key not in known:
            return None
        nested = resolver(range_key, second) if resolver else None
        if nested is None:
            return None                      # the hop is not a feature of that type
        return [leaf, {"path": second, **facets, "nestedOwner": range_key,
                       "declOwner": nested["declOwner"]}]
    return [leaf]


def translate(body: str, props: dict[str, dict], known: set[str],
              resolver=None) -> dict | None:
    """Translate one OCL body, including conjunctions of translatable clauses.

    A conjunction is translated only if EVERY clause translates: applying the clauses that
    happened to parse would publish a weaker rule under the constraint's name, which is the
    failure mode the untranslated register exists to avoid.
    """
    text = re.sub(r"\s+", " ", body).strip()
    if not text:
        return None

    # bare negation forms first: they are their own shape of statement
    m = re.fullmatch(r"not " + PROP + r"(?:\.([A-Za-z_][A-Za-z_0-9]*))?\.oclIsUndefined\(\)", text)
    if m and m.group(1) in props:
        leaf = {"path": m.group(1), "minCount": 1, "form": "not oclIsUndefined()"}
        if m.group(2):
            range_key = props[m.group(1)]["range"]
            if range_key not in known:
                return None
            nested = resolver(range_key, m.group(2)) if resolver else None
            if nested is None:
                return None
            return {"paths": [[leaf, {"path": m.group(2), "minCount": 1,
                                     "nestedOwner": range_key,
                                     "declOwner": nested["declOwner"],
                                     "form": "not oclIsUndefined()"}]]}
        return {"paths": [[leaf]]}
    m = re.fullmatch(PROP + r"(?:\.([A-Za-z_][A-Za-z_0-9]*))?\.oclIsUndefined\(\)", text)
    if m and m.group(1) in props:
        leaf = {"path": m.group(1), "maxCount": 0, "form": "oclIsUndefined()"}
        if m.group(2):
            range_key = props[m.group(1)]["range"]
            if range_key not in known:
                return None
            nested = resolver(range_key, m.group(2)) if resolver else None
            if nested is None:
                return None
            return {"paths": [[leaf, {"path": m.group(2), "maxCount": 0,
                                     "nestedOwner": range_key,
                                     "declOwner": nested["declOwner"],
                                     "form": "oclIsUndefined()"}]]}
        return {"paths": [[leaf]]}

    # a universal over a navigation, one level deep: X->forAll(x | x.p->notEmpty())
    m = re.fullmatch(r"self\.([A-Za-z_][A-Za-z_0-9]*)->forAll\(\s*([a-z])\s*\|\s*"
                     r"\2\.([A-Za-z_][A-Za-z_0-9]*)->notEmpty\(\)\s*\)", text)
    if m and m.group(1) in props:
        range_key = props[m.group(1)]["range"]
        if range_key in known:
            return {"paths": [[{"path": m.group(1), "minCount": 1,
                                "form": "forAll x | x.p->notEmpty()"}]]}

    # conjunctions: every clause must translate, or none is applied
    clauses = [c.strip() for c in re.split(r"\s+and\s+", text)]
    if len(clauses) > 1:
        chains = [_clause(c, props, known, resolver) for c in clauses]
        if any(chain is None for chain in chains):
            return None
        # One path per clause.  Chaining the clauses into a single navigation would read
        # "the target of the source of X", which is not what a conjunction means.
        return {"paths": [chain for chain in chains if chain], "conjunction": len(clauses)}

    single = _clause(text, props, known, resolver)
    return {"paths": [single]} if single else None


def build() -> dict:
    model = onto.build()
    classes = model["classes"]
    props = {(p["owner"], p["name"]): p for p in model["properties"]}
    by_owner: dict[str, list[dict]] = {}
    for prop in model["properties"]:
        by_owner.setdefault(prop["owner"], []).append(prop)

    shapes: dict[str, dict] = {}
    translated: list[dict] = []
    untranslated: list[dict] = []

    def visible_properties(key: str, seen: set[str] | None = None) -> dict[str, dict]:
        """Own and inherited properties, each tagged with its declaring class."""
        seen = set() if seen is None else seen
        if key in seen:
            return {}
        seen.add(key)
        found: dict[str, dict] = {}
        for prop in by_owner.get(key, []):
            found[prop["name"]] = {**prop, "declOwner": prop["owner"]}
        for base in classes.get(key, {}).get("bases", []):
            for name, prop in visible_properties(base, seen).items():
                found.setdefault(name, prop)
        return found

    # 1. stated cardinality, per owner class and feature
    for owner, owner_props in by_owner.items():
        shape = shapes.setdefault(owner, {"cardinality": [], "constraints": []})
        for prop in owner_props:
            lo, hi = prop["lo"], prop["hi"]
            entry = {"path": prop["name"], "owner": owner, "range": prop["range"]}
            if isinstance(lo, int) and lo > 0:
                entry["minCount"] = lo
            if str(hi) != "*":
                try:
                    hi_int = int(hi)
                except (TypeError, ValueError):
                    hi_int = None
                if hi_int is not None:
                    entry["maxCount"] = hi_int
            if "minCount" in entry or "maxCount" in entry:
                shape["cardinality"].append(entry)

    # 2. the whitelisted OCL subset
    modules = onto.runtime_modules()
    for prefix, module_name, _label in onto.MODULES:
        for name, cls in onto.collect_classes(modules[prefix], module_name).items():
            owner_key = f"{prefix}:{name}"
            owner_props = visible_properties(owner_key)
            for cname, body in (getattr(cls, "CONSTRAINTS", ()) or ()):
                if not isinstance(body, str) or not body.strip():
                    untranslated.append({"owner": owner_key, "name": cname, "body": "",
                                         "reason": "empty body"})
                    continue
                result = translate(body, owner_props, set(classes),
                                   resolver=lambda owner, name: visible_properties(owner).get(name))
                if result is None:
                    reason = classify(body) or "outside the translatable subset"
                    untranslated.append({"owner": owner_key, "name": cname,
                                         "body": body.strip()[:400], "reason": reason})
                    continue
                result.update({"owner": owner_key, "name": cname,
                               "body": body.strip()[:400]})
                shapes.setdefault(owner_key, {"cardinality": [], "constraints": []})
                shapes[owner_key]["constraints"].append(result)
                translated.append(result)

    return {"shapes": shapes, "translated": translated,
            "untranslated": untranslated, "model": model}


def _esc(text: str) -> str:
    return onto._esc(text)


def emit(model: dict, base: str) -> tuple[str, int]:
    onto_model = model["model"]
    prefixes = sorted({key.split(":", 1)[0] for key in onto_model["classes"]})
    lines = [
        "@prefix sh:   <http://www.w3.org/ns/shacl#> .",
        "@prefix owl:  <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix umlmeta: <https://mycr0ft.github.io/umlmeta/ns#> .",
    ]
    for prefix in prefixes:
        lines.append(f"@prefix {prefix}: <{base}/{prefix}#> .")
    lines.append("")
    lines.append(f"<{base}/shapes> a owl:Ontology ;")
    lines.append('    rdfs:label "UML-family relationship shapes"@en ;')
    lines.append('    rdfs:comment "Generated SHACL for the UML-family relationship '
                 'ontology. Cardinality is the metamodel\'s own lo/hi; constraint facets '
                 'come from a whitelisted OCL subset, and every refused constraint is '
                 'listed in shapes/untranslated.json with its reason."@en ;')
    lines.append('    owl:versionInfo "1" .')
    lines.append("")

    n = 0
    for owner_key, shape in sorted(model["shapes"].items()):
        entries = shape["cardinality"] + shape["constraints"]
        if not entries:
            continue
        n += 1
        frags = ["a sh:NodeShape", f"sh:targetClass {owner_key}"]
        for entry in shape["cardinality"]:
            facets = [f"sh:path {entry['owner']}__{entry['path']}"]
            if "minCount" in entry:
                facets.append(f"sh:minCount {entry['minCount']}")
            if "maxCount" in entry:
                facets.append(f"sh:maxCount {entry['maxCount']}")
            facets.append(f'umlmeta:grade "stated"')
            frags.append("sh:property [ " + " ; ".join(facets) + " ]")
        for entry in shape["constraints"]:
            for chain in entry["paths"]:
                # innermost link first, then wrap: SHACL nests the second hop as a property
                # shape on the first, so a two-hop path stays one property shape
                inner = chain[-1]
                facets = [f"sh:path {inner.get('declOwner', inner.get('nestedOwner', entry['owner']))}__{inner['path']}"]
                for facet in ("minCount", "maxCount"):
                    if facet in inner:
                        facets.append(f"sh:{facet} {inner[facet]}")
                if inner.get("class"):
                    facets.append(f"sh:class {inner['class']}")
                body = " ; ".join(facets)
                for link in reversed(chain[:-1]):
                    body = (f"sh:path {link.get('declOwner', entry['owner'])}__{link['path']} ; "
                            f"sh:property [ {body} ]")
                frags.append(
                    "sh:property [ " + body
                    + ' ; umlmeta:grade "stated"'
                    + f' ; umlmeta:oclName "{_esc(entry["name"])}"'
                    + f' ; umlmeta:oclBody "{_esc(entry["body"])}" ]')
        lines.append(onto._block(f"<{base}/shapes#{owner_key.replace(':', '_')}>", frags))
    return "\n".join(lines) + "\n", n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "shapes"))
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args(argv)

    model = build()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ttl, shape_count = emit(model, args.base.rstrip("/"))
    (out / "uml-family-shapes.ttl").write_text(ttl, encoding="utf-8")
    reasons: dict[str, int] = {}
    for row in model["untranslated"]:
        reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
    (out / "untranslated.json").write_text(json.dumps({
        "counts": {
            "constraintsTotal": len(model["translated"]) + len(model["untranslated"]),
            "translated": len(model["translated"]),
            "untranslated": len(model["untranslated"]),
            "shapes": shape_count,
        },
        "refusalReasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "untranslated": model["untranslated"],
    }, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "shapes": shape_count,
        "translatedConstraints": len(model["translated"]),
        "untranslatedConstraints": len(model["untranslated"]),
        "refusalReasons": reasons,
    }, indent=2))
    print(f"wrote {out / 'uml-family-shapes.ttl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
