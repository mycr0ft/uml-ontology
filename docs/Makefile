# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Jon R. Fox
#
# Draw UML class diagrams of the metamodel from this repo's own fact book.
#
#   cd docs && make check          measure, draw, verify geometry, compile (9 checks)
#   cd docs && make relationships  generate figures/relationships.{pdf,png}
#   cd docs && make clean
#
# The .tex sources stay flat in docs/ because tectonic resolves \usepackage{umltikz} only
# beside the main file; only the artifacts go to figures/.
CLASSES_REL ?= uml:Element,uml:NamedElement,uml:Relationship,uml:DirectedRelationship,uml:Dependency,uml:Abstraction,uml:Realization,uml:Usage,uml:PackageableElement,uml:Package,uml:Classifier,uml:Feature,uml:Type,uml:TypedElement
ASSOC_REL ?= --assoc uml:Dependency.client --assoc uml:Dependency.supplier
TECTONIC ?= $(HOME)/.local/bin/tectonic
PYTHON ?= python3

.PHONY: all relationships check clean

all: relationships

relationships:
	$(PYTHON) tools/measure_boxes.py --classes "$(CLASSES_REL)" --out build/sizes.json
	$(PYTHON) tools/draw_ontology.py --classes "$(CLASSES_REL)" $(ASSOC_REL) \
	    --sizes build/sizes.json --layout-json build/layout.json --out relationships.tex
	$(TECTONIC) -X compile relationships.tex --outdir build
	mkdir -p figures
	cp build/relationships.pdf figures/relationships.pdf
	pdftoppm -r 150 -png -singlefile build/relationships.pdf figures/relationships

check:
	$(PYTHON) check.py --classes "$(CLASSES_REL)" $(ASSOC_REL) --out relationships.tex

clean:
	rm -rf build probe.tex relationships.tex sizes.txt
