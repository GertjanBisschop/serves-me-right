from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterable
from urllib.parse import urldefrag, urlparse

from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import OWL, SH

UI = Namespace("https://w3id.org/peh/ui/")
PREFIX_DECLARATION = re.compile(
    r"^\s*(?:@prefix|PREFIX)\s+([A-Za-z][\w.-]*|):\s*<([^>]+)>",
    re.IGNORECASE,
)

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
    hierarchy_enabled: bool
    hierarchy_path: URIRef | None
    fields: list[Field]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the static knowledge graph browser."
    )
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
        help=("Static site source directory. Defaults to the packaged site assets."),
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--site-title", default=DEFAULT_TITLE)
    args = parser.parse_args()

    data_dirs = args.data_dirs or [DEFAULT_DATA_DIR]
    data_files = turtle_files(data_dirs)
    graph = load_turtle_files(data_files, data_dirs)
    shapes_graph = Graph()
    shapes_graph.parse(args.shapes, format="turtle")
    prefix_bindings = declared_prefixes([*data_files, args.shapes])
    bind_declared_prefixes(graph, prefix_bindings)
    bind_declared_prefixes(shapes_graph, prefix_bindings)
    shapes = parse_shapes(shapes_graph)

    reset_output(args.out_dir)
    copy_site_assets(args.site_src, args.out_dir)
    assets_dir = args.out_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "meta": {
            "sourceFiles": len(data_files),
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
    return load_turtle_files(turtle_files(data_dirs), data_dirs)


def load_turtle_files(ttl_files: list[Path], data_dirs: list[Path]) -> Graph:
    graph = Graph()
    if not ttl_files:
        searched = ", ".join(str(data_dir) for data_dir in data_dirs)
        raise SystemExit(f"No .ttl files found in {searched}")

    for ttl_file in ttl_files:
        graph.parse(ttl_file, format="turtle")

    return graph


def declared_prefixes(paths: Iterable[Path]) -> dict[str, str]:
    prefixes_by_name: dict[str, str] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = PREFIX_DECLARATION.match(line)
            if match:
                prefix, namespace = match.groups()
                if prefix:
                    prefixes_by_name[prefix] = namespace
    return prefixes_by_name


def bind_declared_prefixes(graph: Graph, prefixes_by_name: dict[str, str]) -> None:
    for prefix, namespace in prefixes_by_name.items():
        graph.bind(prefix, Namespace(namespace), replace=True)


def turtle_files(data_dirs: list[Path]) -> list[Path]:
    return sorted(
        ttl_file
        for data_dir in data_dirs
        for ttl_file in data_dir.rglob("*.ttl")
        if ttl_file.is_file()
    )


def parse_shapes(graph: Graph) -> list[Shape]:
    shapes: list[Shape] = []
    for shape_node in sorted(graph.subjects(RDF.type, SH.NodeShape), key=str):
        target_class = graph.value(shape_node, SH.targetClass)
        if not isinstance(target_class, URIRef):
            continue

        shape_id = compact_iri(shape_node, graph)
        hierarchy_enabled_value = optional_bool_literal(
            graph.value(shape_node, UI.hierarchyEnabled)
        )
        hierarchy_path = graph.value(shape_node, UI.hierarchyPath)
        if hierarchy_enabled_value is True and not isinstance(hierarchy_path, URIRef):
            raise SystemExit(
                f"{shape_id} sets ui:hierarchyEnabled true but does not define "
                "ui:hierarchyPath."
            )
        hierarchy_enabled = (
            hierarchy_enabled_value
            if hierarchy_enabled_value is not None
            else isinstance(hierarchy_path, URIRef)
        )
        if not hierarchy_enabled:
            hierarchy_path = None

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
                    identifier=shape_id,
                    target_class=target_class,
                    hierarchy_enabled=hierarchy_enabled,
                    hierarchy_path=hierarchy_path,
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

    subjects = matching_subjects(graph, shape.target_class)
    rows = []
    for subject in subjects:
        values_by_key = {
            field.key: sorted(
                display_value(value, graph, field)
                for value in graph.objects(subject, field.path)
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
    table = {
        "id": shape.identifier,
        "targetClass": str(shape.target_class),
        "targetClassLabel": compact_iri(shape.target_class, graph),
        "hierarchyEnabled": shape.hierarchy_enabled,
        "fields": fields,
        "rows": rows,
    }
    if shape.hierarchy_enabled and shape.hierarchy_path is not None:
        table["hierarchyPath"] = str(shape.hierarchy_path)
        table["hierarchy"] = hierarchy_payload(graph, subjects, shape.hierarchy_path)
    return table


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


def hierarchy_payload(
    graph: Graph, subjects: list[URIRef], hierarchy_path: URIRef
) -> dict:
    subject_set = set(subjects)
    parents_by_subject: dict[URIRef, list[URIRef]] = {}
    children_by_subject: dict[URIRef, list[URIRef]] = {
        subject: [] for subject in subjects
    }

    for subject in subjects:
        parents = sorted(
            (
                parent
                for parent in graph.objects(subject, hierarchy_path)
                if isinstance(parent, URIRef) and parent in subject_set
            ),
            key=lambda parent: preferred_label(graph, parent).casefold(),
        )
        parents_by_subject[subject] = parents
        for parent in parents:
            children_by_subject.setdefault(parent, []).append(subject)

    for children in children_by_subject.values():
        children.sort(
            key=lambda child: (preferred_label(graph, child).casefold(), str(child))
        )

    roots = [subject for subject in subjects if not parents_by_subject[subject]]
    if not roots:
        roots = subjects

    depth_cache: dict[URIRef, int] = {}
    nodes = {
        str(subject): {
            "id": str(subject),
            "curie": compact_iri(subject, graph),
            "label": preferred_label(graph, subject),
            "parents": [str(parent) for parent in parents_by_subject[subject]],
            "children": [str(child) for child in children_by_subject.get(subject, [])],
            "depth": hierarchy_depth(subject, parents_by_subject, depth_cache, set()),
        }
        for subject in subjects
    }

    return {
        "predicate": str(hierarchy_path),
        "roots": [str(root) for root in roots],
        "nodes": nodes,
    }


def hierarchy_depth(
    subject: URIRef,
    parents_by_subject: dict[URIRef, list[URIRef]],
    depth_cache: dict[URIRef, int],
    seen: set[URIRef],
) -> int:
    if subject in depth_cache:
        return depth_cache[subject]
    if subject in seen:
        return 0

    parents = parents_by_subject.get(subject, [])
    if not parents:
        depth_cache[subject] = 0
        return 0

    depth = 1 + min(
        hierarchy_depth(parent, parents_by_subject, depth_cache, seen | {subject})
        for parent in parents
    )
    depth_cache[subject] = depth
    return depth


def uri_subjects(subjects: Iterable) -> Iterable[URIRef]:
    for subject in subjects:
        if isinstance(subject, URIRef):
            yield subject


def preferred_label(graph: Graph, subject: URIRef) -> str:
    labels = [
        value
        for value in graph.objects(subject, RDFS.label)
        if isinstance(value, Literal)
    ]
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


def optional_bool_literal(value) -> bool | None:
    if isinstance(value, Literal):
        return bool(value.toPython())
    return None


def compact_iri(value, graph: Graph) -> str:
    if isinstance(value, URIRef):
        parsed = urlparse(str(value))
        if parsed.scheme == "file" and parsed.fragment:
            return f"#{urldefrag(str(value)).fragment}"
        try:
            normalized = graph.namespace_manager.normalizeUri(value)
            if normalized.startswith("<") and normalized.endswith(">"):
                return normalized[1:-1]
            return normalized
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
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_site_config(path: Path, payload: dict) -> None:
    write_json(path, payload)


if __name__ == "__main__":
    main()
