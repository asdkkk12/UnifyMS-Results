#!/usr/bin/env python3
"""Materialize a visible MicroMiner-style AIRMS input directory."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MONO = REPO.parent / "MonoEmbed-EMSE25-RP" / "tools"
sys.path.insert(0, str(MONO))
from compute_airms_metrics import parse_model, operation_info  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=REPO / "AIRMS")
    ap.add_argument("--app", default="AIRMS")
    args = ap.parse_args()

    services, entities, contracts, actors, use_cases = parse_model(args.model)
    op_info = operation_info(services, entities, contracts)
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.model, args.output / args.model.name)

    service_files = []
    entity_files = []
    for service, ops in services.items():
        filename = f"{service}.java"
        service_files.append(filename)
        body = "\n".join(f"    public void {op}() {{}}" for op in ops)
        (args.output / filename).write_text(
            f"// Structural input generated from {args.model.name}; not recovered implementation code.\n"
            f"public class {service} {{\n{body}\n}}\n", encoding="utf-8")
    for entity, data in entities.items():
        filename = f"{entity}.java"
        entity_files.append(filename)
        body = "\n".join(f"    private {field};" for field in sorted(data["features"]))
        (args.output / filename).write_text(
            f"// Structural input generated from {args.model.name}; not recovered implementation code.\n"
            f"public class {entity} {{\n{body}\n}}\n", encoding="utf-8")

    (args.output / "application.txt").write_text("\n".join(service_files) + "\n", encoding="utf-8")
    (args.output / "entity.txt").write_text("\n".join(entity_files) + "\n", encoding="utf-8")
    (args.output / "utility.txt").write_text("", encoding="utf-8")

    edges = set()
    entity_names = set(entities)
    for (service, op), data in op_info.items():
        for entity in data["entities"]:
            edges.add((f"{service}.java", f"{entity}.java", 25, "service-entity-access"))
        for target_service, target_op in data["external_calls"]:
            edges.add((f"{service}.java", f"{target_service}.java", 5, "external-service-call"))
    for entity, data in entities.items():
        for target in data["refs"]:
            if target in entity_names:
                edges.add((f"{entity}.java", f"{target}.java", 100, "entity-association"))
    with (args.output / f"{args.app}_call_graph.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(sorted(edges))

    manifest = {
        "application": args.app,
        "source_model": str(args.model),
        "service_count": len(services),
        "entity_count": len(entities),
        "operation_count": sum(len(x) for x in services.values()),
        "files": {"application": "application.txt", "entity": "entity.txt", "utility": "utility.txt",
                  "call_graph": f"{args.app}_call_graph.csv"},
        "note": "Visible structural MicroMiner input generated from Remodel; Java files are stubs, not original source.",
    }
    (args.output / "conversion_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "README.md").write_text(
        f"# {args.app} MicroMiner input\n\n"
        f"Generated from `{args.model.name}`.\n\n"
        "`application.txt` lists Service stubs, `entity.txt` lists Entity stubs, "
        "`utility.txt` is reserved for utility classes, and the call graph CSV contains "
        "adapted static relation weights. The `.java` files are structural stubs.\n",
        encoding="utf-8")
    print(f"wrote {args.output}")
    print(f"services={len(services)} entities={len(entities)} operations={sum(len(x) for x in services.values())} edges={len(edges)}")


if __name__ == "__main__":
    main()
