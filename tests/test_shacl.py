#!/usr/bin/env python
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Jon R. Fox
"""Validate real instance graphs against the generated shapes with pyshacl.

A shape that parses is not a shape that works. Each case below is a small graph, and each
negative case asserts *which* shape fired (the property path in the report), not merely that
validation failed: a shape pointing at the wrong property would still make the graph
non-conformant, and would still pass a test that only checked `conforms == False`.

Run:  python tests/test_shacl.py           (needs pyshacl + rdflib)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY = ROOT / "ontology" / "uml-family-relationships.ttl"
SHAPES = ROOT / "shapes" / "uml-family-shapes.ttl"

PREFIXES = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix uml:  <https://mycr0ft.github.io/uml-ontology/uml#> .
@prefix sysml: <https://mycr0ft.github.io/uml-ontology/sysml#> .
@prefix ex:   <https://example.org/model#> .
"""

#: (label, data in turtle, expected) where expected is None for a conformant graph, or the
#: path IRI fragment the report must name
CASES: list[tuple[str, str, str | None]] = [
    (
        "association with two member ends conforms",
        """
        ex:wheel a uml:Association ;
            uml:Association__memberEnd ex:end1, ex:end2 .
        ex:end1 a uml:Property .
        ex:end2 a uml:Property .
        """,
        None,
    ),
    (
        "association with one member end is rejected",
        """
        ex:broken a uml:Association ;
            uml:Association__memberEnd ex:onlyEnd .
        ex:onlyEnd a uml:Property .
        """,
        "uml#Association__memberEnd",
    ),
    (
        "generalization with two generals is rejected",
        """
        ex:tangled a uml:Generalization ;
            uml:Generalization__general ex:parent1, ex:parent2 ;
            uml:Generalization__specific ex:child .
        ex:parent1 a uml:Class .
        ex:parent2 a uml:Class .
        ex:child a uml:Class .
        """,
        "uml#Generalization__general",
    ),
    (
        "a shape on a superclass reaches a subclass instance",
        # uml:Class inherits TypedElement__type [0..1]; the shape is emitted once, on
        # TypedElement, and must fire for a Class through rdfs inference
        """
        ex:overtyped a uml:Class ;
            uml:TypedElement__type ex:t1, ex:t2 .
        ex:t1 a uml:Class .
        ex:t2 a uml:Class .
        """,
        "uml#TypedElement__type",
    ),
    (
        "a binary allocate with one source and one target conforms",
        # the same nested shape as the case below, on a graph that satisfies it: without this,
        # a shape that rejected everything would still look like a passing test suite
        """
        ex:goodAlloc a sysml:Allocate ;
            sysml:Allocate__base_Abstraction ex:goodAbstraction .
        ex:goodAbstraction a uml:Abstraction ;
            uml:DirectedRelationship__source ex:gs ;
            uml:DirectedRelationship__target ex:gt .
        ex:gs a uml:Class .
        ex:gt a uml:Class .
        """,
        None,
    ),
    (
        "an OCL-derived shape fires through a nested path",
        # SysML's binary rule: self.base_Abstraction.source->size() = 1 and ... target ...
        """
        ex:alloc a sysml:Allocate ;
            sysml:Allocate__base_Abstraction ex:abstraction .
        ex:abstraction a uml:Abstraction ;
            uml:DirectedRelationship__source ex:s1, ex:s2 ;
            uml:DirectedRelationship__target ex:t1 .
        ex:s1 a uml:Class .
        ex:s2 a uml:Class .
        ex:t1 a uml:Class .
        """,
        "uml#DirectedRelationship__source",
    ),
    (
        "an untyped graph has nothing to violate",
        """
        ex:loose a uml:Comment ;
            rdfs:comment "no constrained property asserted" .
        """,
        None,
    ),
]


def load(path: Path, fmt: str = "turtle"):
    from rdflib import Graph

    graph = Graph()
    graph.parse(str(path), format=fmt)
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


def named(report_graph) -> list[str]:
    """Human-readable one-liner per violation, from the machine-readable report."""
    from rdflib import Namespace
    from rdflib.namespace import RDF

    sh = Namespace("http://www.w3.org/ns/shacl#")
    rows = []
    for result in report_graph.subjects(RDF.type, sh.ValidationResult):
        path = report_graph.value(result, sh.resultPath)
        component = report_graph.value(result, sh.sourceConstraintComponent)
        focus = report_graph.value(result, sh.focusNode)
        rows.append(f"path={path} component={str(component).split('#')[-1]} focus={focus}")
    return rows


def main() -> int:
    from rdflib import Namespace
    from rdflib.namespace import RDF

    sh = Namespace("http://www.w3.org/ns/shacl#")

    onto_graph = load(ONTOLOGY)
    shapes_graph = load(SHAPES)
    print(f"ontology {len(onto_graph)} triples | shapes {len(shapes_graph)} triples | "
          f"{len(CASES)} cases")

    failures = 0
    for label, data, expected_path in CASES:
        conforms, report_graph = validate(data, onto_graph, shapes_graph)
        rows = named(report_graph)
        if expected_path is None:
            ok = conforms
            detail = "" if ok else f"unexpected violations: {rows[:3]}"
        else:
            named_paths = " ".join(rows)
            ok = (not conforms) and expected_path in named_paths
            detail = "" if ok else (
                f"conforms={conforms} expected a violation on {expected_path}; got {rows[:3]}")
        print(f"[{'ok' if ok else 'FAIL'}] {label}")
        if not ok:
            failures += 1
            print(f"        {detail}")

    # a validator that never fires would pass every positive case above, so prove the shapes
    # can fail at all: with a single required property removed, the graph must break
    conforms, report_graph = validate(
        """
        ex:solo a uml:Association .
        """,
        onto_graph,
        shapes_graph,
    )
    ok = not conforms
    print(f"[{'ok' if ok else 'FAIL'}] the shapes can fail (bare Association is rejected)")
    if not ok:
        failures += 1

    print(f"\n{len(CASES) + 1 - failures}/{len(CASES) + 1} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
