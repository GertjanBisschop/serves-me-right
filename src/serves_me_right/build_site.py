from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterable
from urllib.parse import urldefrag, urlparse

from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import OWL, SH

BIOCHEM = Namespace("https://w3id.org/peh/biochementities/")
IDENTIFIERS = Namespace("https://identifiers.org/")
SCHEMA = Namespace("http://schema.org/")
UI = Namespace("https://w3id.org/peh/ui/")

DEFAULT_DATA_DIR = Path("data")
DEFAULT_SHAPES = Path("config/ui-shapes.ttl")
DEFAULT_DIST = Path("dist")
DEFAULT_TITLE = "Vocabulary Browser"


@dataclass(frozen=True)
class Field:
    path: URIRef
    key: str
    label: str
    order: float
    searchable: bool
    render_as: str


@dataclass(frozen=True)
class Shape:
    identifier: str
    target_class: URIRef
    fields: list[Field]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static knowledge graph browser.")
    parser.add_argument(
        "--data-dir",
        action="append",
        type=Path,
        dest="data_dirs",
        help=(
            "Directory containing .ttl files, searched recursively. May be provided multiple times. "
            "Defaults to data/."
        ),
    )
    parser.add_argument("--shapes", type=Path, default=DEFAULT_SHAPES)
    parser.add_argument(
        "--site-src",
        type=Path,
        default=None,
        help=(
            "Static site source directory. Defaults to the packaged site assets."
        ),
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--site-title", default=DEFAULT_TITLE)
    args = parser.parse_args()

    data_dirs = args.data_dirs or [DEFAULT_DATA_DIR]
    graph = load_turtle_directories(data_dirs)
    shapes_graph = Graph()
    shapes_graph.parse(args.shapes, format="turtle")
    shapes = parse_shapes(shapes_graph)

    reset_output(args.out_dir)
    copy_site_assets(args.site_src, args.out_dir)
    assets_dir = args.out_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "meta": {
            "sourceFiles": len(turtle_files(data_dirs)),
            "triples": len(graph),
            "shapes": len(shapes),
        },
        "prefixes": prefixes(graph, shapes_graph),
        "tables": [table_payload(graph, shape) for shape in shapes],
    }

    write_json(assets_dir / "catalog.json", payload)
    write_site_config(assets_dir / "site-config.json", {"title": args.site_title})
    print(
        f"Built {args.out_dir} from {payload['meta']['sourceFiles']} Turtle files in "
        f"{len(data_dirs)} data source(s), "
        f"{payload['meta']['triples']} triples, {sum(len(t['rows']) for t in payload['tables'])} rows."
    )


def load_turtle_directories(data_dirs: list[Path]) -> Graph:
    graph = Graph()
    bind_project_prefixes(graph)
    ttl_files = turtle_files(data_dirs)
    if not ttl_files:
        searched = ", ".join(str(data_dir) for data_dir in data_dirs)
        raise SystemExit(f"No .ttl files found in {searched}")

    for ttl_file in ttl_files:
        graph.parse(ttl_file, format="turtle")

    return graph


def turtle_files(data_dirs: list[Path]) -> list[Path]:
    return sorted(
        ttl_file
        for data_dir in data_dirs
        for ttl_file in data_dir.rglob("*.ttl")
        if ttl_file.is_file()
    )


def parse_shapes(graph: Graph) -> list[Shape]:
    bind_project_prefixes(graph)
    shapes: list[Shape] = []
    for shape_node in sorted(graph.subjects(RDF.type, SH.NodeShape), key=str):
        target_class = graph.value(shape_node, SH.targetClass)
        if not isinstance(target_class, URIRef):
            continue

        fields: list[Field] = []
        for prop in graph.objects(shape_node, SH.property):
            path = graph.value(prop, SH.path)
            if not isinstance(path, URIRef):
                continue

            label = literal_text(graph.value(prop, SH.name)) or compact_iri(path, graph)
            order = numeric_literal(graph.value(prop, SH.order), default=9999)
            searchable = bool_literal(graph.value(prop, UI.searchable))
            render_as = literal_text(graph.value(prop, UI.renderAs)) or "value"
            fields.append(
                Field(
                    path=path,
                    key=compact_iri(path, graph),
                    label=label,
                    order=order,
                    searchable=searchable,
                    render_as=render_as,
                )
            )

        fields.sort(key=lambda field: (field.order, field.label))
        if fields:
            shapes.append(
                Shape(
                    identifier=compact_iri(shape_node, graph),
                    target_class=target_class,
                    fields=fields,
                )
            )

    if not shapes:
        raise SystemExit("No usable sh:NodeShape definitions found.")

    return shapes


