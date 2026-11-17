#!/usr/bin/env python3
"""Bridge ServiceCutter's entity clusters to the remodel operation model."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

TOOLS = Path('/Users/yuanyaowu/Desktop/u/MonoEmbed-EMSE25-RP/tools')
sys.path.insert(0, str(TOOLS))
from compute_airms_metrics import parse_model  # noqa: E402

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', type=Path, required=True)
    ap.add_argument('--solver-result', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    services, entities, contracts, actors, use_cases = parse_model(args.model)
    result = json.loads(args.solver_result.read_text(encoding='utf-8'))
    clusters = result.get('services', [])
    responsibility = result.get('useCaseResponsibility', {})
    op_to_service = {op: service for (service, op) in contracts}
    # ServiceCutter reports responsibility by use case. Map those operation
    # names back to the declaring remodel service.
    op_clusters = {op: [] for op in op_to_service}
    for i, cluster in enumerate(clusters):
        for op in responsibility.get(cluster.get('name'), []):
            if op in op_to_service:
                op_clusters[op].append(i)
    # Operations without a use-case responsibility (CRUD/system operations)
    # cannot be recovered from ServiceCutter's native result. Put them in the
    # largest cluster, which is the documented conservative fallback.
    fallback = max(range(len(clusters)), key=lambda i: len(clusters[i].get('nanoentities', []))) if clusters else 0
    all_declared = set(services)
    assigned = {i: set() for i in range(len(clusters))}
    for service in all_declared:
        votes = {i: 0 for i in range(len(clusters))}
        for op, owner in op_to_service.items():
            if owner == service:
                for i in op_clusters[op]:
                    votes[i] += 1
        target = max(votes, key=votes.get) if votes and max(votes.values()) else fallback
        assigned[target].add(service)

    # A ServiceCutter entity may be split into nanoentities in multiple
    # clusters. For the requested entity-pair CMQ metric, assign that entity
    # to the cluster containing most of its nanoentities.
    entity_votes = {}
    for i, cluster in enumerate(clusters):
        for nano in cluster.get('nanoentities', []):
            entity_votes.setdefault(nano.split('.', 1)[0], {}).setdefault(i, 0)
            entity_votes[nano.split('.', 1)[0]][i] += 1
    entity_owner = {e: max(votes, key=votes.get) for e, votes in entity_votes.items()}
    out_clusters = []
    for i, cluster in enumerate(clusters):
        entity_names = sorted(e for e, owner in entity_owner.items() if owner == i)
        members = [f'servicecutter.domain.{e}' for e in entity_names if e in entities]
        members += [f'servicecutter.service.{s}' for s in sorted(assigned.get(i, set()))]
        out_clusters.append({'name': cluster.get('name', f'Service {i}'), 'members': members,
                             'servicecutter_nanoentities': cluster.get('nanoentities', [])})
    output = {
        'method': 'ServiceCutter',
        'is_official_servicecutter': True,
        'source_solver_result': str(args.solver_result),
        'mapping_assumptions': [
            'ServiceCutter entity/nanoentity clusters are retained as the decomposition.',
            'Use-case responsibilities are mapped to remodel services by operation name.',
            'Operations not present in ServiceCutter use-case responsibility are assigned to the largest cluster.',
        ],
        'clusters': out_clusters,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'clusters': len(out_clusters), 'fallback_cluster': fallback, 'assigned_services': {str(k): sorted(v) for k,v in assigned.items()}}, ensure_ascii=False))

if __name__ == '__main__':
    main()
