#!/usr/bin/env python
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Jon R. Fox
"""Is ``sh:sparql`` a usable escape hatch for the bodies the subset refuses?

There is no OCL-to-SPARQL translation to be had: OCL is a typed expression language over an
object model and SPARQL is a graph-pattern query language, so every body has to be re-expressed
against the ontology's own IRIs rather than converted. The question this file answers is
narrower and cheap to answer: under the ruleset the other tests run (``inference="rdfs"``), does
pyshacl *execute* such a query, and does the query that gets written have any bite?

Each case is a real body taken verbatim from ``shapes/untranslated.json``, paired with a query,
a conforming instance, a violating instance, and a mutation of the query that must flip the
verdict. The mutation is the part that matters: a constraint that never fires passes a test
that only checks ``conforms``, and a vacuously true query is exactly what a mistyped property
path produces.

Run:  python tests/test_sparql_probe.py      (needs pyshacl + rdflib)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY = ROOT / "ontology" / "uml-family-relationships.ttl"
UNTRANSLATED = ROOT / "shapes" / "untranslated.json"

PREFIXES = """\
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix uml:  <https://mycr0ft.github.io/uml-ontology/uml#> .
@prefix ex:   <https://example.org/model#> .

"""

#: one query per refused body. ``mutate`` is (text that occurs once, replacement) and is chosen
#: so the rewritten query must stop firing on the conforming instance or start firing on it
CASES = {
    "same_lifeline": dict(
        owner="uml:ExecutionSpecification",
        body="start.covered = finish.covered",
        query="""PREFIX uml: <https://mycr0ft.github.io/uml-ontology/uml#>
            SELECT $this
            WHERE {
                $this uml:ExecutionSpecification__start ?s ;
                      uml:ExecutionSpecification__finish ?f .
                { ?s uml:InteractionFragment__covered ?l .
                  FILTER NOT EXISTS { ?f uml:InteractionFragment__covered ?l } }
                UNION
                { ?f uml:InteractionFragment__covered ?l .
                  FILTER NOT EXISTS { ?s uml:InteractionFragment__covered ?l } }
            }""",
        mutate=("{ ?f uml:InteractionFragment__covered ?l .\n                  FILTER NOT EXISTS",
                "{ ?f uml:InteractionFragment__covered ?l .\n                  FILTER EXISTS"),
        message="start and finish of an execution specification cover different lifelines",
        ok="""ex:e1 a uml:ExecutionSpecification ;
        uml:ExecutionSpecification__start ex:s1 ; uml:ExecutionSpecification__finish ex:f1 .
ex:s1 a uml:OccurrenceSpecification ; uml:InteractionFragment__covered ex:L .
ex:f1 a uml:OccurrenceSpecification ; uml:InteractionFragment__covered ex:L .""",
        bad="""ex:e2 a uml:ExecutionSpecification ;
        uml:ExecutionSpecification__start ex:s2 ; uml:ExecutionSpecification__finish ex:f2 .
ex:s2 a uml:OccurrenceSpecification ; uml:InteractionFragment__covered ex:L .
ex:f2 a uml:OccurrenceSpecification ; uml:InteractionFragment__covered ex:M .""",
    ),
    "non_leaf_redefinition": dict(
        owner="uml:RedefinableElement",
        body="redefinedElement->forAll(re | not re.isLeaf)",
        query="""PREFIX uml: <https://mycr0ft.github.io/uml-ontology/uml#>
            SELECT $this ?re
            WHERE {
                $this uml:RedefinableElement__redefinedElement ?re .
                ?re uml:RedefinableElement__isLeaf ?leaf .
                FILTER (?leaf = true)
            }""",
        mutate=("FILTER (?leaf = true)", "FILTER (?leaf = false)"),
        message="a leaf redefinable element cannot be redefined",
        ok="""ex:r1 a uml:RedefinableElement ;
        uml:RedefinableElement__redefinedElement ex:r2 .
ex:r2 a uml:RedefinableElement ; uml:RedefinableElement__isLeaf false .""",
        bad="""ex:r3 a uml:RedefinableElement ;
        uml:RedefinableElement__redefinedElement ex:r4 .
ex:r4 a uml:RedefinableElement ; uml:RedefinableElement__isLeaf true .""",
    ),
    "binary_associations": dict(
        owner="uml:UseCase",
        body="Association.allInstances()->forAll(a | a.memberEnd.type->includes(self) "
             "implies a.memberEnd->size() = 2)",
        # a count of the ends, so this one cannot be a property path: pyshacl forbids a nested
        # SELECT that does not project $this, which rules out the obvious subquery form
        query="""PREFIX uml: <https://mycr0ft.github.io/uml-ontology/uml#>
            SELECT $this ?association
            WHERE {
                ?association uml:Association__memberEnd ?end .
                ?end uml:TypedElement__type $this .
                ?association uml:Association__memberEnd ?e
            }
            GROUP BY $this ?association
            HAVING (COUNT(DISTINCT ?e) != 2)""",
        mutate=("HAVING (COUNT(DISTINCT ?e) != 2)", "HAVING (COUNT(DISTINCT ?e) < 0)"),
        message="a use case may only take part in binary associations",
        ok="""ex:uc1 a uml:UseCase .
