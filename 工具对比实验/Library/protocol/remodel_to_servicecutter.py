#!/usr/bin/env python3
"""Convert the remodel dialect used by this workspace to ServiceCutter JSON."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TOOLS = Path('/Users/yuanyaowu/Desktop/u/MonoEmbed-EMSE25-RP/tools')
sys.path.insert(0, str(TOOLS))
from compute_airms_metrics import parse_model, operation_info  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('model', type=Path)
    ap.add_argument('--out-dir', type=Path, required=True)
    args = ap.parse_args()
    services, entities, contracts, actors, use_cases = parse_model(args.model)
    # Ignore commented declarations/associations when collecting regex-based
    # relations too, matching parse_model's line-comment handling.
    text = '\n'.join(line.split('//', 1)[0] for line in
                     args.model.read_text(encoding='utf-8', errors='replace').splitlines())
    entity_names = set(entities)
    ops = operation_info(services, entities, contracts)
    related_services = {
        uc: service
        for uc in use_cases
        for service in re.findall(r'UC::' + re.escape(uc) + r'\([^\n]*?relatedService\(([A-Za-z_]\w*)\)', text)
    }
    entity_attrs = {
        name: sorted(data['features'] | {x.lower() for x in data['refs']}) or ['id']
        for name, data in entities.items()
    }

    # ServiceCutter requires an ERM with entity attributes (“nanoentities”).
    # The remodel grammar contains fields and association ends, so both are
    # emitted as attributes; aggregation is used for every association because
    # this is the only non-destructive relation in the importer.
    erd_entities = []
    for name, data in entities.items():
        erd_entities.append({'name': name, 'nanoentities': entity_attrs[name]})
    relations = []
    seen = set()
    for owner, body in re.findall(r'Entity\s+([A-Za-z_]\w*)(?:\s+extends\s+[A-Za-z_]\w*)?\s*\{(.*?)\n\s*\}', text, re.S):
        for target in re.findall(r':\s*([A-Z][A-Za-z0-9_]*)\s+\**!?\s*Association', body):
            if target in entity_names and (owner, target) not in seen:
                relations.append({'origin': owner, 'destination': target, 'type': 'AGGREGATION'})
                seen.add((owner, target))
    model = {'name': args.model.stem.upper(), 'entities': erd_entities, 'relations': relations}

    # ServiceCutter represents use cases through fields read/written.  The
    # remodel contracts are the strongest available source for this mapping.
    uses = []
    for uc in use_cases:
        matches = [v['entities'] for (service, op), v in ops.items() if op == uc]
        if not matches:
            service = related_services.get(uc)
            if service:
                matches = [v['entities'] for (owner, op), v in ops.items() if owner == service]
        if not matches:
            compact = re.sub(r'[^a-z0-9]', '', uc.lower())
            candidates = [s for s in services if compact in re.sub(r'(service|crud)', '', s.lower())]
            if candidates:
                matches = [v['entities'] for (owner, op), v in ops.items() if owner == candidates[0]]
        refs = sorted(set().union(*matches)) if matches else []
        if not refs and entity_attrs:
            # ServiceCutter cannot score a use case with no nanoentity. Keep a
            # deterministic sentinel association so the Engine can solve it.
            refs = [sorted(entity_attrs)[0]]
        uses.append({'name': uc, 'nanoentitiesRead': [f'{e}.{entity_attrs[e][0]}' for e in refs], 'nanoentitiesWritten': []})
    shared = []
    for actor, ucs in actors.items():
        refs = sorted({f'{e}.{entity_attrs[e][0]}' for uc in ucs for (s, op), v in ops.items() if op == uc for e in v['entities']})
        if refs:
            shared.append({'name': actor, 'nanoentities': refs})
    reps = {'useCases': uses, 'compatibilities': {}, 'sharedOwnerGroups': shared}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / 'servicecutter_model.json').write_text(json.dumps(model, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (args.out_dir / 'servicecutter_user_representations.json').write_text(json.dumps(reps, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest = {
        'source': str(args.model),
        'model': 'servicecutter_model.json',
        'user_representations': 'servicecutter_user_representations.json',
        'assumptions': [
            'remodel associations are emitted as ServiceCutter AGGREGATION relations',
            'use-case entity references are emitted against the first available attribute of each Entity',
            'actor groups are represented as sharedOwnerGroups',
            'include/extend relations are not represented by this adapter',
            'use cases with no inferable entity use the first entity as a deterministic ServiceCutter sentinel',
        ],
        'counts': {'entities': len(erd_entities), 'relations': len(relations), 'use_cases': len(uses), 'shared_owner_groups': len(shared)},
    }
    (args.out_dir / 'servicecutter_conversion_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__':
    main()
