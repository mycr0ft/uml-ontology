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

## OCL translation: what SHACL core can carry

`shapes/untranslated.json` refuses 2,142 of the 2,255 normative constraint bodies, each with the
reason it was refused. 113 are checked. The second group, 95 shapes, is the same-object
comparison subset — a constraint whose atoms are all tests on one object's own features, joined
by `and`/`or`/`not`/`implies`:

    namespace = null and owner <> null implies visibility = null

That compiles whole into a SHACL core tree: `sh:or(sh:not(sh:and(...)), property)` over
`sh:property [ sh:path … ; sh:minCount 1 ]` / `sh:maxCount 0` / `sh:hasValue true`. One node
shape per constraint, named `<owner>_<constraint>`, carrying `umlmeta:oclName` and
`umlmeta:oclBody` so the shape can be read back against the body it came from. No `sh:sparql`.

Four rules make the mapping honest rather than approximate:

* **An absent Boolean test is false.** OCL's `if` on an unset attribute is `null`, not `false`,
  so only `xsd:boolean`-ranged features may become a `sh:hasValue true` test; anything else
  refuses the whole formula rather than publish a weaker rule under the constraint name.
* **`= null` is "no value" and `<> null` is "at least one value"** — `sh:maxCount 0` and
  `sh:minCount 1` on the path, not a check on any value.
* **`and`/`or` swap under negation.** `not(a and b)` is `sh:or(sh:not a, sh:not b)`.
* **The refused text is carried, not paraphrased.** All 2,142 refused bodies are stated verbatim
  as `umlmeta:oclConstraint` on the class that declares them, and `check.py` reconciles the two
  per class in both directions, so a body that is dropped or re-escaped on the way out fails the
  gate even though every total is unchanged.
* **A formula that touches a navigation or a collection is refused**, not truncated: `->`,
  `select`, `forAll`, `exists`, `let`, `size`, `allInstances`, `oclIs`, `::` and the rest are on
  the refusal list, and the register records which one stopped it.

The gate for this subset is not a count alone: `tests/test_shacl.py` takes each of the 95
compiled formulas from `shapes/logic.json`, searches its atom assignments for an instance that
must fail it and one that must pass it, and runs both through pyshacl. A shape that accepts its
own falsifying instance fails the test, so a mis-compiled tree cannot pass by parsing.

## Multiplicity: one fact, three statements

The bounds were already in the SHACL shapes — `lo`/`hi` become `sh:minCount`/`sh:maxCount` on
the declaring class (812 node shapes, 1,031 upper bounds). What was missing was the same fact
on the OWL side, so anything that was not a SHACL validator could not see it. Both are now
stated, from the same `lo`/`hi`:

| statement | where | how many | what it is good for |
|---|---|---|---|
| `sh:minCount` / `sh:maxCount` | `shapes/` | 812 shapes | validating a model |
| `umlmeta:lower` / `umlmeta:upper` | `ontology/` | 1,996 features | querying the metamodel itself; `*` survives as a string |
| `owl:minCardinality` restriction | `ontology/` | 16 features | a reasoner sees "a Dependency has at least one client" with no umlmeta vocabulary |

Three deliberate choices:

* **Annotations, not a datatype.** UML's own `lower`/`upper` are `ValueSpecification`
  instances (`LiteralInteger`, `LiteralUnlimitedNatural`, `OpaqueExpression`). Modelling that
  structure is faithful to UML and useless in practice: every query becomes two hops, and no
  reasoner can read a bound out of an `OpaqueExpression`. `umlmeta` already reduces the bound
  to `lo`/`hi`, so the ontology states what the generator actually knows. The structural half
  is listed under "authored multiplicity" below — a model that *authors* multiplicity
  needs it, and the metamodel does not.
* **Restrictions only where the lower bound is stated.** An upper bound of 1 is already an
  `owl:FunctionalProperty`; an upper bound of `*` states nothing. `owl:minCardinality 0` is
  the absence of a restriction, so emitting it would double the file to say nothing.
* **`UnlimitedNatural` is an approximation.** Its value space is the non-negative integers
  *plus* `*`, which no XSD datatype has. It is emitted as `xsd:nonNegativeInteger` with
  `umlmeta:declaredType "UnlimitedNatural"`, and the exact bound survives as `hi: "*"` in the
  fact book. Losing the declared name would make `Integer` and `UnlimitedNatural` features
  indistinguishable; the annotation keeps them apart.

