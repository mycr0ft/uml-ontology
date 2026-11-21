# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Jon R. Fox
"""Export an OWL 2 ontology of UML-family relationships from the generated runtimes.

The ontology is generated, not written: every axiom comes from the metamodel metadata the
generators already preserved — the class hierarchy, each property's type (domain/range),
multiplicity, composite flag, subsets/redefines, the recorded opposite, the normative OCL
constraints, and for profiles the stereotype's base metaclass.

Three grades of statement are kept apart on purpose:

* ``stated``   — the metamodel says it (a typed end, a subclass axiom, a constraint body);
* ``implied``  — the profile's semantics constrain more than the typing does (``Satisfy``
  between a Requirement and a Block is SysML's rule, not UML's);
* ``observed`` — the instance corpus shows the pair occurring (evidence, never a rule).

A consumer that cannot tell those apart will treat "some model did this" as "the language
allows this", which is the failure mode this separation exists to prevent.

Usage:
    <venv>/bin/python scripts/build_ontology.py [--out DIR] [--base IRI]

Writes ``uml-family-relationships.ttl`` (OWL 2 DL, Turtle) and ``relationships.json``
(the same facts in a form tooling can query without an RDF stack).
"""
from __future__ import annotations

import argparse
import json
import keyword
import re
import sys
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def find_umlmeta() -> tuple[str, Path | None]:
    """Locate umlmeta: $UMLMETA_SRC, then an installed package, then a sibling checkout."""
    import importlib.util
    import os

    env = os.environ.get("UMLMETA_SRC")
    if env:
        src = Path(env).expanduser().resolve()
        if not (src / "umlmeta" / "uml25.py").exists():
            raise SystemExit(f"UMLMETA_SRC={src} does not contain umlmeta/uml25.py")
        sys.path.insert(0, str(src))
        return f"UMLMETA_SRC={src}", src
    if importlib.util.find_spec("umlmeta") is not None:
        return "installed umlmeta package", None
    sibling = (ROOT.parent / "umlmeta" / "src").resolve()
    if (sibling / "umlmeta" / "uml25.py").exists():
        sys.path.insert(0, str(sibling))
        return f"sibling checkout {sibling}", sibling
    raise SystemExit(
        "umlmeta not found: set UMLMETA_SRC=/path/to/umlmeta/src, "
        "pip install umlmeta, or place this repo beside an umlmeta checkout")


UMLMETA_SOURCE, UMLMETA_SRC_PATH = find_umlmeta()

GENERATOR = "uml-ontology scripts/build_ontology.py"


def _umlmeta_version() -> str:
    """The package version, the same however umlmeta was obtained.

    Installed distributions carry metadata; a bare source tree (``UMLMETA_SRC``,
    a sibling checkout) often does not, so read ``__version__`` from the module
    instead. Leaving this as "unknown" would write an environment-dependent
    value into a committed artifact and fail the currency gate.
    """
    try:
        from importlib.metadata import version

        return version("umlmeta")
    except Exception:                                            # noqa: BLE001
        pass
    try:
        import importlib

        found = getattr(importlib.import_module("umlmeta"), "__version__", None)
        if isinstance(found, str) and found:
            return found
    except Exception:                                            # noqa: BLE001
        pass
    return "unknown"


UMLMETA_VERSION = _umlmeta_version()

DEFAULT_BASE = "https://mycr0ft.github.io/uml-ontology"
DEFAULT_OUT = ROOT / "ontology"

#: Namespace prefix -> (module name, IRI fragment). Ordering matters only for prefix
#: declaration in the emitted Turtle.
MODULES: tuple[tuple[str, str, str], ...] = (
    ("uml", "uml25", "UML 2.5.1 metaclasses"),
    ("sp", "standard_profile", "UML Standard Profile stereotypes"),
    ("sysml", "sysml", "SysML v1 profile stereotypes"),
    ("uaf", "uaf", "UAF profile stereotypes"),
    ("bpmn", "bpmn", "BPMN 2.0 stereotypes"),
    ("sysml2", "sysml2", "SysML v2 abstract syntax"),
)