def table_payload(graph: Graph, shape: Shape) -> dict:
    fields = [
        {
            "key": field.key,
            "path": str(field.path),
            "label": field.label,
            "searchable": field.searchable,
            "renderAs": field.render_as,
        }
        for field in shape.fields
    ]

    rows = []
    for subject in matching_subjects(graph, shape.target_class):
        values_by_key = {
            field.key: sorted(
                display_value(value, graph, field) for value in graph.objects(subject, field.path)
            )
            for field in shape.fields
        }
        searchable_values = [
            value
            for field in shape.fields
            if field.searchable
            for value in values_by_key[field.key]
        ]
        rows.append(
            {
                "id": str(subject),
                "curie": compact_iri(subject, graph),
                "label": preferred_label(graph, subject),
                "values": values_by_key,
                "searchText": " ".join(searchable_values).lower(),
            }
        )

    rows.sort(key=lambda row: (row["label"].casefold(), row["id"]))
    return {
        "id": shape.identifier,
        "targetClass": str(shape.target_class),
        "targetClassLabel": compact_iri(shape.target_class, graph),
        "fields": fields,
        "rows": rows,
    }


def matching_subjects(graph: Graph, target_class: URIRef) -> list[URIRef]:
    subjects = set(uri_subjects(graph.subjects(RDF.type, target_class)))
    subjects.update(transitive_subclasses(graph, target_class))

    # The current corpus models terms as owl:Class instances and places the domain class
    # in rdfs:subClassOf. Keep owl:Class rows reachable when a shape targets owl:Class.
    if target_class == OWL.Class:
        subjects.update(uri_subjects(graph.subjects(RDF.type, OWL.Class)))

    return sorted(subjects, key=str)


def transitive_subclasses(graph: Graph, target_class: URIRef) -> set[URIRef]:
    subclasses: set[URIRef] = set()
    frontier = [target_class]

    while frontier:
        parent = frontier.pop()
        for child in uri_subjects(graph.subjects(RDFS.subClassOf, parent)):
            if child in subclasses:
                continue
            subclasses.add(child)
            frontier.append(child)

    return subclasses


def uri_subjects(subjects: Iterable) -> Iterable[URIRef]:
    for subject in subjects:
        if isinstance(subject, URIRef):
            yield subject


def preferred_label(graph: Graph, subject: URIRef) -> str:
    labels = [value for value in graph.objects(subject, RDFS.label) if isinstance(value, Literal)]
    if labels:
        untagged = [label for label in labels if not label.language]
        return str((untagged or labels)[0])
    return compact_iri(subject, graph)


def display_value(value, graph: Graph, field: Field) -> str:
    if isinstance(value, Literal):
        return str(value)
    if isinstance(value, BNode):
        return "[nested value]"
    if isinstance(value, URIRef):
        if field.render_as == "label":
            return primary_untagged_label(graph, value) or str(value)
        return str(value)
    return str(value)


def primary_untagged_label(graph: Graph, subject: URIRef) -> str | None:
    for label in graph.objects(subject, RDFS.label):
        if isinstance(label, Literal) and not label.language:
            return str(label)
    return None


def literal_text(value) -> str | None:
    if isinstance(value, Literal):
        return str(value)
    return None


def numeric_literal(value, default: float) -> float:
    if isinstance(value, Literal):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    return default


def bool_literal(value) -> bool:
    if isinstance(value, Literal):
        return bool(value.toPython())
    return False


def compact_iri(value, graph: Graph) -> str:
    if isinstance(value, URIRef):
        parsed = urlparse(str(value))
        if parsed.scheme == "file" and parsed.fragment:
            return f"#{urldefrag(str(value)).fragment}"
        try:
            return graph.namespace_manager.normalizeUri(value)
        except Exception:
            return str(value)
    if isinstance(value, BNode):
        return f"_:{value}"
    return str(value)


def prefixes(*graphs: Graph) -> dict[str, str]:
    merged: dict[str, str] = {}
    for graph in graphs:
        for prefix, namespace in graph.namespaces():
            if prefix:
                merged[prefix] = str(namespace)
    return dict(sorted(merged.items()))


def bind_project_prefixes(graph: Graph) -> None:
    graph.bind("pehbio", BIOCHEM)
    graph.bind("identifiers", IDENTIFIERS)
    graph.bind("schema1", SCHEMA)


def reset_output(out_dir: Path) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)


def copy_site_assets(site_src: Path | None, out_dir: Path) -> None:
    if site_src is not None:
        if not site_src.exists():
            raise SystemExit(f"Site source directory not found: {site_src}")
        shutil.copytree(site_src, out_dir, dirs_exist_ok=True)
        return

    packaged_site = resources.files("serves_me_right").joinpath("site")
    with resources.as_file(packaged_site) as site_path:
        shutil.copytree(site_path, out_dir, dirs_exist_ok=True)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_site_config(path: Path, payload: dict) -> None:
    write_json(path, payload)


if __name__ == "__main__":
    main()
