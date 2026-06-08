# Serves Me Right

Static browser for the Turtle knowledge graph in `data/`.

The build step parses every `data/*.ttl` file, applies the SHACL-inspired UI schema in `config/ui-shapes.ttl`, and writes a static site to `dist/`.

## Requirements

- Python 3.12+
- `uv`

## Rebuild The Site

From the repository root:

```bash
uv run python -m scripts.build_site
```

This creates or replaces:

```text
dist/
  index.html
  app.js
  styles.css
  assets/catalog.json
```

## Serve Locally

After rebuilding:

```bash
python3 -m http.server 8000 --directory dist
```

Then open:

```text
http://127.0.0.1:8000/
```

Use another port if `8000` is already in use:

```bash
python3 -m http.server 8080 --directory dist
```

## Useful Files

- `data/`: source Turtle files.
- `config/ui-shapes.ttl`: controls which RDF classes, predicates, table labels, column order, and search fields are exposed.
- `scripts/build_site.py`: preprocessing script that builds `dist/assets/catalog.json`.
- `src/site/`: static HTML, CSS, and JavaScript copied into `dist/`.
- `src/site/vendor/fuse.basic.min.mjs`: vendored Fuse.js browser module used for client-side fuzzy search.
- `.github/workflows/pages.yml`: GitHub Pages deployment workflow.
- `build-plan/agent.md`: design notes and next iteration plan.

## Change The Search Or Table Columns

Edit `config/ui-shapes.ttl`, then rebuild:

```bash
uv run python -m scripts.build_site
```

Fields marked with `ui:searchable true` are included in browser search. Every `sh:property` listed in a shape becomes a table column.