OWL = "http://www.w3.org/2002/07/owl#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def is_metaclass(obj: Any) -> bool:
    """True for a generated runtime class (metaclass or stereotype), not an enum/helper."""
    if not isinstance(obj, type):
        return False
    if obj.__module__.rsplit(".", 1)[-1] not in {m for _, m, _ in MODULES}:
        return False
    if getattr(obj, "_STEREO", None) is not None:
        return True
    return hasattr(obj, "_DECL") or any(hasattr(b, "_DECL") for b in obj.__mro__[1:])


def runtime_modules() -> dict[str, Any]:
    import importlib

    out = {}
    for prefix, module, _label in MODULES:
        out[prefix] = importlib.import_module(f"umlmeta.{module}")
    return out


def collect_classes(module: Any, module_name: str) -> dict[str, type]:
    return {
        name: obj
        for name, obj in vars(module).items()
        if name[:1].isupper() and is_metaclass(obj)
        and obj.__module__.rsplit(".", 1)[-1] == module_name
    }


def own_features(cls: type) -> dict[str, Any]:
    """Features declared on *cls* itself (not inherited), from its own ``_DECL``."""
    return dict(vars(cls).get("_DECL", {}) or {})


#: Declared primitive type -> (XSD datatype, UML type name).  ``UnlimitedNatural`` is the
#: one that does not fit cleanly: its value space is the non-negative integers *plus* ``*``,
#: so the datatype is an approximation and the exact bound still reaches the fact book as
#: ``hi: "*"``.  The UML name is kept as an annotation either way, so a consumer can tell
#: "Integer" from "UnlimitedNatural" without consulting the generator.
PRIMITIVES: dict[str, tuple[str, str]] = {
    "bool": ("xsd:boolean", "Boolean"),
    "int": ("xsd:integer", "Integer"),
    "float": ("xsd:double", "Real"),
    "str": ("xsd:string", "String"),
    "UnlimitedNatural": ("xsd:nonNegativeInteger", "UnlimitedNatural"),
}

#: Declared types that name no node in the metamodel and carry no value either, with the
#: reason they are not emitted.  A type not listed here is a mapping gap, not a decision,
#: and ``check.py`` fails on one: silence is how features disappear.
UNMAPPED_REASONS: dict[str, str] = {
    "xml.dom.Element": "the feed types this as a DOM node: no model element to range over",
    "BPMNDI.BPMNDiagram": "the diagram-interchange package: layout, not model",
    "": "the feed declares no type for this feature",
    "None": "the feed declares no type for this feature",
}

#: Enumeration members whose Python name had to dodge a keyword or constant keep the
#: metamodel's spelling, which is what a reader of the ontology expects to see.
RESERVED = set(keyword.kwlist) | {"None", "True", "False"}


def literal_name(member: str) -> str:
    """``break_`` -> ``break``, ``in_`` -> ``in``, ``None_`` -> ``None``."""
    return member[:-1] if member.endswith("_") and member[:-1] in RESERVED else member


def enumeration_types(module: Any, module_name: str) -> dict[str, type]:
    """Enumerations the module declares: UML ``Enumeration`` classes, not metaclasses."""
    import enum as _enum

    return {
        name: obj
        for name, obj in vars(module).items()
        if isinstance(obj, type) and issubclass(obj, _enum.Enum)
        and obj.__module__.rsplit(".", 1)[-1] == module_name
    }


def metaclass_bases(cls: type, known: set[str]) -> list[str]:
    return [b.__name__ for b in cls.__mro__[1:] if b.__name__ in known]


def describe(cls: type) -> dict[str, Any]:
    doc = (cls.__doc__ or "").strip().splitlines()
    text = " ".join(line.strip() for line in doc if line.strip())
    return {
        "name": cls.__name__,
        "stereotype": getattr(cls, "_STEREO", None),
        "package": getattr(cls, "_PKG", None),
        "abstract": bool(getattr(cls, "_ABSTRACT", False)),
        "bases": [],
        "definition": text[:1500],
        "constraints": [
            {"name": name, "body": body}
            for name, body in (getattr(cls, "CONSTRAINTS", ()) or ())
        ],
    }