`lower <= upper` is not an OWL axiom — it is a constraint on the *values* of two properties,
and OWL restricts structure, not values. It is asserted twice instead: in `check.py` over the
1,996 stated bounds (`lo` integral, `hi` integral or `*`, `hi` an exception to `lo` in no row),
and in SHACL over any bound a model authors, as `sh:sparql` on the pair — see the next section.

Writing the first of those found four features whose upper bound `umlmeta` stores as a digit
string (`bpmn:ChoreographyTask.messageFlowRef` is `1..'2'`, as are `uml:DurationObservation.event`
and both `firstEvent` ends). The ontology and the shapes already coerced it, so only the fact
book was wrong; `hi` is now `int` or `"*"` in all 1,996 rows, and `check.py` says so.

## Authored multiplicity: what a model may write

The three statements above are about the metamodel's own bounds, which the generator reduces to
`lo`/`hi` before anyone asks. A *model* is different: it writes `lowerValue`/`upperValue`, and
those hold `ValueSpecification` instances. `shapes/authored-multiplicity.ttl` (hand-written,
separate from the generated file so regeneration cannot clobber it) says what those instances
may be. Four shapes, 12 test cases:

| shape | says | what a plain range would have said instead |
|---|---|---|
| `auth:BoundIsALiteral` | a bound is a `LiteralInteger`, `LiteralUnlimitedNatural` or `OpaqueExpression` | `uml:ValueSpecification`: true of anything, useful for nothing |
| `auth:BoundIsNotNegative` | `LiteralInteger`/`LiteralUnlimitedNatural` values are `>= 0` | nothing |
| `auth:BoundHasOneValue` | a literal bound carries exactly one value | nothing |
| `auth:LowerDoesNotExceedUpper` | `lower <= upper`, reading both through the literals | nothing |

Two findings are worth recording, because both were wrong in the first draft:

* **`sh:class uml:ValueSpecification` is vacuous.** `lowerValue rdfs:range uml:ValueSpecification`,
  and a validator running with `inference="rdfs"` derives that type for every object of the
  property — including a `uml:Class` used as a bound. The type is a consequence of the edge, not
  a check on it. Enumerating the three interpreted kinds is a real test; `ex:Person a uml:Class`
  now fails.
* **`sh:class uml:ValueSpecification` is also too permissive without inference.** UML permits
  any `ValueSpecification` as a bound. Nothing in this repository can read a number out of an
  arbitrary `Expression`, so the shape states the narrower rule the pipeline can honour and the
  message says so. A bound of another kind is rejected as unreadable, not as illegal.

`OpaqueExpression` is accepted because its `body` can be `"*"` or `"count(ownedAttribute)"` and
the shape does not try to parse it: the shapes say what may be *written*, `check.py` says what
the generator *read*.

Tests assert *which* violation fired — its message, its source shape and its focus node — not
just `conforms`. A shape pointed at the wrong property still fails a graph, and would still pass
a test that only looked at `conforms`.

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

## Subsetting: 537 stated, 37 named but not declared

`subsets` is the fact that made this section necessary. The generator used to mint
`Owner__target` for every subset, which is right only when the target is declared on the
owner: `Dependency.client subsets source`, and `source` is declared on `DirectedRelationship`.
574 subset statements produced 574 IRIs, 448 of which nothing defined — the ontology asserted
that a property was a subproperty of a name that did not exist.

The target is now resolved by walking the owner's bases, and what cannot be resolved is
**recorded rather than minted**: `umlmeta:unresolvedSubset "classifier"`. That count used to be
88, and this document used to account for all of them as four pairs from `sysml2` — which was
wrong. Four were; 84 named `owner` or `namespace` on UML features, and both of those are stated
by UML 2.5.1 and absent from the feeds.

### The two derived unions the feeds omit

    uml:Element__owner           0..1  uml:Element    derived union, inverse of ownedElement
    uml:NamedElement__namespace  0..1  uml:Namespace  derived union, inverse of ownedMember

