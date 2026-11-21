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

import json
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


def evaluate(expr, state):
    """Evaluate a compiled formula tree over an assignment of feature name -> absent/true/false."""
    kind = expr[0]
    if kind == "not":
        return not evaluate(expr[1], state)
    if kind == "implies":
        return (not evaluate(expr[1], state)) or evaluate(expr[2], state)
    if kind in ("and", "or"):
        values = [evaluate(branch, state) for branch in expr[1]]
        return all(values) if kind == "and" else any(values)
    if kind == "test":
        return state[expr[1]] == "true"
    name, op, value = expr[1], expr[2], expr[3]
    held = state[name]
    if value == "null":
        return (held == "absent") if op == "=" else (held != "absent")
    return (held == value) if op == "=" else (held != value)


def instances(entry):
    """A falsifying and a satisfying instance for one compiled formula, or (None, None)."""
    import itertools

    names = sorted(entry["paths"])
    found = {"bad": None, "good": None}
    for combo in itertools.product(("absent", "true", "false"), repeat=len(names)):
        state = dict(zip(names, combo))
        holds = evaluate(entry["expr"], state)
        key = "good" if holds else "bad"
        if found[key] is None:
            found[key] = state
        if found["bad"] is not None and found["good"] is not None:
            break
    return found["bad"], found["good"]


def iri(term: str, prefixes: dict) -> str:
    """A prefixed name from the shapes file as a full IRI, so no prefix has to be guessed."""
    prefix, _, local = term.partition(":")
    return prefixes[prefix] + local


def as_turtle(owner: str, paths: dict, state: dict, prefixes: dict) -> str:
    """One focus node of the owner class, with each feature absent, true or false."""
    triples = [f"<http://example.org/i> a <{iri(owner, prefixes)}>"]
    for name, held in state.items():
        if held != "absent":
            triples.append(f"<http://example.org/i> <{iri(paths[name], prefixes)}> {held}")
    return " .\n".join(triples) + " .\n"


def logic_cases(shapes_graph, registry):
    """Per compiled shape: the instance it must reject and the instance it must accept."""
    from pyshacl import validate as pyshacl_validate

    from rdflib import Graph, Namespace, URIRef
    from rdflib.namespace import RDF

    sh = Namespace("http://www.w3.org/ns/shacl#")

    prefixes = {prefix: str(uri) for prefix, uri in shapes_graph.namespaces() if prefix}
    failures = 0
    for entry in registry["entries"]:
        shape = URIRef(entry["shape"])
        bad, good = instances(entry)
        results = {}
        for label, state in (("bad", bad), ("good", good)):
            if state is None:
                results[label] = "no instance exists"
                continue
            data = Graph()
            data.parse(data=as_turtle(entry["owner"], entry["paths"], state, prefixes),
                       format="turtle")
            # only this shape, so a violation cannot be another shape's and runtime stays small
            local = Graph()
            for triple in shapes_graph.cbd(shape):
                local.add(triple)
            conforms, report, _text = pyshacl_validate(
                data, shacl_graph=local, inference="rdfs", abort_on_first=False)
            hit = any(True for _ in report.subjects(RDF.type, sh.ValidationResult))
            results[label] = (conforms, hit)
        ok = results["bad"] == (False, True) and results["good"] == (True, False)
        if not ok:
            failures += 1
            print(f"[FAIL] logic shape {entry['owner']} {entry['name']}: {results}")
    print(f"[{'ok' if not failures else 'FAIL'}] every compiled formula has a rejecting and an "
          f"accepting instance ({len(registry['entries'])} shapes)")
    return failures


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

    registry_path = ROOT / "shapes" / "logic.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    logic_failures = logic_cases(shapes_graph, registry)
    hand = len(CASES) + 1
    print(f"\n{hand - failures}/{hand} hand-written cases passed")
    return 1 if (failures or logic_failures) else 0


if __name__ == "__main__":
    raise SystemExit(main())