def feature_rows(cls: type, known: set[str]) -> Iterable[dict[str, Any]]:
    """Object properties for one class: every feature whose type is a metaclass."""
    for name, ref in own_features(cls).items():
        target = getattr(ref, "t", None)
        target_name = target.__name__ if isinstance(target, type) else str(target)
        if target_name not in known:
            continue                       # primitive, enum or library type: not a node
        yield {
            "owner": cls.__name__,
            "name": name,
            "range": target_name,
            "multi": bool(getattr(ref, "multi", False)),
            "lo": getattr(ref, "lo", 0),
            "hi": _count(getattr(ref, "hi", 1)),
            "composite": bool(getattr(ref, "composite", False)),
            "derived": bool(getattr(ref, "derived", False)),
            "union": bool(getattr(ref, "union", False)),
            "readonly": bool(getattr(ref, "readonly", False)),
            "subsets": list(getattr(ref, "subsets", ()) or ()),
            "redefines": list(getattr(ref, "redefines", ()) or ()),
            "opposite": getattr(ref, "opp", None),
            "assoc": getattr(ref, "assoc", None),
        }


def build() -> dict[str, Any]:
    """Collect classes and properties, keyed by QUALIFIED name (``prefix:Name``).

    Bare names collide: ``Element``, ``Relationship`` and ``Dependency`` exist in both the
    UML and the SysML v2 namespaces, and keying by name silently let one module's class
    overwrite the other's — which emitted the wrong subclass axioms and dropped the
    ``uml:`` IRIs entirely. Identity maps keep the resolution exact.
    """
    modules = runtime_modules()
    class_of: dict[str, type] = {}          # qualified key -> class
    key_of: dict[type, str] = {}            # class -> qualified key
    for prefix, module_name, _label in MODULES:
        for name, cls in collect_classes(modules[prefix], module_name).items():
            key = f"{prefix}:{name}"
            class_of[key] = cls
            key_of[cls] = key

    classes: dict[str, dict[str, Any]] = {}
    properties: list[dict[str, Any]] = []
    attributes: list[dict[str, Any]] = []
    enumerations: dict[str, dict[str, Any]] = {}
    unmapped: list[dict[str, Any]] = []
    prefix_of: dict[str, str] = {}

    languages = {"uml": "UML 2.5.1", "sp": "UML Standard Profile", "sysml": "SysML v1",
                 "uaf": "UAF", "bpmn": "BPMN 2.0", "sysml2": "SysML v2"}

    for key, cls in class_of.items():
        prefix = key.split(":", 1)[0]
        row = describe(cls)
        row["key"] = key
        row["prefix"] = prefix
        row["language"] = languages[prefix]
        # DIRECT bases only: the full MRO is what a reasoner computes, and emitting every
        # ancestor makes each class carry ten redundant subclass axioms
        row["bases"] = [key_of[b] for b in cls.__bases__ if b in key_of]
        row["base_metaclasses"] = [
            key_of[b] for b in (getattr(cls, "_BASE_METACLASSES", ()) or ())
            if b in class_of and class_of[b].__module__.endswith("uml25")
        ]
        classes[key] = row
        prefix_of[key] = prefix

    # enumerations are the second half of the type space: a feature typed ``VisibilityKind``
    # ranges over literals, not over a metaclass.  Collected before the feature walk so a
    # name declared in another module still resolves.
    for prefix, module_name, _label in MODULES:
        for name, member in enumeration_types(modules[prefix], module_name).items():
            key = f"{prefix}:{name}"
            enumerations[key] = {
                "key": key,
                "name": name,
                "prefix": prefix,
                "language": languages[prefix],
                "literals": [{"name": literal_name(m.name), "member": m.name}
                             for m in member],
            }

    def resolve_enum(owner_key: str, declared: str) -> str | None:
        """The enumeration a declared type names, in the owner's module first, then UML."""
        if not declared:
            return None
        prefix = owner_key.split(":", 1)[0]
        for candidate in (f"{prefix}:{declared}", f"uml:{declared}"):
            if candidate in enumerations:
                return candidate
        return None

    def resolve_target(owner_key: str, target: Any) -> str | None:
        """Resolve a feature's declared type to a qualified class key.

        ``_DECL`` refs carry the type either as a class object (profile base refs) or as a
        bare name string (most metaclass features: ``_Ref('client', "NamedElement", ...)``).
        Strings resolve in the owner's own module first, then in UML, so ``sysml``'s
        ``Allocate`` pointing at ``Abstraction`` lands on ``uml:Abstraction`` and a SysML v2
        ``Element`` stays ``sysml2:Element``.
        """
        if isinstance(target, type):
            return key_of.get(target)
        if not isinstance(target, str) or not target:
            return None
        owner_prefix = owner_key.split(":", 1)[0]
        for candidate in (f"{owner_prefix}:{target}", f"uml:{target}"):
            if candidate in class_of:
                return candidate
        for key in class_of:
            if key.split(":", 1)[1] == target:
                return key
        return None

    for key, cls in class_of.items():
        for name, ref in own_features(cls).items():
            target = getattr(ref, "t", None)
            target_key = resolve_target(key, target)
            row = {
                "owner": key,
                "name": name,
                "range": None,
                "multi": bool(getattr(ref, "multi", False)),
                "lo": getattr(ref, "lo", 0),
                "hi": _count(getattr(ref, "hi", 1)),
                "composite": bool(getattr(ref, "composite", False)),
                "derived": bool(getattr(ref, "derived", False)),
                "union": bool(getattr(ref, "union", False)),
                "readonly": bool(getattr(ref, "readonly", False)),
                "subsets": list(getattr(ref, "subsets", ()) or ()),
                "redefines": list(getattr(ref, "redefines", ()) or ()),
                "opposite": getattr(ref, "opp", None),
                "assoc": getattr(ref, "assoc", None),
            }
            if target_key is not None:
                row["range"] = target_key
                properties.append(row)
                continue
            # not a node: either a value (datatype), a literal-set (enumeration), or a
            # declared type this build cannot map - the last is recorded, never dropped
            declared = target.__name__ if isinstance(target, type) else str(target or "")
            enum_key = resolve_enum(key, declared)
            primitive = PRIMITIVES.get(declared)
            if enum_key is not None:
                attributes.append(dict(row, kind="enumeration", range=enum_key,
                                       declaredType=enum_key.split(":", 1)[1]))
            elif primitive is not None:
                attributes.append(dict(row, kind="datatype", range=None,
                                       xsd=primitive[0], declaredType=primitive[1]))
            else:
                unmapped.append({
                    "owner": key, "name": name,
                    "declaredType": declared or None,
                    "reason": UNMAPPED_REASONS.get(
                        declared, f"no mapping for declared type {declared!r}"),
                })

    by_owner = {(p["owner"], p["name"]): p for p in properties}
    inverses = 0
    for prop in properties:
        opp = prop["opposite"]
        if not opp:
            continue
        candidate = by_owner.get((prop["range"], opp))
        if candidate is not None and candidate.get("opposite") == prop["name"]:
            inverses += 1

    # relationship classes = transitive subclasses of uml:Relationship, walked over the
    # emitted direct bases (the count is a fact about the ontology, so it must not depend on
    # which axioms happened to be direct)
    def ancestors_of(key: str, seen: set[str] | None = None) -> set[str]:
        seen = set() if seen is None else seen
        for parent in classes.get(key, {}).get("bases", []):
            if parent not in seen:
                seen.add(parent)
                ancestors_of(parent, seen)
        return seen

    relationships = sorted(
        key for key in classes if "uml:Relationship" in ancestors_of(key))
    stereotype_kinds = sorted(key for key, row in classes.items() if row["stereotype"])
    described = properties + attributes
    return {
        "classes": classes,
        "properties": properties,
        "attributes": attributes,
        "enumerations": enumerations,
        "unmapped": unmapped,
        "features": len(properties) + len(attributes) + len(unmapped),
        "required": sum(1 for row in described if int(row["lo"]) > 0),
        "inverses": inverses,
        "prefix_of": prefix_of,
        "relationships": relationships,
        "stereotype_kinds": stereotype_kinds,
    }


