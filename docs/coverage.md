# What the ontology covers, and what it does not

Coverage here is counted in **features**, not classes: a class with no ends says nothing on
its own, and a feature the generator cannot type is a hole wherever it lives. Every module of
`umlmeta` is walked, so the census is over all six metamodels at once.

    2,023  declared features            (898 classes, uml + sp + sysml + uaf + bpmn + sysml2)
    1,640  association ends             -> ontology/relationships.json "properties"
      356  attributes                   -> "attributes"   (309 datatype, 47 enumeration-valued)
       27  unmapped, each with a reason -> "unmapped"

`check.py` asserts `1640 + 356 + 27 == 2023`, so a feature cannot leave the pipeline without
appearing in one of the three lists. That assertion, not the prose here, is what keeps this
document true.

## Multiplicity: one fact, three statements

The bounds were already in the SHACL shapes — `lo`/`hi` become `sh:minCount`/`sh:maxCount` on
the declaring class (684 node shapes, 1,031 upper bounds). What was missing was the same fact
on the OWL side, so anything that was not a SHACL validator could not see it. Both are now
stated, from the same `lo`/`hi`:

| statement | where | how many | what it is good for |
|---|---|---|---|
| `sh:minCount` / `sh:maxCount` | `shapes/` | 684 shapes | validating a model |
| `umlmeta:lower` / `umlmeta:upper` | `ontology/` | 1,996 features | querying the metamodel itself; `*` survives as a string |
| `owl:minCardinality` restriction | `ontology/` | 16 features | a reasoner sees "a Dependency has at least one client" with no umlmeta vocabulary |

Three deliberate choices:

* **Annotations, not a datatype.** UML's own `lower`/`upper` are `ValueSpecification`
  instances (`LiteralInteger`, `LiteralUnlimitedNatural`, `OpaqueExpression`). Modelling that
  structure is faithful to UML and useless in practice: every query becomes two hops, and no
  reasoner can read a bound out of an `OpaqueExpression`. `umlmeta` already reduces the bound
  to `lo`/`hi`, so the ontology states what the generator actually knows. The structural half
  is listed under "not yet" below — a model that *authors* multiplicity needs it.
* **Restrictions only where the lower bound is stated.** An upper bound of 1 is already an
  `owl:FunctionalProperty`; an upper bound of `*` states nothing. `owl:minCardinality 0` is
  the absence of a restriction, so emitting it would double the file to say nothing.
* **`UnlimitedNatural` is an approximation.** Its value space is the non-negative integers
  *plus* `*`, which no XSD datatype has. It is emitted as `xsd:nonNegativeInteger` with
  `umlmeta:declaredType "UnlimitedNatural"`, and the exact bound survives as `hi: "*"` in the
  fact book. Losing the declared name would make `Integer` and `UnlimitedNatural` features
  indistinguishable; the annotation keeps them apart.

`lower <= upper` is not asserted. OWL has no way to say it, and `umlmeta`'s data has no case
that violates it, so it stays a known gap rather than a false claim — see "not yet".

## Attributes: the 356 features that were missing

Line 119 of the old README said enumeration and primitive features were "intentionally
absent". That was honest and wrong: `Class.isAbstract`, `NamedElement.visibility` and
`LiteralInteger.value` are features of the metamodel, and a fact book that omits them cannot
answer "what may a class carry?".

They are now emitted, in the two forms their type allows:

* **309 datatype-valued** — `owl:DatatypeProperty` with an XSD range, `owl:FunctionalProperty`
  when the upper bound is 1: `String` 156, `Boolean` 134, `Integer` 12, `UnlimitedNatural` 4,
  `Real` 3. The UML type name rides along as `umlmeta:declaredType`.
* **47 enumeration-valued** — `owl:ObjectProperty` ranging over the enumeration class, because
  the value is an IRI (see below), not a literal.

They are **kept out of `"properties"`** on purpose. That list is the feed for the generated
figure, and the figure is a reviewed artefact: adding 356 rows would change every box in it.
Separation of concerns rather than a second opinion — `"properties"` is the association ends
the figure draws, `"attributes"` is the rest of the class.

## Enumerations: 53 classes, 250 literals

`VisibilityKind`, `AggregationKind`, `AdHocOrdering` and fifty others become `owl:Class`
subclasses of `uml:Enumeration`, and every literal is an **individual** of that class:
`uml:VisibilityKind__public`, labelled `public`. Individuals rather than an OWL datatype
enumeration, because a model that references `private` must be able to write an IRI for it.

Python forced a rename on four literals (`break`, `in`, `None` and friends are keywords or
constants), so the member name is stored next to the literal name and the label is the
metamodel's own spelling. The gate counts individuals against the fact book: 250/250.

## Subsetting: 486 stated, 88 named but not declared

