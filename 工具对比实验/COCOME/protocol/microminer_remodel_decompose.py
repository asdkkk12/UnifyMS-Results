#!/usr/bin/env python3
"""MicroMiner-style decomposition directly from a Remodel model.

The published MicroMiner implementation requires Java/KDM artifacts. This
adapter preserves its main signals for a .remodel input: static model
relations, lexical/semantic overlap, and fuzzy service membership.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
from compute_airms_metrics import parse_model, operation_info  # noqa: E402


def words(text: str) -> set[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return {x.lower() for x in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text)}


def sim(a: set[str], b: set[str]) -> float:
    return len(a & b) / math.sqrt(len(a) * len(b)) if a and b else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="AirMS")
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--membership-threshold", type=float, default=0.70)
    args = ap.parse_args()

    services, entities, contracts, actors, use_cases = parse_model(args.model)
    op_info = operation_info(services, entities, contracts)
    service_text = {}
    for service, ops in services.items():
        service_text[service] = words(service + " " + " ".join(ops))
    entity_text = {}
    for entity, data in entities.items():
        entity_text[entity] = words(entity + " " + " ".join(data["features"]) + " " + " ".join(data["refs"]))

    # Static relation score: an entity is related to a service when it occurs
    # in one of the service's contracts. Entity associations add a weaker
    # transitive signal, while lexical overlap supplies the semantic signal.
    referenced = {s: set() for s in services}
    for (s, op), data in op_info.items():
        referenced[s].update(data["entities"])
    entity_scores = {}
    for entity in entities:
        scores = {}
        for service in services:
            static = 1.0 if entity in referenced[service] else 0.0
            semantic = sim(entity_text[entity], service_text[service])
            scores[service] = static + 0.35 * semantic
        entity_scores[entity] = scores

    clusters = []
    memberships = {}
    for service in services:
        members = [f"{args.app}.service.{service}"]
        for entity, scores in entity_scores.items():
            best = max(scores.values()) if scores else 0.0
            score = scores[service]
            # Preserve fuzzy/overlapping membership: related entities can be
            # present in more than one service if they pass the relative bar.
            if score > 0 and score >= max(0.35, best * args.membership_threshold):
                members.append(f"{args.app}.domain.{entity}")
                memberships.setdefault(entity, []).append({"service": service, "score": round(score, 6)})
        clusters.append({"cluster": len(clusters), "members": members,
                         "service_names": [service],
                         "membership_scores": {e: s for e, s in entity_scores.items() if e in [x.rsplit('.', 1)[-1] for x in members[1:]]}})

    result = {
        "application": args.app,
        "method": "microminer-remodel-adapter",
        "is_official_microminer": False,
        "warning": "Adapted MicroMiner signals for .remodel; published implementation requires Java/KDM artifacts.",
        "model": str(args.model),
        "membership_threshold": args.membership_threshold,
        "clusters": clusters,
        "entity_memberships": memberships,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    for c in clusters:
        print(c["cluster"], c["service_names"], len(c["members"]) - 1, "entities")


if __name__ == "__main__":
    main()