# ----------------------------------------------------------------- emitters
_TAG = re.compile(r"<[^>]+>")


def _esc(text: str) -> str:
    """Plain-text Turtle literal body: tags stripped, whitespace collapsed, quotes escaped."""
    text = _TAG.sub(" ", text)
    text = " ".join(text.split())
    return (text.replace("\\", "\\\\").replace('"', '\\"').replace("\t", " ").strip())


def _count(value: Any) -> int | str:
    """A bound as the fact book states it: an integer, or ``"*"`` for unbounded.

    ``umlmeta`` stores most upper bounds as integers but four as digit strings
    (``bpmn:ChoreographyTask.messageFlowRef`` is ``1..'2'``), and the fact book is what other
    tools read, so the wart is normalised here rather than documented.
    """
    if str(value) == "*":
        return "*"
    return int(value)


def _bounds(row: dict[str, Any]) -> list[str]:
    """The stated multiplicity as annotations: ``lower`` a count, ``upper`` a count or ``*``."""
    upper = row["hi"]
    literal = '"*"' if str(upper) == "*" else str(int(upper))
    return [f"umlmeta:lower {int(row['lo'])}", f"umlmeta:upper {literal}"]


def _declare_in(classes: dict[str, Any], own: set[tuple[str, str]],
                owner: str, name: str) -> str | None:
    """Where a inherited feature name is actually declared: the owner, else a base.

    ``subsets``/``redefines`` name a feature, not a class: ``Dependency.client`` subsets
    ``source``, which is declared on ``DirectedRelationship``.  Minting ``Dependency__source``
    from the owner produces an IRI that does not exist, which is how 448 of the 574 subset
    triples used to dangle.  Walk the bases until the name is found.
    """
    seen: set[str] = set()
    frontier = [owner]
    while frontier:
        key = frontier.pop(0)
        if key in seen:
            continue
        seen.add(key)
        if (key, name) in own:
            return f"{key}__{name}"
        frontier.extend(classes.get(key, {}).get("bases", []))
    return None


