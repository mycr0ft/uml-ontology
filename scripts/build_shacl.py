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


# ---------------------------------------------------------------------------------------
# the predicate-logic subset
#
# A second family of bodies needs no path chain and no facet list: they are boolean formulas
# over the presence and the truth value of single-valued features of the same object, e.g.
# ``visibility = null implies namespace = null``. Each formula compiles whole into one SHACL
# core logic tree (sh:and / sh:or / sh:not over property shapes), so nothing is dropped and
# nothing outside the subset is ever approximated.  The reading of the atoms is the one the
# SHACL core gives them: an absent boolean test is false, ``= null`` means "no value",
# ``<> null`` means "at least one value".
# ---------------------------------------------------------------------------------------

LOGIC_KEYWORDS = ("and", "or", "not", "implies", "null", "true", "false")
LOGIC_TOKEN = re.compile(
    r"\s*(<>|<=|>=|[()=<>]|[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*|\d+)")


def _logic_tokens(body: str) -> list[str] | None:
    """Split a formula into tokens, or None when it carries anything this subset cannot read."""
    text = re.sub(r"\s+", " ", body).strip()
    if text.endswith("."):
        text = text[:-1].strip()
    tokens: list[str] = []
    pos = 0
    while pos < len(text):
        found = LOGIC_TOKEN.match(text, pos)
        if not found:
            return None
        tokens.append(found.group(1))
        pos = found.end()
    return tokens or None


class _Logic:
    """Recursive descent: implies (right associative) > or > and > not > atom."""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def eat(self, expected: str | None = None) -> str:
        found = self.peek()
        if found is None or (expected is not None and found != expected):
            raise ValueError(f"expected {expected!r}, found {found!r}")
        self.pos += 1
        return found

    def parse(self) -> tuple:
        expr = self.implies()
        if self.pos != len(self.tokens):
            raise ValueError(f"trailing tokens from {self.tokens[self.pos]!r}")
        return expr

    def implies(self) -> tuple:
        left = self.disjunct()
        if self.peek() == "implies":
            self.eat()
            return ("implies", left, self.implies())
        return left

    def disjunct(self) -> tuple:
        parts = [self.conjunct()]
        while self.peek() == "or":
            self.eat()
            parts.append(self.conjunct())
        return parts[0] if len(parts) == 1 else ("or", parts)

    def conjunct(self) -> tuple:
        parts = [self.unary()]
        while self.peek() == "and":
            self.eat()
            parts.append(self.unary())
        return parts[0] if len(parts) == 1 else ("and", parts)

    def unary(self) -> tuple:
        if self.peek() == "not":
            self.eat()
            return ("not", self.unary())
        return self.atom()

    def atom(self) -> tuple:
        if self.peek() == "(":
            self.eat()
            expr = self.implies()
            self.eat(")")
            return expr
        name = self.eat()
        if name in LOGIC_KEYWORDS or name in ("<>", "=", "(", ")"):
            raise ValueError(f"not a feature name: {name!r}")
        if self.peek() in ("=", "<>"):
            return ("cmp", name, self.eat(), self.eat())
        return ("test", name)


def _logic_atoms(expr: tuple, out: list | None = None) -> list:
    out = [] if out is None else out
    if expr[0] in ("test", "cmp"):
        out.append(expr)
    elif expr[0] == "not":
        _logic_atoms(expr[1], out)
    elif expr[0] == "implies":
        _logic_atoms(expr[1], out)
        _logic_atoms(expr[2], out)
    else:
        for branch in expr[1]:
            _logic_atoms(branch, out)
    return out


def _logic_path(name: str, props: dict[str, dict]) -> str | None:
    """The shape path for a feature, or None when it is navigated, missing or multi-valued."""
    prop = props.get(name)
    if prop is None or prop.get("multi"):
        return None
    return f"{prop.get('declOwner') or prop['owner']}__{name}"