UML 2.5.1 7.8.6.4 states `/owner : Element [0..1]{union} (opposite Element::ownedElement)`, and
7.8.9.6 states `/namespace : Namespace [0..1]{union, subsets memberNamespace, subsets
Element::owner} (opposite Namespace::ownedMember)`. Declaring them is what makes the ontology
able to answer *what owns this element*, which it could not: it carried `ownedElement` and
`ownedMember` and only one direction of each relation.

They are the only two properties in the ontology that are not feed facts. Each one carries
`umlmeta:specClause` with the clause text it comes from, is flagged `umlmeta:derived` and
`umlmeta:union` as that text says, and states `owl:inverseOf` the opposite the clause names.
Because the opposite end is one the feeds do not carry, these two pairs are the only
single-ended inverses in the file, and the symmetry gate names them rather than tolerating
asymmetry in general.

Effect: 26 properties now state `rdfs:subPropertyOf uml:Element__owner` and 25 state
`uml:NamedElement__namespace`, retiring 51 of the 88 records. The 37 left sit under 12 names —
`directedRelationship` 10, `redefinableElement` 10, `classifier` 3, `owner` 2, `ownedElement` 2,
`owningPackage` 2, `memberNamespace` 2, `messageEnd` 2, and four singletons. The `owner` and
`ownedElement` rows come from `sysml2:Element`, which declares no bases at all, so no walk
reaches `uml:Element`; the rest are features the UML feed really does omit. `check.py` pins the
total and the whole name histogram, so a new name means the generator lost a feature, not that
coverage grew.

### Stereotypes state a profile and a package, not a path

`"StandardProfile::StandardProfile::Auxiliary"` is a path, and in 344 of 344 rows its tail is
the subject's own local name, so the literal restated the subject and the only facts in it were
the profile and the package. It is now `umlmeta:stereotypeProfile "StandardProfile"` plus
`umlmeta:stereotypePackage "StandardProfile"`. The gate compares all 344 against the fact book,
requires zero `stereotypeUri` literals, and requires the profiles to map one-to-one onto
modules: `StandardProfile`→`sp` 33, `SysML`→`sysml` 55, `UAF`→`uaf` 256.

The rest of the "uncovered" feature facts are now annotations on the property: `umlmeta:union`
(21 union ends, previously mislabelled `derived`), `umlmeta:readOnly` (48), `umlmeta:redefines`
(135).

What is still open, in the order it will be closed, is in [PLAN.md](../PLAN.md).

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

## SPARQL: the bodies SHACL core cannot carry

The other way to cover a refused body is `sh:sparql`, and this document used to rule it out on
the grounds that the constraints should stay declarative. That reasoning was wrong on the facts,
because the repo already depends on it: `auth:LowerNotAboveUpper` in
`shapes/authored-multiplicity.ttl` is a `sh:SPARQLConstraint`, it has been since the authored
multiplicity round, and `tests/test_authored_multiplicity.py` asserts that `3..1` fails while
`0..*` conforms. Core SHACL cannot compare two values it reads from two nodes, so without that
query the case is untestable. pyshacl evaluates it under the `rdfs` ruleset CI runs. There is
nothing to explore here: the mechanism is in production, at two constraints.

What there is *not* is a translation. OCL is a typed expression language over an object model;
SPARQL is a graph-pattern query language. `self.start.covered = self.finish.covered` has no
syntactic counterpart, and every body has to be re-expressed against the ontology's own IRIs,
which is authorship, not conversion. So the useful question is not *can* a body be carried but
*what does carrying it cost*, and that is measurable.

### What is even an expression

402 of the 2,142 refusals state no OCL at all: 335 are UAF prose clauses quoting a stereotype in
`«guillemets»`, 39 say the specification does not serialize one, 28 are `--` comments. A query
can do nothing with those; they need a person. They sit inside the first and last rows of the
generator's own partition, which runs over all 2,142:

| refusal reason | bodies | in a query |
| --- | --- | --- |
| outside the translatable subset | 1,084 | a pattern and a `FILTER`, once the operands are spelled |
| an implication between property tests | 339 | `FILTER NOT EXISTS` over the antecedent |
| a global quantification over the whole model | 209 | a class pattern plus `FILTER NOT EXISTS` |
| a set operation over a navigation | 112 | property path, or `NOT EXISTS` in both directions |
| a filtered selection | 60 | pattern plus `FILTER` |
| a transitive closure over a navigation | 47 | `+` or `*` in a property path |
| a cast | 35 | the target class in the pattern |
| an operation, not a property test | 55 | needs the operation defined first |
| a model-library predicate | 169 | needs the predicate defined first |

