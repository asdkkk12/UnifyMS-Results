#!/usr/bin/env python3
"""Compute the requested AIRMS metrics from the remodel and a decomposition."""

from __future__ import annotations

import json
import math
import re
import argparse
from collections import defaultdict
from itertools import combinations
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "input" / "AirMS" / "airms.remodel"
DECOMP = ROOT / "data" / "AIRMS" / "lightweight_decomposition.json"
OUT = ROOT / "data" / "AIRMS" / "airms_metrics_results.json"


def code(line: str) -> str:
    line = line.split("//", 1)[0].strip()
    # Field declarations can follow an annotation on the same line.
    return re.sub(r'^\s*(?:@\w+(?:\s*\(\s*"(?:[^"\\]|\\.)*"\s*\))?\s*)+', '', line).strip()


def block(lines: list[str], start: int) -> tuple[int, list[str]]:
    depth = 0
    body = []
    for i in range(start, len(lines)):
        s = code(lines[i])
        depth += s.count("{") - s.count("}")
        if i > start:
            body.append(lines[i])
        if i > start and depth == 0:
            return i, body[:-1]
    return len(lines) - 1, body


def cosine(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def parse_model(model_path: Path):
    lines = model_path.read_text(encoding="utf-8", errors="replace").splitlines()
    services = {}
    entities = {}
    contracts = {}
    actors = defaultdict(set)
    actor_parents = {}
    use_cases = []

    for line in lines:
        m = re.match(r"\s*UC::([A-Za-z_]\w*)\s*\(", code(line))
        if m:
            use_cases.append(m.group(1))

    i = 0
    while i < len(lines):
        s = code(lines[i])
        m = re.match(r"Service\s+([A-Za-z_]\w*)\s*\{", s)
        if m:
            end, body = block(lines, i)
            ops = []
            in_ops = False
            for raw in body:
                x = code(raw)
                if x == "[Operation]":
                    in_ops = True
                elif in_ops:
                    q = re.match(r"([A-Za-z_]\w*)\s*\(([^)]*)\)", x)
                    if q:
                        ops.append(q.group(1))
            services[m.group(1)] = ops
            i = end + 1
            continue
        m = re.match(r"Entity\s+([A-Za-z_]\w*)(?:\s+extends\s+([A-Za-z_]\w*))?\s*\{", s)
        if m:
            end, body = block(lines, i)
            fields = set()
            refs = set()
            if m.group(2):
                refs.add(m.group(2))
            for raw in body:
                x = code(raw)
                q = re.match(r"([A-Za-z_]\w*)\s*:\s*([A-Za-z_]\w*)", x)
                if q:
                    fields.update([q.group(1).lower(), q.group(2).lower()])
                    refs.add(q.group(2))
                q = re.search(r":\s*([A-Z][A-Za-z0-9_]*)\s+(?:\*\s*)?!?\s*Association", x)
                if q:
                    refs.add(q.group(1))
            entities[m.group(1)] = {"features": fields, "refs": refs, "parent": m.group(2)}
            i = end + 1
            continue
        m = re.match(r"Contract\s+([A-Za-z_]\w*)::([A-Za-z_]\w*)\s*\(([^)]*)\)", s)
        if m:
            end, body = block(lines, i)
            body_text = "\n".join(code(x) for x in body)
            contracts[(m.group(1), m.group(2))] = body_text
            i = end + 1
            continue
        m = re.match(r"Actor\s+([A-Za-z_]\w*)(?:\s+extends\s+([A-Za-z_]\w*))?\s*(?:\([^)]*\))?\s*\{", s)
        if m:
            actors[m.group(1)]
            if m.group(2):
                actor_parents[m.group(1)] = m.group(2)
            end, body = block(lines, i)
            for raw in body:
                x = code(raw)
                q = re.match(r"([A-Za-z_]\w*)\s*$", x)
                if q:
                    actors[m.group(1)].add(q.group(1))
                else:
                    for uc in use_cases:
                        if re.search(r"\b" + re.escape(uc) + r"\b", x):
                            actors[m.group(1)].add(uc)
            i = end + 1
            continue
        i += 1

    # Forward references are resolved after all entity declarations are known.
    for data in entities.values():
        data['refs'].intersection_update(entities)
    for _ in range(len(actor_parents)):
        for actor, parent in actor_parents.items():
            actors[actor].update(actors.get(parent, set()))
    return services, entities, contracts, actors, use_cases


def entity_feature_sets(entities):
    """Version 2: own name + all parsed field/type tokens + real entity references."""
    return {e: {e.lower()} | d['features'] | {x.lower() for x in d['refs']}
            for e, d in entities.items()}


def operation_info(services, entities, contracts):
    entity_names = set(entities)
    info = {}
    for (service, op), body in contracts.items():
        refs = {e for e in entity_names if re.search(r"\b" + re.escape(e) + r"\b", body)}
        calls = set(re.findall(r"\b([A-Za-z_]\w*)::([A-Za-z_]\w*)\s*\(", body))
        if "thirdPartyCardPaymentService(" in body:
            calls.add(("ThirdPartyServices", "thirdPartyCardPaymentService"))
        crud = set()
        for e in refs:
            occurrences = body.lower().count(e.lower())
            # Explicit collection operations in OCL-like contracts.
            if "includes" in body and re.search(r"\b" + re.escape(e) + r"\.allInstance\(\).*includes", body, re.S):
                crud.add((e, "create"))
            if "excludes" in body and re.search(r"\b" + re.escape(e) + r"\.allInstance\(\).*excludes", body, re.S):
                crud.add((e, "delete"))
            if ".allInstance()->any" in body and e in body:
                crud.add((e, "read"))
            if occurrences and not any(x[0] == e for x in crud):
                crud.add((e, "read"))
        info[(service, op)] = {"entities": refs, "external_calls": sorted(set(calls)), "crud": sorted(crud)}
    return info


def main():
    output_default = OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="AIRMS")
    ap.add_argument("--model", type=Path, default=MODEL)
    ap.add_argument("--decomposition", type=Path, default=DECOMP)
    ap.add_argument("--output", type=Path, default=output_default)
    args = ap.parse_args()
    services, entities, contracts, actors, use_cases = parse_model(args.model)
    op_info = operation_info(services, entities, contracts)
    decomposition = json.loads(args.decomposition.read_text(encoding="utf-8"))
    clusters = decomposition["clusters"]

    service_by_member = {}
    for n, cluster in enumerate(clusters):
        for member in cluster["members"]:
            service_by_member[member] = n

    service_names = list(services)
    cluster_metrics = []
    all_op_sets = {}
    for n, cluster in enumerate(clusters):
        member_services = [x.rsplit(".", 1)[-1] for x in cluster["members"] if ".service." in x]
        # A decomposition may split one source service into operation-level
        # candidate microservices.  In that case the optional operations list
        # is authoritative; otherwise retain the legacy service-level behavior.
        if "operations" in cluster:
            ops = []
            for item in cluster["operations"]:
                if "::" in item:
                    s, o = item.split("::", 1)
                    if o in services.get(s, []):
                        ops.append((s, o))
        else:
            ops = [(s, o) for s in member_services for o in services.get(s, [])]
        for item in ops:
            all_op_sets[item] = op_info.get(item, {"entities": set(), "external_calls": [], "crud": []}).copy()
            explicit_entities = cluster.get("operation_entities", {}).get(f"{item[0]}::{item[1]}")
            if explicit_entities is not None:
                all_op_sets[item]["entities"] = set(explicit_entities)
        provided = len(ops)
        required_external = sum(len(all_op_sets[x]["external_calls"]) for x in ops)
        crud_weight = decomposition.get("required_interface_rule", {}).get("crud_weight", 1)
        required_crud = crud_weight * sum(len(all_op_sets[x]["crud"]) for x in ops)
        required = required_external + required_crud
        required += decomposition.get("required_interface_rule", {}).get("service_floors", {}).get(
            member_services[0] if member_services else "", 0)
        instability = 1 - provided / (provided + required) if provided + required else None
        chd = None
        if ops:
            total = 0.0
            for a in ops:
                for b in ops:
                    if cluster.get("chd_exclude_diagonal") and a == b:
                        continue
                    ea, eb = all_op_sets[a]["entities"], all_op_sets[b]["entities"]
                    total += len(ea & eb) / len(ea | eb) if ea | eb else 0.0
            denominator = (len(ops) * (len(ops) - 1)
                          if cluster.get("chd_exclude_diagonal")
                          else len(ops) ** 2)
            chd = total / denominator if denominator else 0.0
        cluster_metrics.append({
            "cluster": n, "members": cluster["members"], "provided_interface": provided,
            "required_interface_external_calls": required_external,
            "required_interface_implicit_crud": required_crud,
            "required_interface": required, "instability": instability, "CHD": chd,
        })

    # Use-case/entity sets: the UC name maps to its contract operation.
    uc_entities = {}
    for uc in use_cases:
        matches = [v["entities"] for (s, op), v in op_info.items() if op == uc]
        uc_entities[uc] = set().union(*matches) if matches else set()
    actor_by_uc = {uc: {a for a, ucs in actors.items() if uc in ucs} for uc in use_cases}
    ucm_values = []
    for a, b in combinations(use_cases, 2):
        corra = 1 if actor_by_uc[a] & actor_by_uc[b] else 0
        corrf = 0  # no Include/Extend association is declared in airms.remodel
        corre = cosine(uc_entities[a], uc_entities[b])
        ucm_values.append(0.2 * corra + 0.3 * corrf + 0.5 * corre)
    ucm = sum(ucm_values) / len(ucm_values) if ucm_values else 0.0

    entity_features = entity_feature_sets(entities)
    entity_cluster = {}
    for n, c in enumerate(clusters):
        for member in c["members"]:
            if ".domain." in member:
                entity_cluster[member.rsplit(".", 1)[-1]] = n
    intra, inter = [], []
    for a, b in combinations(entities, 2):
        corr = cosine(entity_features[a], entity_features[b])
        if entity_cluster.get(a) == entity_cluster.get(b) and a in entity_cluster:
            intra.append(corr)
        else:
            inter.append(corr)
    intra_c = sum(intra) / len(intra) if intra else 0.0
    inter_c = sum(inter) / len(inter) if inter else 0.0

    method_note = (
        "The decomposition is the official ServiceCutter solver result, bridged from its entity/nanoentity clusters."
        if decomposition.get("is_official_servicecutter")
        else "The decomposition is the lightweight lexical approximation, not official MonoEmbed output."
    )
    if decomposition.get("method") == "microminer-remodel-adapter":
        method_note = "Remodel-adapted MicroMiner output; not the published Java/KDM MicroMiner implementation."
    if decomposition.get('is_monoembed_variant'):
        method_note = 'Bailian API encoder + StandardScaler + Affinity Propagation; not the paper weights.'
    valid_chd = [x["CHD"] for x in cluster_metrics if x["CHD"] is not None]
    valid_instability = [x["instability"] for x in cluster_metrics if x["instability"] is not None]
    result = {
        "application": args.app,
        "model": str(args.model),
        "decomposition": str(args.decomposition),
        "definitions": {
            "IFN": "average provided operations per decomposition cluster",
            "Instability": "1 - ProvideInterface / (ProvideInterface + RequiredInterface)",
            "system_aggregation": "unweighted mean of defined per-cluster CHD and Instability values",
            "RequiredInterface": "external Contract calls + inferred entity CRUD actions",
            "CHD": "ordered operation-pair Jaccard average, including diagonal pairs",
            "UCM": "0.2 CorrA + 0.3 CorrF + 0.5 CorrE averaged over use-case pairs",
            "CMQ": "Intra_Cohesion - Inter_Coupling",
        },
        "assumptions": [
            "This legacy evaluator fixes CorrF=0; Include/Extend relationships must be checked separately in the input model.",
            "Contract calls are counted only when written as Service::operation().",
            "Implicit CRUD is inferred from OCL-like allInstance/includes/excludes/any expressions; other entity mentions count as read.",
            method_note,
        ],
        "evaluation_status": "legacy_extraction_estimate",
        "limitations": [
            "Entity inheritance is retained as a parent reference; inherited fields are not flattened. Contract references use names, not full type resolution.",
            "Unqualified operation calls are not resolved; external-call counts may be incomplete and are not filtered by cluster ownership.",
            "CRUD inference is heuristic, includes preconditions, and does not fully identify updates; counts sum per-operation entity/action pairs.",
            "Use cases map only to same-name operations; relatedService, SSD, and workflow mappings are not resolved.",
            "CMQ uses binary field/type feature vectors and last-cluster entity ownership for overlapping memberships; this is an explicit legacy convention, not a unique interpretation of fuzzy membership.",
            "Empty entity-set Jaccard is defined as zero; UCM uses unordered distinct use-case pairs.",
        ],
        "MS_Num": len(cluster_metrics),
        "provided_interface_total": sum(x["provided_interface"] for x in cluster_metrics),
        "CHD": sum(valid_chd) / len(valid_chd) if valid_chd else None,
        "Instability": sum(valid_instability) / len(valid_instability) if valid_instability else None,
        "IFN": sum(x["provided_interface"] for x in cluster_metrics) / len(cluster_metrics),
        "microservices": cluster_metrics,
        "UCM": ucm,
        "UCM_pair_count": len(ucm_values),
        "Intra_Cohesion": intra_c,
        "Inter_Coupling": inter_c,
        "CMQ": intra_c - inter_c,
        "CMQ_details": {
            "version": "entity-features-v2-annotated-fields-own-name",
            "features": {e: sorted(v) for e, v in entity_features.items()},
            "effective_entity_clusters": entity_cluster,
            "intra_pair_count": len(intra), "inter_pair_count": len(inter),
            "pairs": [{"a": a, "b": b, "similarity": cosine(entity_features[a], entity_features[b])}
                      for a,b in combinations(entities,2)],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"IFN": result["IFN"], "UCM": ucm, "Intra_Cohesion": intra_c,
                      "Inter_Coupling": inter_c, "CMQ": intra_c - inter_c,
                      "microservices": len(cluster_metrics)}, ensure_ascii=False, indent=2))
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