def _block(subject: str, fragments: list[str]) -> str:
    """One subject block: `s p1 o1 ; p2 o2 .`, wrapped for readability."""
    body = " ;\n    ".join(fragments)
    return f"{subject} {body} .\n"


def _stereotype_parts(path: str) -> tuple[str, str, str]:
    """``UAF::Taxonomy::Achiever`` as (profile, package, local name).

    Every one of the 344 rows ends with the class's own name, so the tail restates the subject
    and only the profile and the package carry information.
    """
    parts = path.split("::")
    if len(parts) != 3:
        return parts[0], "", parts[-1]
    return parts[0], parts[1], parts[2]


# Derived unions the feeds do not carry.  UML 2.5.1 states both ends of the two central
# relations, but umlmeta preserves only ``ownedElement`` and ``ownedMember``, which is why 53
# subset records name a feature no class declares.  These are supplements, not feed facts: each
# one cites the clause it comes from and is flagged derived and union, as the clause says.
SPEC_SUPPLEMENT: tuple[dict[str, Any], ...] = (
    {
        "iri": "uml:Element__owner",
        "owner": "uml:Element",
        "name": "owner",
        "range": "uml:Element",
        "lo": 0,
        "hi": 1,
        "subsets": (),
        "opposite": "uml:Element__ownedElement",
        "clause": ("UML 2.5.1 7.8.6.4: /owner : Element [0..1]{union} "
                   "(opposite Element::ownedElement). The Element that owns this Element."),
    },
    {
        "iri": "uml:NamedElement__namespace",
        "owner": "uml:NamedElement",
        "name": "namespace",
        "range": "uml:Namespace",
        "lo": 0,
        "hi": 1,
        # the clause also says it subsets memberNamespace, which the feeds omit as well
        "subsets": (),
        "opposite": "uml:Namespace__ownedMember",
        "clause": ("UML 2.5.1 7.8.9.6: /namespace : Namespace [0..1]{union, subsets "
                   "memberNamespace, subsets Element::owner} (opposite Namespace::ownedMember). "
                   "Specifies the Namespace that owns the NamedElement."),
    },
)