ex:a1 a uml:Association ;
     uml:Association__memberEnd ex:e11 , ex:e12 .
ex:e11 uml:TypedElement__type ex:uc1 . ex:e12 uml:TypedElement__type ex:actor1 .""",
        bad="""ex:uc2 a uml:UseCase .
ex:a2 a uml:Association ;
     uml:Association__memberEnd ex:e21 , ex:e22 , ex:e23 .
ex:e21 uml:TypedElement__type ex:uc2 .
ex:e22 uml:TypedElement__type ex:actor2 . ex:e23 uml:TypedElement__type ex:actor3 .""",
    ),
}


def shape_ttl(name: str, case: dict, query: str) -> str:
    return f'''ex:{name} a sh:NodeShape ;
    sh:targetClass uml:{case["owner"].split(":")[-1]} ;
    sh:sparql [
        a sh:SPARQLConstraint ;
        sh:message "{case["message"]}" ;
        sh:select """{query}"""
    ] .
'''


def run(shapes_txt: str, data_txt: str):
    """Validate one data graph against one probe shape; return (conforms, shapes that fired)."""
    from pyshacl import validate
    from rdflib import Graph, URIRef

    shapes = Graph()
    shapes.parse(data=PREFIXES + shapes_txt, format="turtle")
    ontology = Graph()
    ontology.parse(str(ONTOLOGY), format="turtle")
    data = Graph()
    data.parse(data=PREFIXES + data_txt, format="turtle")
    for triple in ontology:
        data.add(triple)
    conforms, report, _ = validate(data, shacl_graph=shapes, inference="rdfs",
                                   abort_on_first=False, allow_infos=False)
    fired = set()
    for result in report.subjects(URIRef("http://www.w3.org/ns/shacl#resultSeverity"), None):
        source = report.value(result, URIRef("http://www.w3.org/ns/shacl#sourceShape"))
        fired.add(str(source).split("#")[-1])
    return conforms, sorted(fired)


def registered(case: dict) -> bool:
    """The body has to still be in the refusal register, or this probe has outlived its case."""
    rows = json.loads(UNTRANSLATED.read_text())["untranslated"]
    body = " ".join(case["body"].split())
    return any(" ".join(row["body"].split()) == body and row["owner"] == case["owner"]
               for row in rows)


def main() -> int:
    failures = 0

    for name, case in CASES.items():
        still_refused = registered(case)
        failures += not still_refused
        print(f"{'PASS' if still_refused else 'FAIL'}  {name:<24} body still refused by the subset")

        shapes_txt = shape_ttl(name, case, case["query"])
        ok_conforms, ok_fired = run(shapes_txt, case["ok"])
        bad_conforms, bad_fired = run(shapes_txt, case["bad"])
        good = ok_conforms and not ok_fired and not bad_conforms and bad_fired == [name]
        failures += not good
        print(f"{'PASS' if good else 'FAIL'}  {name:<24} conforming={ok_conforms} "
              f"violating={bad_conforms} fired={bad_fired}")

        old, new = case["mutate"]
        assert case["query"].count(old) == 1, f"{name}: mutation text does not occur once"
        mutated = shape_ttl(name, case, case["query"].replace(old, new))
        m_ok, m_ok_fired = run(mutated, case["ok"])
        m_bad, m_bad_fired = run(mutated, case["bad"])
        caught = not (m_ok and not m_ok_fired and not m_bad and m_bad_fired == [name])
        failures += not caught
        print(f"{'PASS' if caught else 'FAIL'}  {name:<24} mutated query changes a verdict "
              f"(conforming={m_ok}, violating={m_bad}, fired={m_bad_fired or m_ok_fired})")

    # cost: a query is evaluated once per focus node, so what matters at model scale is the
    # marginal rate, not the total - loading the ontology costs more than the queries do. Two
    # sizes, subtract, divide
    case = CASES["same_lifeline"]
    shapes_txt = shape_ttl("same_lifeline", case, case["query"])
    timings = {}
    for nodes in (100, 300):
        data_txt = "\n".join(
            f'ex:e{i} a uml:ExecutionSpecification ; '
            f'uml:ExecutionSpecification__start ex:s{i} ; '
            f'uml:ExecutionSpecification__finish ex:f{i} . '
            f'ex:s{i} a uml:OccurrenceSpecification ; uml:InteractionFragment__covered ex:L . '
            f'ex:f{i} a uml:OccurrenceSpecification ; uml:InteractionFragment__covered ex:L .'
            for i in range(nodes))
        started = time.time()
        conforms, fired = run(shapes_txt, data_txt)
        timings[nodes] = (time.time() - started, conforms, fired)
    per_node = 1000 * (timings[300][0] - timings[100][0]) / 200
    affordable = (all(t[1] and not t[2] for t in timings.values()) and per_node < 50)
    failures += not affordable
    print(f"{'PASS' if affordable else 'FAIL'}  {'cost':<24} "
          f"{1000 * timings[100][0]:.0f} ms at 100 nodes, {1000 * timings[300][0]:.0f} ms at "
          f"300 ({per_node:.1f} ms per focus node)")

    print(f"\n{len(CASES)} bodies, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
