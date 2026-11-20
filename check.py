# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Jon R. Fox
#!/usr/bin/env python
"""Gate for the uml-ontology artifacts.

Proves the generators still produce artifacts that (a) parse, (b) agree with each other, and
(c) say the specific things that were checked when they were written. Run from the repo root:

    python check.py            # all checks; needs rdflib for the RDF half
    python check.py --json     # machine-readable

Checks, in order:

1. both generators run and write their artifacts;
2. both Turtle files parse (skipped, loudly, when rdflib is absent);
3. every sh:path in the shapes resolves to a property in the ontology - the two artifacts
   are generated from different code paths, and a shape pointing at a property that does not
   exist silently validates nothing;
4. the ontology's own shape: relationship backbone, stereotype bases, inverse symmetry,
   namespace collision (uml:Element vs sysml2:Element);
5. the untranslated register accounts for every constraint: translated + untranslated equals
   the constraint total, and every refused constraint names a reason.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHECKS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((label, bool(ok), detail))


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args],
                          capture_output=True, text=True, cwd=ROOT)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    onto = run("build_ontology.py")
    check("build_ontology runs", onto.returncode == 0, onto.stderr.strip()[-300:])
    shacl = run("build_shacl.py")
    check("build_shacl runs", shacl.returncode == 0, shacl.stderr.strip()[-300:])

    ttl = ROOT / "ontology" / "uml-family-relationships.ttl"
    shapes = ROOT / "shapes" / "uml-family-shapes.ttl"
    register = ROOT / "shapes" / "untranslated.json"
    factbook = ROOT / "ontology" / "relationships.json"
    for path in (ttl, shapes, register, factbook):
        check(f"{path.relative_to(ROOT)} written", path.exists())

    if not all(p.exists() for p in (ttl, shapes, register, factbook)):
        return report(args.json)

    # generated files are published: an absolute home path in one of them is both a
    # reproducibility break (the bytes then depend on who built it) and a leak
    for path in (ttl, shapes, register, factbook):
        text = path.read_text(errors="replace")
        leaked = [needle for needle in ("/home/", "/Users/", "C:\\Users\\") if needle in text]
        check(f"{path.name} carries no local path", not leaked, ", ".join(leaked))

    facts = json.loads(factbook.read_text())
    reg = json.loads(register.read_text())
    counts = facts["counts"]
    check("classes > 800", counts["classes"] > 800, str(counts["classes"]))
    check("properties > 1500", counts["properties"] > 1500, str(counts["properties"]))
    check("inverse pairs > 500", counts["inversePairs"] > 500, str(counts["inversePairs"]))

    # the feature census: every declared feature is either described (an association end or
    # an attribute) or registered as unmapped. A feature that reaches none of the three is a
    # silent hole in the metamodel, which is exactly what this half of the gate is for
    described = counts["properties"] + counts["attributes"] + counts["unmapped"]
    check("every feature is described or registered",
          described == counts["features"],
          f"{described} != {counts['features']}")
    gaps = [row for row in facts["unmapped"] if row["reason"].startswith("no mapping")]
    check("no feature fell through the type mapping", not gaps,
          ", ".join(f"{g['owner']}.{g['name']}" for g in gaps[:3]))
    check("unmapped register is the known 27", counts["unmapped"] == 27,
          str(counts["unmapped"]))
    check("attributes > 300", counts["attributes"] > 300, str(counts["attributes"]))
    check("enumerations > 40, each with literals",
          counts["enumerations"] > 40 and all(facts["enumerations"].values()),
          str(counts["enumerations"]))
    check("enumeration literals > 200", counts["enumerationLiterals"] > 200,
          str(counts["enumerationLiterals"]))

    # 5. the register accounts for everything
    total = reg["counts"]["constraintsTotal"]
    check("register accounts for every constraint",
          reg["counts"]["translated"] + reg["counts"]["untranslated"] == total,
          f"{reg['counts']['translated']}+{reg['counts']['untranslated']} != {total}")
    check("every refused constraint names a reason",
          all(row.get("reason") for row in reg["untranslated"]),
          str(len(reg["untranslated"])))
    check("translation subset is honest about its size",
          reg["counts"]["translated"] < total,
          f"{reg['counts']['translated']}/{total} translated")
    check("shapes cover cardinality", reg["counts"]["shapes"] > 500,
          str(reg["counts"]["shapes"]))

    try:
        from rdflib import RDF, RDFS, OWL, Graph, URIRef
    except ImportError:
        print("SKIP: rdflib not installed - the RDF half of this gate did not run")
        return report(args.json)

    g_onto = Graph()
    g_shacl = Graph()
    try:
        g_onto.parse(str(ttl), format="turtle")
        check("ontology parses", True, f"{len(g_onto)} triples")
    except Exception as exc:                                        # noqa: BLE001
        check("ontology parses", False, str(exc)[:200])
    try:
        g_shacl.parse(str(shapes), format="turtle")
        check("shapes parse", True, f"{len(g_shacl)} triples")
    except Exception as exc:                                        # noqa: BLE001
        check("shapes parse", False, str(exc)[:200])
    if len(g_onto) == 0 or len(g_shacl) == 0:
        return report(args.json)

    # 3. cross-artifact agreement: every sh:path must be a property the ontology defines
    SH = "http://www.w3.org/ns/shacl#"
    ontology_props = set(g_onto.subjects(RDF.type, OWL.ObjectProperty))
    ontology_props |= set(g_onto.subjects(RDF.type, OWL.DatatypeProperty))
    shape_paths = set(g_shacl.objects(None, URIRef(SH + "path")))
    dangling = shape_paths - ontology_props
    check(f"every sh:path is an ontology property ({len(shape_paths)} paths)",
          not dangling, ", ".join(sorted(str(d) for d in list(dangling)[:3])))

    # every shape targets a class the ontology defines
    ontology_classes = set(g_onto.subjects(RDF.type, OWL.Class))
    targets = set(g_shacl.objects(None, URIRef(SH + "targetClass")))
    check(f"every shape targets an ontology class ({len(targets)} targets)",
          targets <= ontology_classes,
          ", ".join(sorted(str(t) for t in list(targets - ontology_classes)[:3])))

    # 4. the ontology's own shape
    base_iri = facts["baseIri"].rstrip("/")

    def cls(qualified: str) -> URIRef:
        prefix, name = qualified.split(":", 1)
        return URIRef(f"{base_iri}/{prefix}#{name}")

    def ancestors(node, seen=None):
        seen = set() if seen is None else seen
        for parent in g_onto.objects(node, RDFS.subClassOf):
            if parent not in seen:
                seen.add(parent)
                ancestors(parent, seen)
        return seen

    for child, parent in (("uml:Dependency", "uml:DirectedRelationship"),
                          ("uml:Abstraction", "uml:Dependency"),
                          ("sysml:Allocate", "uml:Abstraction"),
                          ("sysml:Satisfy", "uml:Dependency"),
                          ("uaf:Implements", "uml:Abstraction")):
        # reachability, not directness: profile stereotypes chain through other stereotypes
        check(f"{child} reaches {parent}", cls(parent) in ancestors(cls(child)))

    inverses = list(g_onto.triples((None, OWL.inverseOf, None)))
    symmetric = sum(1 for a, _, b in inverses if (b, OWL.inverseOf, a) in g_onto)
    check(f"inverses symmetric ({symmetric}/{len(inverses)})",
          bool(inverses) and symmetric == len(inverses))

    # multiplicity has two halves, and both are checked: the bounds every feature states as
    # annotations, and the lower bounds restated as OWL restrictions so a consumer that knows
    # nothing about umlmeta can still see "at least one client"
    META = URIRef(base_iri.replace("/ontology", "") + "/ns#")
    lo_annot = list(g_onto.triples((None, URIRef(str(META) + "lower"), None)))
    check(f"every feature states its bounds ({len(lo_annot)})",
          len(lo_annot) == counts["properties"] + counts["attributes"])
    up_annot = list(g_onto.triples((None, URIRef(str(META) + "upper"), None)))
    check(f"every feature states an upper bound ({len(up_annot)})",
          len(up_annot) == len(lo_annot))
    mincard = list(g_onto.triples((None, OWL.minCardinality, None)))
    check(f"stated lower bounds are restrictions ({len(mincard)})",
          len(mincard) == counts["requiredProperties"] and len(mincard) > 0)
    required = {str(o) for _, _, o in g_onto.triples((None, OWL.minCardinality, None))}
    check("restrictions agree with the fact book",
          len(required) >= 1 and all(int(v) >= 1 for v in required), ", ".join(sorted(required)))

    datatypes = set(g_onto.subjects(RDF.type, OWL.DatatypeProperty))
    xsd_range = {s for s, o in g_onto.subject_objects(RDFS.range)
                 if str(o).startswith("http://www.w3.org/2001/XMLSchema#")}
    check(f"every datatype property has an XSD range ({len(datatypes)})",
          datatypes and datatypes <= xsd_range,
          ", ".join(sorted(str(d) for d in list(datatypes - xsd_range)[:3])))

    enum_classes = {cls(key) for key in facts["enumerations"]}
    check(f"enumerations subclass uml:Enumeration ({len(enum_classes)})",
          all(cls("uml:Enumeration") in ancestors(key) for key in enum_classes))
    individuals = sum(len(list(g_onto.subjects(RDF.type, key))) for key in enum_classes)
    check(f"every literal is an individual ({individuals}/{counts['enumerationLiterals']})",
          individuals == counts["enumerationLiterals"])

    # a subset or redefining feature names a feature declared on the owner or a base; emitting
    # ``Owner__name`` blindly minted 448 IRIs that nothing defines
    META_NS = str(URIRef(str(META)))
    defined = set(g_onto.subjects(RDF.type, OWL.ObjectProperty))
    defined |= set(g_onto.subjects(RDF.type, OWL.DatatypeProperty))
    dangling = []
    for pred in ("subPropertyOf", "redefines"):
        iri = URIRef(META_NS + pred) if pred == "redefines" else RDFS.subPropertyOf
        for s, o in g_onto.subject_objects(iri):
            if o not in defined:
                dangling.append(f"{pred}:{o}")
    check(f"subset and redefine targets are defined properties ({len(dangling)} dangling)",
          not dangling, ", ".join(sorted(dangling)[:3]))
    subsets = len(list(g_onto.triples((None, RDFS.subPropertyOf, None))))
    check(f"subsets are emitted ({subsets})", subsets > 450, str(subsets))
    unresolved = len(list(g_onto.triples((None, URIRef(META_NS + "unresolvedSubset"), None))))
    check(f"named-but-undeclared subset targets are recorded ({unresolved})",
          unresolved == 88, str(unresolved))
    redefines = len(list(g_onto.triples((None, URIRef(META_NS + "redefines"), None))))
    check(f"redefinitions are emitted ({redefines})", redefines > 100, str(redefines))

    # authored multiplicity: the hand-written shapes are the only artifact in the repo that is
    # not generated, so nothing else would notice when a property they name is renamed. Every
    # uml: IRI they target or require - including the ones inside the SPARQL text, which no
    # parser sees - must be something the ontology defines
    authored = ROOT / "shapes" / "authored-multiplicity.ttl"
    g_auth = Graph()
    try:
        g_auth.parse(str(authored), format="turtle")
        check(f"authored shapes parse ({len(g_auth)} triples)", True)
    except Exception as exc:                                        # noqa: BLE001
        check("authored shapes parse", False, str(exc)[:200])
    node_shapes = set(g_auth.subjects(RDF.type, URIRef(SH + "NodeShape")))
    check(f"authored shapes are the known four ({len(node_shapes)})", len(node_shapes) == 4,
          ", ".join(sorted(str(s).split("#")[-1] for s in node_shapes)))
    referenced = set()
    for predicate in ("path", "targetClass", "targetSubjectsOf", "targetObjectsOf", "class"):
        for node in g_auth.objects(None, URIRef(SH + predicate)):
            if isinstance(node, URIRef):
                referenced.add(node)
    for query in g_auth.objects(None, URIRef(SH + "select")):
        referenced |= {URIRef(base_iri + "/uml#" + name)
                       for name in set(re.findall(r"uml:([A-Za-z0-9_]+)", str(query)))}
    uml_ns = base_iri + "/uml#"
    defined_any = set(g_onto.subjects(RDF.type, None))
    missing = {r for r in referenced if str(r).startswith(uml_ns)} - defined_any
    check(f"authored shapes name only defined uml terms ({len(referenced)} refs)",
          not missing, ", ".join(sorted(str(m) for m in missing)[:3]))

    # bounds consistency over the fact book: every feature states a lower bound that is an
    # integer, an upper bound that is an integer or the unbounded marker, and 3..1 is not a
    # multiplicity. The SHACL side checks the same thing for bounds a model authors; this
    # side checks the 1,996 the metamodel states about itself, which no shape ever sees
    features = facts["properties"] + facts["attributes"]
    bad_lo = [f"{r['owner']}.{r['name']}" for r in features if not isinstance(r["lo"], int)]
    bad_hi = [f"{r['owner']}.{r['name']}" for r in features
              if not (r["hi"] == "*" or isinstance(r["hi"], int))]
    inverted = [f"{r['owner']}.{r['name']} {r['lo']}..{r['hi']}" for r in features
                if isinstance(r["hi"], int) and isinstance(r["lo"], int) and r["lo"] > r["hi"]]
    unbounded = sum(1 for r in features if r["hi"] == "*")
    check(f"every lower bound is an integer ({len(bad_lo)} bad)", not bad_lo,
          ", ".join(bad_lo[:3]))
    check(f"every upper bound is an integer or * ({len(bad_hi)} bad, {unbounded} unbounded)",
          not bad_hi, ", ".join(bad_hi[:3]))
    check(f"no feature states a lower bound above its upper bound ({len(inverted)} bad)",
          not inverted, ", ".join(inverted[:3]))

    check("uml:Element and sysml2:Element are distinct classes",
          cls("uml:Element") != cls("sysml2:Element")
          and (cls("uml:Element"), RDF.type, OWL.Class) in g_onto
          and (cls("sysml2:Element"), RDF.type, OWL.Class) in g_onto)

    return report(args.json)


def report(as_json: bool) -> int:
    failed = [c for c in CHECKS if not c[1]]
    if as_json:
        print(json.dumps({"checks": [{"label": l, "ok": o, "detail": d}
                                     for l, o, d in CHECKS]}, indent=2))
    else:
        for label, ok, detail in CHECKS:
            print(f"[{'ok' if ok else 'FAIL'}] {label}"
                  + (f"  -- {detail}" if detail and not ok else ""))
        print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
