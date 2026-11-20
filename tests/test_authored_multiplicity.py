#!/usr/bin/env python
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Jon R. Fox
"""Validate authored multiplicity: a bound a model writes, not a bound the metamodel states.

The generated shapes cap each end at one lowerValue and one upperValue. Everything that makes
a bound *mean* something lives in shapes/authored-multiplicity.ttl, and this file is the proof
that those shapes fire and fire on the right thing. Each case asserts the report names the
constraint that should have caught it: a shape pointed at the wrong property still fails a
graph, and would still pass a test that only looked at ``conforms``.

Run:  python tests/test_authored_multiplicity.py      (needs pyshacl + rdflib)
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY = ROOT / "ontology" / "uml-family-relationships.ttl"
SHAPES = [ROOT / "shapes" / "uml-family-shapes.ttl",
          ROOT / "shapes" / "authored-multiplicity.ttl"]

PREFIXES = """\
@prefix uml:  <https://mycr0ft.github.io/uml-ontology/uml#> .
@prefix ex:   <https://example.org/model#> .
"""

#: the two ends of an association over Person, spelled once so the cases differ only in the
#: bounds they author
ENDS = """
ex:employment a uml:Association ;
    uml:Association__memberEnd ex:employee , ex:employer .
ex:employee a uml:Property ;
    uml:MultiplicityElement__upperValue ex:one .
ex:employer a uml:Property .
ex:one a uml:LiteralUnlimitedNatural ;
    uml:LiteralUnlimitedNatural__value 1 .
