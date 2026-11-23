# Plan: closing the coverage gaps

Generated artifacts describe the OMG metamodel feeds; the gaps below are what is *not* in them
or not yet checked. Every item carries the number that moves when it is done, so "done" is a
measurement, not a claim.

Baseline at HEAD `9aa1841`: `check.py` 51/51, `test_shacl.py` 8/8,
`test_authored_multiplicity.py` 12/12, `docs make check` 9/9, rebuild byte-identical.

## How the numbers are obtained

    .venv/bin/python check.py                      # the gate
    .venv/bin/python scripts/build_ontology.py     # ontology/*.ttl + relationships.json
    .venv/bin/python scripts/build_shacl.py        # shapes/generated/**
    python3.10 -m compileall -q scripts check.py tests docs

Census over `ontology/uml-family-relationships.ttl` (rdflib, transient script), before round A:

    1,687 owl:ObjectProperty   309 owl:DatatypeProperty   1,334 owl:FunctionalProperty
      951 owl:Class (898 classes + 53 enumerations)       1,439 rdfs:subClassOf
      586 owl:inverseOf        16 owl:minCardinality      1,996 lower/upper pairs
    2,207 oclConstraint        486 subset edges            88 unresolvedSubset
      344 stereotypeUri      0 disjointWith  0 propertyDisjointWith
      0 transitive/symmetric/reflexive/asymmetric/inverse-functional properties

## Round A, as shipped

Items 1 and 2 are done. The same census after them:

    1,689 owl:ObjectProperty  (+2 supplemented)      1,998 lower/upper pairs  (+2)
    1,336 owl:FunctionalProperty (+2)                2 specClause citations
      588 owl:inverseOf       (+2, both single-ended by design)
    537 subset edges          (+51)                 37 unresolvedSubset      (from 88)
      344 stereotypeProfile + 344 stereotypePackage  0 stereotypeUri literals
    54/54 check.py checks     (+3: the supplement, the pinned histogram, the stereotype split)
    test_shacl.py 8/8, test_authored_multiplicity.py 12/12, rebuild byte-identical

One number did not reach the 35 this plan predicted, and the reason is a defect in the plan's
own premise, not in the change: two `owner` and two `ownedElement` records belong to
`sysml2:Element`, which declares no `subClassOf` at all, so no walk can reach `uml:Element`.
37 is therefore the floor for the feeds as they stand, and the gate pins the whole histogram
rather than a total.

### Proof the new gates bite

Each gate was broken on purpose, `check.py` run against the broken generator, and the generator
restored from a byte copy; the restore is confirmed by a final green run (54/54).

    mutation                                 check.py
    supplement loses its specClause citation   53/54  [FAIL] the specification supplement is declared and cited (2)
    stereotype goes back to a path literal     53/54  [FAIL] every stereotype states its profile and package (0/344, 344 path literals)
    supplement loses owl:inverseOf             52/54  [FAIL] inverses symmetric except the supplemented pairs (586/586)
                                                      [FAIL] the specification supplement is declared and cited (2)
    Element__owner deleted from the table      51/54  [FAIL] inverses symmetric except the supplemented pairs (586/587)
                                                      [FAIL] the specification supplement is declared and cited (2)
                                                      [FAIL] only the names the feeds omit stay unresolved (63)

The last mutation also exposed a defect in the gate itself: `check.py` read `umlmeta:derived` with
`.toPython()` on a value that may be absent, so a deleted supplement crashed the suite with an
`AttributeError` instead of reporting a failure. Fixed with a `_flag()` helper that reads absent
as false, and the histogram check now prints `pinned:found` counts rather than two empty lists.

## Items

### 1. Declare the two derived unions the feeds omit — done

`umlmeta` carries `Element::ownedElement` and `Namespace::ownedMember` but not their opposite
ends, so the ontology can say what an element owns and never what owns it. That is what the 88
`umlmeta:unresolvedSubset` records are complaining about: `owner` 28, `namespace` 25, then
`directedRelationship` 10, `redefinableElement` 10, `classifier` 3, `owningPackage` 2,
`memberNamespace` 2, `messageEnd` 2, and singletons.