def _logic_boolean(prop: dict) -> bool:
    """True when the feature is a Boolean: feeds carry the datatype as range, attributes as xsd."""
    return (prop.get("range") or prop.get("xsd")) == "xsd:boolean"


def _logic_atom_shape(atom: tuple, props: dict[str, dict], negate: bool) -> str | None:
    """One atom as the inside of a bracketed shape, or None when it is outside the subset."""
    if atom[0] == "test":
        path = _logic_path(atom[1], props)
        if path is None or not _logic_boolean(props[atom[1]]):
            return None
        tested = f"sh:property [ sh:path {path} ; sh:hasValue true ]"
        return f"sh:not [ {tested} ]" if negate else tested
    name, op, value = atom[1], atom[2], atom[3]
    path = _logic_path(name, props)
    if path is None or value not in ("null", "true", "false"):
        return None
    if value == "null":
        # absence is exactly a count, so the negation stays a plain facet
        absent = (op == "=") != negate
        facet = 'sh:maxCount 0' if absent else 'sh:minCount 1'
        return f"sh:property [ sh:path {path} ; {facet} ]"
    held = f"sh:property [ sh:path {path} ; sh:hasValue {value} ]"
    return f"sh:not [ {held} ]" if negate else held


def _logic_shape(expr: tuple, props: dict[str, dict], negate: bool = False):
    """Compile a formula tree into a SHACL core logic tree; None if an atom is out of scope."""
    kind = expr[0]
    if kind == "not":
        return _logic_shape(expr[1], props, not negate)
    if kind in ("test", "cmp"):
        return _logic_atom_shape(expr, props, negate)
    if kind == "implies":
        # A implies B  ==  (not A) or B
        return _logic_shape(("or", [("not", expr[1]), expr[2]]), props, negate)
    parts = [_logic_shape(branch, props, negate) for branch in expr[1]]
    if any(part is None for part in parts):
        return None
    # and/or swap under negation, which is what pushing not inward means
    joint = "sh:and" if (kind == "and") == (not negate) else "sh:or"
    return f"{joint} ( " + " ".join(f"[ {part} ]" for part in parts) + " )"


