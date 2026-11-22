#!/usr/bin/env python
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Jon R. Fox
"""Derive navigability and check the ontology states what the derivation needs.

UML 2.5.1 9.5.3 gives ``Property::isNavigable`` as a derived attribute: a navigable property
is one that is an association end *except* the ends the association owns.  The feeds do not
carry ``isNavigable`` because it is derived, and the repository does not invent it.  What the
ontology has to state is the relation the derivation runs on, so that a consumer can compute
the navigable ends from the model instead of reading a flag:

    navigable(A) = memberEnd(A) - ownedEnd(A)

Two fixtures pin the two halves.  ``ex:employer`` is a member end the association does not
own and is therefore navigable; ``ex:employee`` is a member end the association owns and is
therefore not navigable, even though both are member ends.  The stated subset chain is checked
too: ``navigableOwnedEnd`` must stay under ``ownedEnd`` under ``memberEnd``, because the
derivation reads ``memberEnd`` and ``ownedEnd`` and nothing else, and ``navigableOwnedEnd``
narrowing to owned ends is what keeps the two definitions from contradicting.

This is a derivation, not a SHACL rule: core shapes cannot condition on the *absence* of an
inverse link, so no NodeShape can say "not owned, therefore navigable" without a query, and
this repository does not compile queries into the generated shapes.

Run:  python tests/test_navigability.py      (needs rdflib)
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY = ROOT / "ontology" / "uml-family-relationships.ttl"

UML = "https://mycr0ft.github.io/uml-ontology/uml#"

PREFIXES = """\
@prefix uml:  <https://mycr0ft.github.io/uml-ontology/uml#> .
@prefix ex:   <https://example.org/model#> .
"""

#: two ends, one owned by the association and one not owned by anybody
FIXTURE = PREFIXES + """
ex:employment a uml:Association ;
    uml:Association__memberEnd ex:employee , ex:employer ;
    uml:Association__ownedEnd ex:employee .
ex:employee a uml:Property ;
    uml:Property__association ex:employment .
ex:employer a uml:Property ;
    uml:Property__association ex:employment .
"""

#: the same two ends, with the association owning neither of them
UNOWNED = PREFIXES + """
ex:employment a uml:Association ;
    uml:Association__memberEnd ex:employee , ex:employer .
ex:employee a uml:Property .
ex:employer a uml:Property .
"""

#: the same association with both ends owned, so nothing is navigable
ALL_OWNED = PREFIXES + """
ex:employment a uml:Association ;
    uml:Association__memberEnd ex:employee , ex:employer ;
    uml:Association__ownedEnd ex:employee , ex:employer .
ex:employee a uml:Property .
ex:employer a uml:Property .
"""


def graph(data: str):
    from rdflib import Graph

    g = Graph()
    g.parse(data=data, format="turtle")
    return g


def navigable(g, assoc):
    """navigable(A) = memberEnd(A) - ownedEnd(A), the clause's derivation spelled out."""
    from rdflib import URIRef

    members = set(g.objects(assoc, URIRef(UML + "Association__memberEnd")))
    owned = set(g.objects(assoc, URIRef(UML + "Association__ownedEnd")))
    return members - owned


def closure(g, prop) -> set:
    """Every property ``prop`` is a (transitive) subset of, itself included."""
    from rdflib import RDFS

    seen, todo = set(), [prop]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        todo.extend(g.objects(current, RDFS.subPropertyOf))
    return seen


def main() -> int:
    from rdflib import URIRef

    cases: list[tuple[str, bool, str]] = []

    onto = graph(ONTOLOGY.read_text(encoding="utf-8"))
    nav = URIRef(UML + "Association__navigableOwnedEnd")
    own = URIRef(UML + "Association__ownedEnd")
    mem = URIRef(UML + "Association__memberEnd")
    nav_chain = closure(onto, nav)
    cases.append((
        "navigableOwnedEnd is stated under ownedEnd under memberEnd",
        own in nav_chain and mem in nav_chain,
        f"closure = {sorted(str(p).split('#')[-1] for p in nav_chain)}",
    ))

    assoc = URIRef("https://example.org/model#employment")
    employee = URIRef("https://example.org/model#employee")
    employer = URIRef("https://example.org/model#employer")

    derived = navigable(graph(FIXTURE), assoc)
    cases.append((
        "a member end the association does not own is navigable",
        derived == {employer},
        f"navigable = {sorted(str(p).split('#')[-1] for p in derived)}",
    ))
    cases.append((
        "an owned member end is not navigable",
        employee not in derived,
        f"navigable = {sorted(str(p).split('#')[-1] for p in derived)}",
    ))

    empty = navigable(graph(ALL_OWNED), assoc)
    cases.append((
        "an association that owns every end navigates nothing",
        not empty,
        f"navigable = {sorted(str(p).split('#')[-1] for p in empty)}",
    ))

    # the derivation reads memberEnd and ownedEnd only: if the fixture dropped ownedEnd the
    # answer would change, which is what makes "owns" the discriminator rather than a default
    unowned = navigable(graph(UNOWNED), assoc)
    cases.append((
        "dropping ownedEnd changes the answer, so ownership is the discriminator",
        unowned == {employee, employer},
        f"navigable = {sorted(str(p).split('#')[-1] for p in unowned)}",
    ))

    failures = 0
    print(f"ontology {len(onto)} triples | {len(cases)} cases")
    for label, ok, detail in cases:
        print(f"[{'ok' if ok else 'FAIL'}] {label}")
        if not ok:
            failures += 1
            print(f"        {detail}")
    print(f"\n{len(cases) - failures}/{len(cases)} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
