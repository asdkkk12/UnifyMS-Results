#!/usr/bin/env python3
"""Convert a RapidOOD .remodel model into MonoEmbed analysis input.

The remodel format describes services/entities, rather than Java source.  The
converter therefore emits source-like, self-contained class/method snippets
for the model elements.  This preserves the model's declared vocabulary and
boundaries without claiming to reconstruct an implementation.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from compute_airms_metrics import code as source_code


SERVICE_RE = re.compile(r"^\s*Service\s+([A-Za-z_]\w*)\s*\{")
ENTITY_RE = re.compile(r"^\s*Entity\s+([A-Za-z_]\w*)(?:\s+extends\s+([A-Za-z_]\w*))?\s*\{")
OP_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*\(([^)]*)\)")


def strip_comment(line: str) -> str:
    return source_code(line)


def matching_block(lines: list[str], start: int) -> tuple[int, list[str]]:
    depth = 0
    body: list[str] = []
    for i in range(start, len(lines)):
        code = strip_comment(lines[i])
        depth += code.count("{") - code.count("}")
        if i > start:
            body.append(lines[i])
        if i > start and depth == 0:
            return i, body[:-1]
    raise ValueError(f"Unclosed block at line {start + 1}")


def parse_services(lines: list[str]) -> list[dict]:
    result = []
    i = 0
    while i < len(lines):
        match = SERVICE_RE.match(strip_comment(lines[i]))
        if not match:
            i += 1
            continue
        end, body = matching_block(lines, i)
        operations = []
        in_ops = False
        for line in body:
            code = strip_comment(line).strip()
            if code == "[Operation]":
                in_ops = True
                continue
            if not in_ops:
                continue
            op = OP_RE.match(code)
            if op:
                args = [x.strip() for x in op.group(2).split(",") if x.strip()]
                operations.append({"name": op.group(1), "args": args})
        result.append({"name": match.group(1), "operations": operations})
        i = end + 1
    return result


def parse_entities(lines: list[str]) -> list[dict]:
    result = []
    i = 0
    while i < len(lines):
        match = ENTITY_RE.match(strip_comment(lines[i]))
        if not match:
            i += 1
            continue
        end, body = matching_block(lines, i)
        fields = []
        for line in body:
            code = strip_comment(line).strip()
            field = re.match(r"^([A-Za-z_]\w*)\s*:\s*([A-Za-z_]\w*)(?:\s*[*!])?", code)
            if field:
                fields.append((field.group(1), field.group(2)))
        result.append({"name": match.group(1), "fields": fields, "parent": match.group(2)})
        i = end + 1
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("remodel", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--app", default="airms")
    args = ap.parse_args()

    text = args.remodel.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    services = parse_services(lines)
    entities = parse_entities(lines)
    if not services and not entities:
        raise SystemExit("No Service or Entity blocks found")

    type_data = []
    method_data = []

    for service in services:
        name = service["name"]
        ops = service["operations"]
        body = "\n".join(f"    public void {o['name']}({', '.join('Object ' + a for a in o['args'])}) {{}}" for o in ops)
        content = (f"// Derived from RapidOOD .remodel\n"
                   f"// service {name}: " + ", ".join(o['name'] for o in ops) +
                   f"\npublic class {name} {{\n{body}\n}}")
        type_data.append({
            "isInterface": False, "isAnnotation": False, "simpleName": name,
            "fullName": f"{args.app}.service.{name}", "serviceName": name,
            "content": content,
        })
        for o in ops:
            signature = f"{o['name']}({', '.join('Object ' + a for a in o['args'])})"
            method_data.append({
                "simpleName": o["name"], "fullName": f"{args.app}.service.{name}.{signature}",
                "serviceName": name, "content": f"class {name} {{ public void {signature} {{}} }}",
            })

    for entity in entities:
        name = entity["name"]
        fields = entity["fields"]
        body = "\n".join(f"    private {typ} {field};" for field, typ in fields)
        parent = ' extends ' + entity['parent'] if entity.get('parent') else ''
        content = f"// Derived from RapidOOD .remodel\npublic class {name}{parent} {{\n{body}\n}}"
        type_data.append({
            "isInterface": False, "isAnnotation": False, "simpleName": name,
            "fullName": f"{args.app}.domain.{name}", "serviceName": "domain-model",
            "content": content,
        })

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "typeData.json").write_text(json.dumps(type_data, ensure_ascii=False, indent=2) + "\n")
    (args.output / "methodData.json").write_text(json.dumps(method_data, ensure_ascii=False, indent=2) + "\n")
    manifest = {"application": args.app, "source": str(args.remodel), "services": services, "entities": entities,
                "note": "Synthetic source-like content derived from .remodel; not recovered implementation code."}
    (args.output / "conversion_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"services={len(services)} entities={len(entities)} operations={len(method_data)}")
    print(f"wrote {args.output / 'typeData.json'}")
    print(f"wrote {args.output / 'methodData.json'}")


if __name__ == "__main__":
    main()