UML 2.5.1 §7.8.6.4 and §7.8.9.6 state both, so they are supplementable without guessing:

    /owner : Element [0..1]{union} (opposite Element::ownedElement)
    /namespace : Namespace [0..1]{union, subsets ...memberNamespace, subsets Element::owner}
        (opposite Namespace::ownedMember)

Carried as `uml:Element__owner` and `uml:NamedElement__namespace`, flagged `umlmeta:derived`
and `umlmeta:union`, given `owl:inverseOf` their stated opposites, and cited with
`umlmeta:specClause`. They live in the generator as a `SPEC_SUPPLEMENT` table so they cannot be
mistaken for feed facts; the build registers them where `_declare_in` looks, which is what
retires the subset records.

Gate: `unresolvedSubset` 88 → 37, and `check.py` asserts the remaining names are exactly the
ones the feeds do not declare (an allowlist, so new drift fails). Result: 88 → 37, 51 records
retired (26 `subPropertyOf uml:Element__owner`, 25 `uml:NamedElement__namespace`).

### 2. `umlmeta:stereotypeUri` holds a path, not a URI — done

344 profile classes each carry a string such as `"UAF::Taxonomy::Achiever"`. The tail is the
subject's own local name in 344 of 344 cases, so the statement adds nothing the key does not
already say; the information is the profile and the package. Replaced by
`umlmeta:stereotypeProfile "UAF"` and `umlmeta:stereotypePackage "Taxonomy"`.

Gate: 0 `stereotypeUri` literals, 344 profiles, and `check.py` asserts profile→module prefix is
one-to-one (`StandardProfile`→`sp` 33, `SysML`→`sysml` 55, `UAF`→`uaf` 256). Result: 344/344
against the fact book, 0 path literals, 3 profiles on 3 modules.

### 3. Translate the OCL implications that need nothing but property tests — done

2,255 constraints are declared, 18 were translated, 2,237 refused. 409 refused as "an
implication between property tests"; of those, 94 named no navigation, no cast and no library
call. They were `sh:or` over property tests away from being checkable, and item 1 unblocked the
`namespace`/`owner` ones.

Shipped: **translated 18 → 113**, one node shape per constraint instead of `sh:sparql`. The
subset is closed under `and`/`or`/`not`/`implies` over atoms that are Boolean tests, `= null`
and `<> null` on one object's own features; anything touching a navigation, a collection, a
cast or a library call still refuses, and the register keeps the reason. A `test` atom demands
an `xsd:boolean` feature, so an unset Boolean reads as false rather than as a null that would
make the shape pass vacuously.

Before/after, measured on the shipped artifacts:

    shapes            684 → 812      (+128, 95 of them the new logic shapes)
    translated OCL     18 → 113      (+95)
    refused         2,237 → 2,142
    check.py           54 → 61
    tests/test_shacl.py  8 → 8 hand-written, plus 95 compiled formulas × 2 instances

Gate: translated 18 → 112 was the estimate; the measured number is 113, which is what
`check.py` pins as a floor (`>= 112`) with the exact value in the check's label.

Each of the 95 shapes is gated by *two* generated instances rather than one failing fixture:
`tests/test_shacl.py` reads `shapes/logic.json`, assigns each feature `absent`/`true`/`false`,
searches for an assignment the formula rejects and one it accepts, and runs both through
pyshacl against that shape alone. A shape that accepts its own falsifying instance fails.

### Proof the item-3 gates bite

Same method: break the generator, run the gate, restore from a byte copy, confirm green.

    mutation                                    gate
    compiled shape loses umlmeta:oclBody        check.py 60/61  [FAIL] every compiled shape carries its OCL text
    and/or stop swapping under negation         test_shacl.py exit 1, 52 of 95 shapes accept their falsifying instance

