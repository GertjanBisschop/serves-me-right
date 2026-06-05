# Knowledge Graph Browser Build Plan

## Goal

Deploy a statically hosted GitHub Pages website that lets users browse and search the RDF knowledge graph represented by every Turtle file in `data/`.

The data corpus can grow or change, so deployment must rebuild derived browser artifacts each time. Users should be able to search selected fields, for example searching `rdfs:label` for `phthal`, and see a configurable results table.

## Current Architecture

```text
data/*.ttl
  -> Python preprocessing with rdflib
  -> dist/assets/catalog.json
  -> static GitHub Pages site

config/ui-shapes.ttl
  -> SHACL-inspired UI schema
  -> searchable fields and table columns
```

## First Slice Implemented

- `config/ui-shapes.ttl` defines the first table for `pehterms:BioChemEntity`.
- `scripts/build_site.py` parses all Turtle files, reads the UI shape, and emits `dist/assets/catalog.json`.
- `src/site/` contains a vanilla JS browser with table selection, text search, and result rendering.
- `.github/workflows/pages.yml` builds the site and deploys `dist/` to GitHub Pages.

## SHACL UI Schema Convention

Use one `sh:NodeShape` per table.

- `sh:targetClass`: which RDF class the table covers.
- `sh:property`: one table/search field.
- `sh:path`: predicate to extract.
- `sh:name`: column label.
- `sh:order`: column order.
- `ui:searchable true`: include the field in browser search.

Current matching semantics:

- A subject matches a shape when it has `rdf:type sh:targetClass`.
- A subject also matches when it has `rdfs:subClassOf sh:targetClass`.
- Blank nodes are excluded from top-level rows.

## Design Decisions To Revisit

- Whether search should remain simple substring matching or use a client-side search library.
- Whether large data growth requires chunked JSON or per-table artifacts instead of one `catalog.json`.
- How to render nested blank-node structures such as `pehterms:hasContextAlias`.
- Whether `skos:exactMatch` should be displayed as compact CURIEs, full links, or grouped identifier chips.
- Whether SHACL should stay "SHACL-inspired UI config" or become validatable application schema with stricter constraints.

## Next Iterations

1. Add detail pages or expandable rows for each entity.
2. Add richer renderers for URI links, identifiers, language-tagged labels, and nested values.
3. Add tests for the build output and shape parsing.
4. Add optional JSON-LD output if another consumer needs framed or flattened graph data.
5. Tune GitHub Pages settings after the repository URL and Pages source are confirmed.