Taking the 402 out of the count, 1,516 of the 1,740 expressions fall in rows that want a query
of one of a handful of shapes. The 55 operations and 169 library predicates, 224 bodies, want a
definition the ontology does not have, and no amount of SPARQL syntax supplies it.

### What it costs

`tests/test_sparql_probe.py` takes three of those bodies verbatim from
`shapes/untranslated.json`, writes each as a query, and checks four things per case: the
conforming instance passes, the violating one fails and the report names the shape, a one-clause
mutation of the query changes a verdict, and the body is still in the refusal register. Measured
on this box, the `same_lifeline` query costs 9.6 ms per focus node after about 5 s of one-time
ontology loading: 6.3 s at 100 instances, 8.2 s at 300. A model with 10,000 instances of a
constrained class pays roughly a minute and a half, per constraint. That is the real argument
against generating all 1,516: not effort, throughput.

The mutation line is the one that matters, because a query is text nothing parses until
validation time. Point it at a property the ontology does not define and it matches nothing and
the constraint holds forever, silently, on every graph. Two gates now stand in front of that:
`check.py` parses every `sh:select` in `shapes/` and fails on a syntax error, and the
defined-`uml:`-term check that used to cover authored shapes now covers the paths and the query
text of every shape file, generated included. `tests/test_sparql_probe.py` covers the third
failure, the query that parses and names real terms but tests the wrong thing.

So the policy: a query is authored, reviewed, and mutation-tested, one per body worth its
throughput, the way `auth:LowerNotAboveUpper` was. Generated queries would need a fixture per
template before they could land, and that fixture is the same work as writing the query by hand
for anything that is not one of a handful of shapes.

## Not yet, and what each would cost

In the order I would build them, cheapest-useful first.

1. **Sibling redefinitions as a class axiom.** The one disjointness the corpus states in OCL,
   `AssociationClass`'s `disjoint_attributes_ends`, is now an axiom: `Class__ownedAttribute`
   is `owl:propertyDisjointWith` `Association__ownedEnd`, one triple, one direction. Nothing
   evaluates it, because the rdfs ruleset has no disjointness entailment; the gate asserts the
   axiom is still stated and the doc says so. What is still not stated is the pair of *siblings*
   that both redefine the same feature, which is an inference and a modelling decision, not a
   transcription of a body the feeds carry.
2. **Navigability as a stored flag.** Not done, and deliberately: `Property::isNavigable` is a
   derived attribute, so the ontology keeps the derivation's inputs (`memberEnd`, `ownedEnd`,
   `navigableOwnedEnd` nested under `ownedEnd`) and `tests/test_navigability.py` computes
   `navigable(A) = memberEnd(A) - ownedEnd(A)` over two fixtures. A stored boolean would let a
   model disagree with its own ends.
3. **Abstract/leaf/static and `AssociationClass`.** `isAbstract` is emitted; the rest are
   annotations on classes that already exist.
4. **SysML v1 ↔ v2 correspondence.** `umlmeta` has `v1_to_v2_as.py` mapping tables; the
   alignment artefact is `owl:equivalentClass`/`equivalentProperty` pairs plus a register of
   the ones that are only *similar*. This is the one with a consumer waiting.
5. **Implied and observed grades.** The README's second and third grades: profile clauses
   (`«satisfy»` narrows `Dependency` ends) and an instance corpus. Both are separate artefacts
   over this one; the grade vocabulary is already in the shapes (`umlmeta:grade`).
6. **Widening the OCL subset.** 2,142 constraints are refused with a reason; 113 translate. The
   cheap widening is exhausted: of the 583 comparison bodies only one compares a path to a
   literal, and core SHACL cannot compare two paths. What is left is either authorship in
   `sh:sparql` (see the section above, which also says why it is not generated) or a definition
   for the 224 bodies that call an operation or a library predicate.

Items 1 and 2 close the multiplicity story properly. Item 4 is the one a reader of the papers
will ask for next.