The second mutation is the one that matters: it leaves every shape parseable and the counts
unchanged (still 113 translated), so a count-only gate would have called it green.

### 4. Reconcile the emitted annotations with the declared constraints — done

The refused OCL is only useful if its text survives, and it did not. `_esc()` ran a tag stripper
(`<[^>]+>` → space) over every literal, which is right for a `skos:definition` harvested from
markup and wrong for OCL, where `<` is an operator: in `ownedParameter->size()<=1 and ...` the
strip ate everything from `<=` to the `>` of the next `->`. Ten bodies came out re-worded, and
because a re-worded body is a different string the damage read as a count.

The 2,207-versus-2,255 gap is not loss at all: 48 declared bodies repeat a body already declared
on the same class, and rdflib dedupes identical triples. Distinct bodies per class equal emitted
rows exactly (2,207 = 2,207), across 761 classes that declare anything.

Fix: markup stripping moved to `_strip_tags()`, called on `skos:definition` only; `_esc()` now
collapses whitespace and escapes quotes and touches nothing else. Measured after:
2,255 declared, 48 repeated declarings, 2,207 rows, 0 classes missing a declared body, 0 classes
stating an undeclared one, 2,142 refused rows all present verbatim.

Gate: two checks, per class and in both directions — every declared body stated on its own class,
and no class stating a body it does not declare. Per class rather than totalled, because the
failure this catches is text drift, which leaves every total unchanged.

The register had the same defect in a milder form: `shapes/untranslated.json` clipped every body
to 400 characters. Only 60 rows ran past the cut, so the total still matched, and a consumer
reconciling the register against the ontology found 60 bodies it could not place. Bodies are now
written whole and whitespace-normalised (`_plain()`), and a third check reconciles the register
row by row: all 2,142 refused rows state a body their own class carries.

### Proof the item-4 gates bite

    mutation                                   gate
    tag stripper restored in _esc()            check.py 61/64  missing, surplus and register checks fail
                                               (sysml2:Association 1 missing, uml:Message 1 surplus,
                                               uml:Message:sending_reception unplaceable)
    every 7th constraint body dropped          check.py 62/64  missing-body and register checks fail
    refused bodies clipped to 120 characters   check.py 63/64  only the register check fails
                                               (uml:NamedElement:has_qualified_name first)

The first mutation is the real defect: the row count moves by nothing, only the text changes.
The totals in those three rows were measured when the gate stood at 64 checks; the disjointness
check added in item 5 makes it 65, so the same three mutations now read 62/65, 63/65 and 64/65.

### 5. Redefinition disjointness - done

`owl:propertyDisjointWith` appeared 0 times. The corpus states one disjointness in OCL,
`AssociationClass`'s `disjoint_attributes_ends`: `ownedAttribute->intersection(ownedEnd)->isEmpty()`.
`build_ontology.py` now recognises exactly that one body shape (`_DISJOINT_BODY`), resolves each
feature name in the declaring class's inheritance chain (`_declare_in`, the same resolver the
subset records use) and emits `owl:propertyDisjointWith` once, in the order the body names them,
because the relation is symmetric and a generated artefact should not carry the mirror image of
every axiom. Output: 1 triple, `Class__ownedAttribute` disjoint `Association__ownedEnd`, the
ancestor pair the feeds name when the constraint is written on `AssociationClass`.

Nothing evaluates it: pyshacl runs the rdfs ruleset, which has no disjointness entailment. The
gate is presence: `check.py` asserts one axiom per declared body, with both sides declared object
properties, recorded in `docs/coverage.md` as "stated, not evaluated". Mutation: dropping the
emission leaves the build and every other check green and takes `check.py` to 64/65.

### 6. Navigability as a derivation, not as data - done

