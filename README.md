# Serves Me Right

Reusable static browser for Turtle/RDF vocabulary repositories.

The build step parses Turtle files from one or more data directories, applies the SHACL-inspired UI schema in `config/ui-shapes.ttl`, and writes a static site to `dist/`.

## Requirements

- Python 3.12+
- `uv`

## Rebuild The Site

From the repository root:

```bash
uv run python -m scripts.build_site
```

The reusable command is equivalent:

```bash
uv run serves-me-right-build
```

This creates or replaces:

```text
dist/
  index.html
  app.js
  styles.css
  assets/catalog.json
  assets/site-config.json
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
- `src/serves_me_right/build_site.py`: reusable preprocessing script that builds `dist/assets/catalog.json`.
- `scripts/build_site.py`: compatibility wrapper for `python -m scripts.build_site`.
- `src/serves_me_right/site/`: static HTML, CSS, and JavaScript copied into `dist/`.
- `src/serves_me_right/site/vendor/fuse.min.mjs`: vendored Fuse.js browser module used for client-side fuzzy search.
- `.github/workflows/pages.yml`: GitHub Pages deployment workflow.
- `build-plan/agent.md`: design notes and next iteration plan.

## Reuse From Another Repository

Install and run the builder from this repository, while providing data and UI shapes from the consuming repository:

```bash
uvx --from git+https://github.com/YOUR-ORG/serves-me-right serves-me-right-build \
  --data-dir published \
  --data-dir unpublished \
  --shapes site/ui-shapes.ttl \
  --site-title "BioChemEntity Vocabulary" \
  --out-dir dist
```

`--data-dir` can be passed more than once and is searched recursively for `.ttl` files. The consuming repository owns its `ui-shapes.ttl`; each `sh:NodeShape` becomes one table, and `sh:targetClass` selects the class serialized into that table.

The generated `dist/` directory can be uploaded directly with GitHub Pages artifact deployment. You do not need a `gh-pages` source branch.

Example Pages workflow step:

```yaml
- name: Build vocabulary browser
  run: |
    uvx --from git+https://github.com/YOUR-ORG/serves-me-right serves-me-right-build \
      --data-dir published \
      --data-dir unpublished \
      --shapes site/ui-shapes.ttl \
      --site-title "BioChemEntity Vocabulary" \
      --out-dir dist
```

## Change The Search Or Table Columns

Edit `config/ui-shapes.ttl`, then rebuild:

```bash
uv run python -m scripts.build_site
```

Fields marked with `ui:searchable true` are included in browser search. Every `sh:property` listed in a shape becomes a table column.
