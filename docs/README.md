# Drawing the metamodel

The ontology's own fact book is a model, so the documentation can be generated from it rather
than drawn by hand: every class, feature, multiplicity and generalization in these figures comes
from `ontology/relationships.json`.

| file | what it is |
|---|---|
| `umltikz.sty` | UML class notation over plain TikZ: three-compartment boxes, generalization, association, navigable association, dependency |
| `tools/measure_boxes.py` | measures each box with TeX and writes `build/sizes.json` |
| `tools/draw_ontology.py` | selects classes, lays them out, emits the `.tex` |
| `check.py` | nine checks: boxes measured, no overlap, every edge joins two real boxes, document compiles |
| `figures/` | generated `relationships.{pdf,png}` |
| `relationships.tex` | the generated source for that figure |

## Regenerate

    cd docs
    make relationships      # figures/relationships.{pdf,png}
    make check              # 9 checks, fails on overlap or a dangling edge

Selection is by IRI list (`--classes`) or metamodel package (`--package`); associations are
opt-in with `--assoc owner.feature`, because a metamodel has hundreds of features and a figure
has room for a few.

## Why the box widths are measured

`measure_boxes.py` is not polish. A proportional bold class name and a monospaced `(composite)`
suffix are not functions of a character count, so estimated widths produced boxes that touched
each other while the document compiled perfectly. The probe typesets each class's widest line
with `\settowidth` and writes the value to `build/sizes.txt`, which the layout consumes.

## Notation, and where it stops

A class box is one `rectangle split` node, so compartment separators span the full width and the
box is as wide as its widest compartment; an abstract class prints its name in italics per the
UML 2.5.1 Notation clause. Relationships are drawn after the boxes (TikZ resolves node names at
draw time) but inside a `back` layer, so a box hides whatever crosses it.

Limits, stated rather than hidden:

* **no router** — edges are straight; an association whose route would cross an unrelated box is
  skipped and named in `associationsSkipped` instead of being drawn where nobody can follow it;
* **depth-grid layout** — good for a taxonomy, poor for a graph with many cross-links;
* **operations compartments are empty** — the metamodel carries OCL invariants, not operations,
  and inventing operations would be fiction;
* attribute rows print `+ name : Type [mult]`, `(composite)`; not yet derived/static markers or
  subsetting.

Licence: MPL-2.0, as the rest of this repo.