Already present, and correct: `Association__navigableOwnedEnd` ⊂ `Association__ownedEnd` ⊂
`Association__memberEnd`, with `Property__association` the declared opposite of `memberEnd`.
What was missing is the rule a model is checked against: a member end the association does not
own is navigable. `isNavigable` is **not** added to the ontology, because UML 2.5.1 9.5.3 gives
it as a derived attribute and inventing a stored flag would state the opposite of the spec.
Instead `tests/test_navigability.py` derives it, `navigable(A) = memberEnd(A) - ownedEnd(A)`,
over two fixtures: an unowned member end is navigable, an owned one is not, and dropping
`ownedEnd` from the fixture changes the answer, which is what makes ownership the discriminator
rather than a default. Five cases, including that the stated subset chain still holds, because
the derivation reads those two properties and nothing else.

It is a derivation and not a shape on purpose: core SHACL cannot condition on the absence of an
inverse link, so "not owned, therefore navigable" has no NodeShape form without a query, and the
generated shapes carry no queries. Mutation: repointing `navigableOwnedEnd` at `memberEnd` in
the TTL keeps the file parseable and takes the chain case to 4/5.

## Closed without work

- **leaf / static**: both properties exist (`RedefinableElement__isLeaf`, `Feature__isStatic`)
  and are set nowhere, because the specifications set them nowhere. Nothing to cover.
- **AssociationClass**: defined, with `Class` and `Association` as bases; no class in the
  feeds subclasses both, so there is no multiple-inheritance case to model.
- **abstract**: 121 classes are marked; the flag was already emitted.

## Corrections to the 2026-11-21 review

- The doubled stereotype segment is real structure (profile `StandardProfile` contains a
  package named `StandardProfile`), not a defect. The defect is the predicate's name and its
  redundancy with the subject key.
- "296 of 344 stereotype names resolve to `/sp#` classes" was wrong: only the 33
  StandardProfile classes live under `/sp#`; the rest are `/sysml#` (55) and `/uaf#` (256),
  and in every case the resolved class is the subject itself.

## Order

Round A (done): items 1 and 2. Round B: item 3. Round C (done): items 4, 5, 6.

Round C moved: `check.py` 61 -> 65 (three per-class reconciliation checks plus the disjointness
presence check), `owl:propertyDisjointWith` 0 -> 1, `tests/test_navigability.py` 5/5 new,
everything else unchanged - 812 shapes, 113 translated, 2,142 refused, 2,207 stated bodies,
`test_shacl.py` 8/8, `test_authored_multiplicity.py` 12/12, `docs make check` 9/9.

## Round D: the SPARQL escape hatch (done)

The question was whether `sh:sparql` can carry the refused bodies, given that OCL is not
translatable to SPARQL and the grammar differs. Answer: it already carries one. `9aa1841` put
`auth:LowerNotAboveUpper` in `shapes/authored-multiplicity.ttl` as a `sh:SPARQLConstraint`, and
`tests/test_authored_multiplicity.py` fails its `3..1` case without it, under the `rdfs` ruleset
CI runs. Feasibility was never open; the open question was scope, and that resolves to
throughput and to how a wrong query fails.

Measured: 402 of the 2,142 refusals state no OCL at all (335 UAF `«guillemets»` prose, 39 "does
not serialize one", 28 `--` comments). Of the 1,740 that do, 1,516 want a query of one of five
shapes and 224 (55 operations, 169 library predicates) want a definition instead. Cost, on a
query of one pattern: 9.6 ms per focus node after one-time ontology loading.

Landed: `check.py` 65 -> 67, two gates in front of the silent-failure mode (every `sh:select`
must parse; every `sh:path`/`targetClass`/`query` term in every shape file, generated included,
must be one the ontology defines), `tests/test_sparql_probe.py` (three verbatim bodies, each
conforming / violating / mutated, plus per-node cost), a CI step for it, and
`docs/coverage.md` §"SPARQL: the bodies SHACL core cannot carry" replacing item 6's old
rationale. Policy: queries are authored and mutation-tested, not generated.