def emit_turtle(model: dict[str, Any], base: str) -> str:
    prefixes = sorted({key.split(":", 1)[0] for key in model["classes"]})
    lines: list[str] = [
        "@prefix owl:  <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix umlmeta: <https://mycr0ft.github.io/uml-ontology/ns#> .",
    ]
    for prefix in prefixes:
        lines.append(f"@prefix {prefix}: <{base}/{prefix}#> .")
    lines.append("")
    lines.append(f"<{base}> a owl:Ontology ;")
    lines.append('    rdfs:label "UML-family relationship ontology"@en ;')
    lines.append(
        '    rdfs:comment "Generated from the OMG metamodel feeds preserved by umlmeta. '
        'Class hierarchy, property domains and ranges, multiplicities, composites, subset '
        'links, recorded opposites and normative OCL constraints are stated facts; the '
        'relationship matrix keeps stated, implied and observed apart."@en ;')
    lines.append('    owl:versionInfo "1" .')
    lines.append("")
    # declare the annotation properties, or the ontology is not OWL 2 DL
    for annotation in ("language", "omgPackage", "abstract", "stereotypeProfile",
                       "stereotypePackage", "specClause",
                       "oclConstraint", "composite", "derived", "declaredType",
                       "lower", "upper", "union", "redefines", "readOnly",
                       "unresolvedSubset", "unresolvedRedefinition"):
        lines.append(f"umlmeta:{annotation} a owl:AnnotationProperty .")
    lines.append("")

    # classes
    for key, row in model["classes"].items():
        subject = key.replace(":", ":")
        frags: list[str] = ["a owl:Class", f'rdfs:label "{_esc(row["name"])}"@en',
                            f'umlmeta:language "{_esc(row["language"])}"@en']
        if row["package"]:
            frags.append(f'umlmeta:omgPackage "{_esc(row["package"])}"')
        if row["abstract"]:
            frags.append("umlmeta:abstract true")
        if row["stereotype"]:
            profile, package, leaf = _stereotype_parts(row["stereotype"])
            frags.append(f'skos:altLabel "{_esc(leaf)}"@en')
            frags.append(f'umlmeta:stereotypeProfile "{_esc(profile)}"')
            if package:
                frags.append(f'umlmeta:stereotypePackage "{_esc(package)}"')
        if row["definition"]:
            frags.append(f'skos:definition "{_esc(row["definition"])}"@en')
        for parent_key in row["bases"]:
            frags.append(f"rdfs:subClassOf {parent_key}")
        for base_meta_key in row["base_metaclasses"]:
            if base_meta_key not in row["bases"]:
                frags.append(f"rdfs:subClassOf {base_meta_key}")
        for constraint in row["constraints"]:
            frags.append(f'umlmeta:oclConstraint "{_esc(constraint["body"])}"')
        lines.append(_block(subject, frags))

    # properties, keyed by owner so a colliding feature name stays unambiguous
    by_owner = {(p["owner"], p["name"]): p for p in model["properties"]}
    own = {(row["owner"], row["name"]) for row in model["properties"]}
    own |= {(row["owner"], row["name"]) for row in model["attributes"]}
    own |= {(row["owner"], row["name"]) for row in SPEC_SUPPLEMENT}

    for prop in model["properties"]:
        iri = f"{prop['owner']}__{prop['name']}"
        kinds = ["owl:ObjectProperty"]
        if not prop["multi"] and str(prop["hi"]) == "1":
            kinds.append("owl:FunctionalProperty")
        frags = [f"a {' , '.join(kinds)}",
                 f'rdfs:label "{_esc(prop["name"])}"@en',
                 f"rdfs:domain {prop['owner']}",
                 f"rdfs:range {prop['range']}"]
        if prop["composite"]:
            frags.append("umlmeta:composite true")
        if prop["derived"]:
            frags.append("umlmeta:derived true")
        # a union feature is not a derived one: ``uml:Action.input`` is the union of the pins
        # of its nodes, which the metamodel states separately from derivation
        if prop["union"]:
            frags.append("umlmeta:union true")
        if prop["readonly"]:
            frags.append("umlmeta:readOnly true")
        frags.extend(_bounds(prop))
        for subset in prop["subsets"]:
            target = _declare_in(model["classes"], own, prop["owner"], subset)
            if target:
                frags.append(f"rdfs:subPropertyOf {target}")
            else:
                # ``sysml2:Element.documentation subsets ownedElement`` but no class in the
                # sysml2 module declares ``ownedElement``: record the name, do not mint an IRI
                frags.append(f'umlmeta:unresolvedSubset "{_esc(subset)}"')
        for redefined in prop["redefines"]:
            target = _declare_in(model["classes"], own, prop["owner"], redefined)
            if target:
                frags.append(f"umlmeta:redefines {target}")
            else:
                frags.append(f'umlmeta:unresolvedRedefinition "{_esc(redefined)}"')
        opp = prop["opposite"]
        if opp and by_owner.get((prop["range"], opp), {}).get("opposite") == prop["name"]:
            frags.append(f"owl:inverseOf {prop['range']}__{opp}")
        lines.append(_block(iri, frags))

    # attributes: features whose type is a value or an enumeration, not a node.  They are
    # stated facts and they carry most of a class's multiplicity, so they are emitted; they
    # are kept out of ``properties`` only because the figure draws association ends.
    for attr in sorted(model["attributes"], key=lambda a: (a["owner"], a["name"])):
        iri = f"{attr['owner']}__{attr['name']}"
        kind = "owl:ObjectProperty" if attr["kind"] == "enumeration" else "owl:DatatypeProperty"
        kinds = [kind]
        if not attr["multi"] and str(attr["hi"]) == "1":
            kinds.append("owl:FunctionalProperty")
        frags = [f"a {' , '.join(kinds)}",
                 f'rdfs:label "{_esc(attr["name"])}"@en',
                 f"rdfs:domain {attr['owner']}",
                 f"rdfs:range {attr['range'] or attr['xsd']}",
                 f'umlmeta:declaredType "{_esc(attr["declaredType"])}"']
        if attr["derived"] or attr["union"]:
            frags.append("umlmeta:derived true")
        frags.extend(_bounds(attr))
        lines.append(_block(iri, frags))

    for spec in SPEC_SUPPLEMENT:
        kinds = ["owl:ObjectProperty"]
        if spec["hi"] == 1:
            kinds.append("owl:FunctionalProperty")
        frags = [f"a {' , '.join(kinds)}",
                 f'rdfs:label "{_esc(spec["name"])}"@en',
                 f"rdfs:domain {spec['owner']}",
                 f"rdfs:range {spec['range']}",
                 "umlmeta:derived true",
                 "umlmeta:union true",
                 f"umlmeta:lower {spec['lo']}",
                 f'umlmeta:upper "{spec["hi"]}"',
                 f"owl:inverseOf {spec['opposite']}",
                 f'umlmeta:specClause "{_esc(spec["clause"])}"']
        for subset_ in spec["subsets"]:
            target_ = _declare_in(model["classes"], own, spec["owner"], subset_)
            if target_:
                frags.append(f"rdfs:subPropertyOf {target_}")
            else:
                frags.append(f'umlmeta:unresolvedSubset "{_esc(subset_)}"')
        lines.append(_block(spec["iri"], frags))

    # enumerations: a class per literal set, an individual per literal, so a model can state
    # ``umlmeta:VisibilityKind__public`` where the metamodel says "VisibilityKind"
    for key, row in sorted(model["enumerations"].items()):
        parent = f"{row['prefix']}:Enumeration"
        if parent not in model["classes"]:
            parent = "uml:Enumeration"
        frags = ["a owl:Class", f'rdfs:label "{_esc(row["name"])}"@en',
                 f'umlmeta:language "{_esc(row["language"])}"@en']
        if parent in model["classes"]:
            frags.append(f"rdfs:subClassOf {parent}")
        lines.append(_block(key, frags))
        for literal in row["literals"]:
            lines.append(_block(f"{key}__{literal['name']}",
                                [f"a {key}",
                                 f'rdfs:label "{_esc(literal["member"])}"@en']))

    # stated lower bounds as OWL restrictions, so "a Dependency has at least one client" is
    # answerable from the ontology alone.  Upper bounds of 1 are functional properties and
    # ``*`` states nothing, so neither becomes a restriction.
    for row in sorted(model["properties"] + model["attributes"],
                      key=lambda r: (r["owner"], r["name"])):
        if int(row["lo"]) <= 0:
            continue
        lines.append(_block(row["owner"], [
            "rdfs:subClassOf [ a owl:Restriction ;\n"
            f"    owl:onProperty {row['owner']}__{row['name']} ;\n"
            f"    owl:minCardinality {int(row['lo'])} ]"]))

    return "\n".join(lines) + "\n"