"""

#: (label, data in turtle, expected) where expected is None for a conformant graph, or the
#: message fragment of the constraint that must have fired
CASES: list[tuple[str, str, str | None]] = [
    (
        "1..* conforms",
        ENDS + """
        ex:employee uml:MultiplicityElement__lowerValue [
            a uml:LiteralInteger ; uml:LiteralInteger__value 1 ] .
        ex:employer uml:MultiplicityElement__lowerValue [
            a uml:LiteralInteger ; uml:LiteralInteger__value 0 ] .
        ex:employer uml:MultiplicityElement__upperValue [
            a uml:LiteralUnlimitedNatural ; uml:LiteralUnlimitedNatural__value "*" ] .
        """,
        None,
    ),
    (
        "2..2 conforms",
        ENDS + """
        ex:employer uml:MultiplicityElement__lowerValue [
            a uml:LiteralInteger ; uml:LiteralInteger__value 2 ] .
        ex:employer uml:MultiplicityElement__upperValue [
            a uml:LiteralInteger ; uml:LiteralInteger__value 2 ] .
        """,
        None,
    ),
    (
        "0..0 conforms (empty is a legal upper bound)",
        ENDS + """
        ex:employer uml:MultiplicityElement__lowerValue [
            a uml:LiteralInteger ; uml:LiteralInteger__value 0 ] .
        ex:employer uml:MultiplicityElement__upperValue [
            a uml:LiteralInteger ; uml:LiteralInteger__value 0 ] .
        """,
        None,
    ),
    (
        "a bound that is not a literal is rejected",
        ENDS + """
        ex:employer uml:MultiplicityElement__upperValue ex:Person .
        ex:Person a uml:Class .
        """,
        "must be a uml:LiteralInteger",
    ),
    (
        "an opaque expression bound conforms",
        ENDS + """
        ex:employer uml:MultiplicityElement__lowerValue [
            a uml:OpaqueExpression ;
            uml:OpaqueExpression__body "count(ownedAttribute)" ;
            uml:OpaqueExpression__language "OCL" ] .
        """,
        None,
    ),
    (
        "3..1 is rejected",
        ENDS + """
        ex:employer uml:MultiplicityElement__lowerValue [
            a uml:LiteralInteger ; uml:LiteralInteger__value 3 ] .
        ex:employer uml:MultiplicityElement__upperValue [
            a uml:LiteralInteger ; uml:LiteralInteger__value 1 ] .
        """,
        "exceeds upper bound",
    ),
    (
        "a negative integer bound is rejected",
        ENDS + """
        ex:employer uml:MultiplicityElement__lowerValue [
            a uml:LiteralInteger ; uml:LiteralInteger__value -1 ] .
        """,
        "non-negative integer",
    ),
    (
        "a negative unlimited natural bound is rejected",
        ENDS + """
        ex:employer uml:MultiplicityElement__upperValue [
            a uml:LiteralUnlimitedNatural ; uml:LiteralUnlimitedNatural__value -1 ] .
        """,
        "non-negative integer",
    ),
    (
        "a word in place of an unlimited natural is rejected",
        # "*" is the only string the type admits; anything else is not a multiplicity
        ENDS + """
        ex:employer uml:MultiplicityElement__upperValue [
            a uml:LiteralUnlimitedNatural ; uml:LiteralUnlimitedNatural__value "many" ] .
        """,
        "non-negative integer",
    ),
    (
        "an unlimited natural with no value is rejected",
        ENDS + """
        ex:employer uml:MultiplicityElement__upperValue [
            a uml:LiteralUnlimitedNatural ] .
        """,
        "non-negative integer",
    ),
    (
        "two values on one literal bound are rejected",
        ENDS + """
        ex:employer uml:MultiplicityElement__upperValue [
            a uml:LiteralInteger ; uml:LiteralInteger__value 1, 2 ] .
        """,
        "non-negative integer",
    ),
]


def load(paths: list[Path]):
    from rdflib import Graph

    graph = Graph()
    for path in paths:
        graph.parse(str(path), format="turtle")
    return graph


def validate(data_turtle: str, onto_graph, shapes_graph):
    from pyshacl import validate as pyshacl_validate

    from rdflib import Graph

    data = Graph()
    data.parse(data=PREFIXES + data_turtle, format="turtle")
    conforms, report_graph, _text = pyshacl_validate(
        data,
        shacl_graph=shapes_graph,
        ont_graph=onto_graph,
        inference="rdfs",
        abort_on_first=False,
    )
    return conforms, report_graph


def messages(report_graph) -> list[str]:
    from rdflib import Namespace
    from rdflib.namespace import RDF

    sh = Namespace("http://www.w3.org/ns/shacl#")
    rows = []
    for result in report_graph.subjects(RDF.type, sh.ValidationResult):
        message = report_graph.value(result, sh.resultMessage)
        path = report_graph.value(result, sh.resultPath)
        component = report_graph.value(result, sh.sourceConstraintComponent)
        focus = report_graph.value(result, sh.focusNode)
        source = str(report_graph.value(result, sh.sourceShape) or "").split("#")[-1]
        rows.append(f"{message or ''} shape={source} focus={focus} path={path} component="
                    f"{str(component or '').split('#')[-1]}")
    return rows


def main() -> int:
    onto_graph = load([ONTOLOGY])
    shapes_graph = load(SHAPES)
    print(f"ontology {len(onto_graph)} triples | shapes {len(shapes_graph)} triples | "
          f"{len(CASES) + 1} cases")

    failures = 0
    for label, data, expected in CASES:
        conforms, report_graph = validate(data, onto_graph, shapes_graph)
        rows = messages(report_graph)
        if expected is None:
            ok = conforms
            detail = "" if ok else f"unexpected violations: {rows[:3]}"
        else:
            joined = " ".join(rows)
            ok = (not conforms) and expected in joined
            detail = "" if ok else (
                f"conforms={conforms} expected a message containing {expected!r}; "
                f"got {rows[:3]}")
        print(f"[{'ok' if ok else 'FAIL'}] {label}")
        if not ok:
            failures += 1
            print(f"        {detail}")

    # the cross-bound rule is the one that cannot be stated without a query, so prove it is
    # reachable from the other side too: an upper bound alone never violates anything
    conforms, report_graph = validate(
        ENDS + """
        ex:employer uml:MultiplicityElement__upperValue [
            a uml:LiteralInteger ; uml:LiteralInteger__value 0 ] .
        """,
        onto_graph,
        shapes_graph,
    )
    print(f"[{'ok' if conforms else 'FAIL'}] a lone upper bound states no lower bound to exceed")
    if not conforms:
        failures += 1
        print(f"        unexpected violations: {messages(report_graph)[:3]}")

    print(f"\n{len(CASES) + 1 - failures}/{len(CASES) + 1} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