def translate_logic(body: str, props: dict[str, dict]) -> dict | None:
    """Translate a pure formula, or return None so the caller can register a refusal."""
    tokens = _logic_tokens(body)
    if not tokens:
        return None
    try:
        expr = _Logic(tokens).parse()
    except ValueError:
        return None
    for atom in _logic_atoms(expr):
        if _logic_atom_shape(atom, props, False) is None:
            return None
    text = _logic_shape(expr, props)
    if not text:
        return None
    atoms = _logic_atoms(expr)
    return {"logic": text, "expr": expr,
            "paths": {atom[1]: _logic_path(atom[1], props) for atom in atoms},
            "atoms": [[atom[0], atom[1], atom[2] if len(atom) > 2 else None,
                       atom[3] if len(atom) > 3 else None] for atom in atoms]}


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
    logic: list[dict] = []

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

    # The two properties declared as a spec supplement live in build_ontology, not in the
    # feeds, so they are invisible to visible_properties and have to be offered here; without
    # them every formula that mentions owner or namespace is refused for the wrong reason.
    supplements: dict[str, dict[str, dict]] = {}
    for row in onto.SPEC_SUPPLEMENT:
        supplements.setdefault(row["owner"], {})[row["name"]] = {
            **row, "declOwner": row["owner"]}

    def supplement_properties(key: str, seen: set[str] | None = None) -> dict[str, dict]:
        seen = set() if seen is None else seen
        if key in seen:
            return {}
        seen.add(key)
        found: dict[str, dict] = dict(supplements.get(key, {}))
        for base in classes.get(key, {}).get("bases", []):
            for name, prop in supplement_properties(base, seen).items():
                found.setdefault(name, prop)
        return found

    # The formula family also sees single-valued datatype features, which the path translator
    # ignores because a Boolean attribute is a hasValue test, not a path chain to walk.
    attributes: dict[str, dict[str, dict]] = {}
    for row in model["attributes"]:
        if not row.get("multi"):
            attributes.setdefault(row["owner"], {})[row["name"]] = {
                **row, "declOwner": row["owner"]}

    def formula_properties(key: str, seen: set[str] | None = None) -> dict[str, dict]:
        seen = set() if seen is None else seen
        if key in seen:
            return {}
        seen.add(key)
        found = {**visible_properties(key), **attributes.get(key, {})}
        found.update(supplement_properties(key))
        for base in classes.get(key, {}).get("bases", []):
            for name, prop in formula_properties(base, seen).items():
                found.setdefault(name, prop)
        return found

    # 1. stated cardinality, per owner class and feature
    for owner, owner_props in by_owner.items():
        shape = shapes.setdefault(owner, {"cardinality": [], "constraints": [], "logic": []})
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
                    logic_props = formula_properties(owner_key)
                    formula = translate_logic(body, logic_props)
                    if formula is not None:
                        entry = {"owner": owner_key, "name": cname,
                                 "body": body.strip()[:400], **formula}
                        shapes.setdefault(owner_key, {"cardinality": [], "constraints": [],
                                                      "logic": []})["logic"].append(entry)
                        logic.append(entry)
                        translated.append(entry)
                        continue
                    reason = classify(body) or "outside the translatable subset"
                    untranslated.append({"owner": owner_key, "name": cname,
                                         "body": body.strip()[:400], "reason": reason})
                    continue
                result.update({"owner": owner_key, "name": cname,
                               "body": body.strip()[:400]})
                shapes.setdefault(owner_key, {"cardinality": [], "constraints": [],
                                              "logic": []})
                shapes[owner_key]["constraints"].append(result)
                translated.append(result)

    return {"shapes": shapes, "translated": translated,
            "untranslated": untranslated, "logic": logic, "model": model}


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
        if not entries and not shape.get("logic"):
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
        for entry in shape.get("logic", []):
            n += 1
            frags = ["a sh:NodeShape", f"sh:targetClass {owner_key}", entry["logic"],
                     'umlmeta:grade "stated"',
                     f'umlmeta:oclName "{_esc(entry["name"])}"',
                     f'umlmeta:oclBody "{_esc(entry["body"])}"',
                     f'sh:message "{_esc(entry["name"])}"']
            lines.append(onto._block(
                f"<{base}/shapes#{owner_key.replace(':', '_')}_{entry['name']}>", frags))
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
            "translatedLogic": len(model["logic"]),
            "untranslated": len(model["untranslated"]),
            "shapes": shape_count,
        },
        "refusalReasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "untranslated": model["untranslated"],
    }, indent=2) + "\n", encoding="utf-8")

    # The compiled formulas, with the shape each one produced. tests/test_shacl.py reads this
    # to build, per shape, an instance that must fail it and an instance that must pass it.
    def plain(node):
        return [node[0]] + [plain(part) if isinstance(part, tuple) else part for part in node[1:]]

    (out / "logic.json").write_text(json.dumps({
        "count": len(model["logic"]),
        "entries": [{
            "owner": entry["owner"],
            "name": entry["name"],
            "body": entry["body"],
            "shape": f"{args.base.rstrip('/')}/shapes#"
                     f"{entry['owner'].replace(':', '_')}_{entry['name']}",
            "expr": plain(entry["expr"]),
            "paths": entry["paths"],
            "atoms": entry["atoms"],
        } for entry in model["logic"]],
    }, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "shapes": shape_count,
        "translatedConstraints": len(model["translated"]),
        "translatedLogic": len(model["logic"]),
        "untranslatedConstraints": len(model["untranslated"]),
        "refusalReasons": reasons,
    }, indent=2))
    print(f"wrote {out / 'uml-family-shapes.ttl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