def emit_json(model: dict[str, Any], base: str = DEFAULT_BASE) -> str:
    classes = {
        key: {
            "iri": key,
            "language": row["language"],
            "stereotype": row["stereotype"],
            "omgPackage": row["package"],
            "abstract": row["abstract"],
            "bases": row["bases"],
            "baseMetaclasses": row["base_metaclasses"],
            "constraints": row["constraints"],
            "definition": row["definition"],
        }
        for key, row in sorted(model["classes"].items())
    }
    return json.dumps({
        "baseIri": base,
        "generatedBy": GENERATOR,
        "umlmetaVersion": UMLMETA_VERSION,
        "umlmetaModules": {prefix: module for prefix, module, _label in MODULES},
        "grades": {
            "stated": "the metamodel states it (typing, subclass axiom, constraint)",
            "implied": "the profile constrains more than the typing does",
            "observed": "an instance corpus shows it; evidence, never a rule",
        },
        "counts": {
            "classes": len(classes),
            "properties": len(model["properties"]),
            "attributes": len(model["attributes"]),
            "enumerations": len(model["enumerations"]),
            "enumerationLiterals": sum(len(row["literals"])
                                       for row in model["enumerations"].values()),
            "inversePairs": model["inverses"],
            "relationshipClasses": len(model["relationships"]),
            "stereotypes": len(model["stereotype_kinds"]),
            "features": model["features"],
            "unmapped": len(model["unmapped"]),
            "requiredProperties": model["required"],
        },
        "relationships": model["relationships"],
        "stereotypes": model["stereotype_kinds"],
        "classes": classes,
        "properties": sorted(model["properties"],
                             key=lambda p: (p["owner"], p["name"])),
        "attributes": sorted(model["attributes"],
                             key=lambda p: (p["owner"], p["name"])),
        "enumerations": {key: [literal["name"] for literal in row["literals"]]
                         for key, row in sorted(model["enumerations"].items())},
        "unmapped": sorted(model["unmapped"], key=lambda r: (r["owner"], r["name"])),
    }, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--base", default=DEFAULT_BASE)
    args = ap.parse_args(argv)

    model = build()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ttl = out / "uml-family-relationships.ttl"
    js = out / "relationships.json"
    ttl.write_text(emit_turtle(model, args.base.rstrip("/")), encoding="utf-8")
    js.write_text(emit_json(model, args.base.rstrip("/")), encoding="utf-8")
    counts = {
        "classes": len(model["classes"]),
        "properties": len(model["properties"]),
        "attributes": len(model["attributes"]),
        "enumerations": len(model["enumerations"]),
        "unmapped": len(model["unmapped"]),
        "features": model["features"],
        "inversePairs": model["inverses"],
        "relationshipClasses": len(model["relationships"]),
        "stereotypes": len(model["stereotype_kinds"]),
        "ttlBytes": ttl.stat().st_size,
    }
    counts["umlmetaSource"] = UMLMETA_SOURCE
    print(json.dumps(counts, indent=2))
    print(f"wrote {ttl}\nwrote {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