`subsets` is the fact that made this section necessary. The generator used to mint
`Owner__target` for every subset, which is right only when the target is declared on the
owner: `Dependency.client subsets source`, and `source` is declared on `DirectedRelationship`.
574 subset statements produced 574 IRIs, 448 of which nothing defined — the ontology asserted
that a property was a subproperty of a name that did not exist.

The target is now resolved by walking the owner's bases, and what cannot be resolved is
**recorded rather than minted**: `umlmeta:unresolvedSubset "ownedElement"` (88 of them, all
`owner`/`ownedElement` pairs from `sysml2`, whose module declares neither feature on
`sysml2:Element`). `check.py` asserts both halves — no `rdfs:subPropertyOf` or
`umlmeta:redefines` object may be undefined, and the count of named-but-undeclared targets is
pinned at 88, so a change in the feed shows up as a failing gate instead of a silent drop.

The rest of the "uncovered" feature facts are now annotations on the property: `umlmeta:union`
(21 union ends, previously mislabelled `derived`), `umlmeta:readOnly` (48), `umlmeta:redefines`
(135).

## The 27 that are not mapped, and why each is a decision

Registered, not dropped. `check.py` fails if a feature arrives with a type nobody has decided
about — silence is how features disappear, which is the failure this whole document exists to
prevent.

    18  the feed declares no type for this feature
        8  the feed types this as a DOM node
        1  the diagram-interchange package

* **18 untyped**, almost all in `sysml2` (`Expose.visibility`, `Feature.direction`,
  `Membership.visibility`, `OccurrenceUsage.portionKind`, `FramedConcernMembership.kind`, ...).
  `umlmeta`'s SysML v2 runtime declares these without a type. The fix is an **override table**
  — `(owner, feature) -> type` — hand-checked against the SysML v2 specification, with the gate
  asserting that every override resolves to a class or enumeration that exists. Guessing the
  types here, in a file that claims to be a projection of the standards, would be the one thing
  this repo cannot do.
* **8 `xml.dom.Element`** — BPMN's element documentation. A DOM node is not a model element;
  if BPMN means a `String` there, that is an `umlmeta` typing question, not a mapping decision.
* **1 `BPMNDI.BPMNDiagram`** (`bpmn:Definitions.diagrams`) — the BPMN diagram-interchange
  package: layout, not model. It deserves its own small ontology, not a corner of this one.

## Not yet, and what each would cost

In the order I would build them, cheapest-useful first.

1. **Authored multiplicity.** `LowerValue`/`UpperValue` as `ValueSpecification` subclasses
   (`LiteralInteger`, `LiteralUnlimitedNatural`, `OpaqueExpression`, `Interval`) plus
   `lowerValue`/`upperValue` object properties on `MultiplicityElement`. The classes are
   already in the 898; what is missing is the two linking properties and an instance per
   authored bound. Needed only when a *model* carries a non-literal bound — the metamodel's
   own bounds are already stated three ways. Cost: 2 properties, 1 SHACL shape proving an
   upper value is one of the literal kinds.
2. **Bounds consistency.** `lower <= upper` per feature, and `hi` integral-or-`*`. Pure data,
   so it belongs in `check.py` today; a model-level version is a SHACL shape.
3. **Redefinition as a class axiom.** Redefinitions are now stated (`umlmeta:redefines`, 135),
   but only as annotations. A redefining feature also *disjoints* itself from its siblings in
   the redefined context, which needs `owl:propertyDisjointWith` against the ancestor's other
   specialisations. That is a real inference and a real modelling decision, not a one-liner.
4. **Navigability and owned ends.** Requires the `memberEnd`/`ownedEnd` split, which
   `umlmeta` carries as `assoc` + `opp`; the ontology currently states the pair, not which end
   is navigable.
5. **Abstract/leaf/static and `AssociationClass`.** `isAbstract` is emitted; the rest are
   annotations on classes that already exist.
6. **SysML v1 ↔ v2 correspondence.** `umlmeta` has `v1_to_v2_as.py` mapping tables; the
   alignment artefact is `owl:equivalentClass`/`equivalentProperty` pairs plus a register of
   the ones that are only *similar*. This is the one with a consumer waiting.
7. **Implied and observed grades.** The README's second and third grades: profile clauses
   (`«satisfy»` narrows `Dependency` ends) and an instance corpus. Both are separate artefacts
   over this one; the grade vocabulary is already in the shapes (`umlmeta:grade`).
8. **Widening the OCL subset.** 2,237 constraints are refused with a reason; 18 translate. Each
   new form (closures, `allInstances`, library predicates) is a whitelist entry in
   `scripts/build_shacl.py` and a test that makes the shape fire.

Items 1, 2 and 3 close the multiplicity story properly. Item 6 is the one a reader of the papers
will ask for next.
