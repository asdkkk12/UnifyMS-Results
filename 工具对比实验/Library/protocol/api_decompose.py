#!/usr/bin/env python3
"""Bailian embeddings -> z-score scaling -> Affinity Propagation.

This is an API-encoder variant, not the paper's ME-llm2vec reproduction.
No automatic request retries: a timed-out request may already be billed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / ".local" / "embedding_api.json"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.7-text-embedding-flash"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def load_settings(config_path):
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    return {
        "api_key": os.getenv("DASHSCOPE_API_KEY") or config.get("api_key", ""),
        "base_url": os.getenv("EMBEDDING_BASE_URL") or config.get("base_url", DEFAULT_BASE_URL),
        "model": os.getenv("EMBEDDING_MODEL") or config.get("model", DEFAULT_MODEL),
    }


def validate_records(records):
    if not isinstance(records, list) or not records:
        raise ValueError("Input must be a non-empty JSON list.")
    names = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Each input record must be an object.")
        if not isinstance(record.get("content"), str) or not record["content"].strip():
            raise ValueError("Every record must have non-empty content; input was not sent.")
        if not isinstance(record.get("fullName"), str) or not record["fullName"]:
            raise ValueError("Every record must have fullName.")
        names.append(record["fullName"])
    if len(set(names)) != len(names):
        raise ValueError("Duplicate fullName values would make the partition ambiguous.")


def validate_vectors(data, count, dimensions):
    if not isinstance(data, list) or len(data) != count:
        raise ValueError("Embedding response count does not match input count.")
    if sorted(item.get("index", -1) for item in data) != list(range(count)):
        raise ValueError("Embedding response indices are missing or duplicated.")
    vectors = [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]
    for vector in vectors:
        if len(vector) != dimensions or any(
            isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v)
            for v in vector
        ):
            raise ValueError("Embedding dimensions or numeric values are invalid.")
    return vectors


def usage_counts(result):
    usage = result.get("usage", {})
    prompt = usage.get("prompt_tokens")
    total = usage.get("total_tokens")
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in (prompt, total)):
        raise ValueError("API response lacks valid usage.prompt_tokens / usage.total_tokens.")
    return prompt, total


def post_embeddings(base_url, api_key, payload, timeout):
    url = base_url.rstrip("/") + "/embeddings"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("API base URL must be HTTPS without embedded credentials.")
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
    )
    # Do not forward Authorization through redirects to another host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Avoid printing raw provider bodies, credentials or request source text.
        raise RuntimeError(f"Embedding API HTTP {exc.code}; check region, model, quota and endpoint.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise RuntimeError("Embedding request failed or response was unreadable; billing may be unknown.") from None


def generate_embeddings(texts, settings, dimensions, batch_size, cache_dir, refresh, timeout,
                        stats, checkpoint, requester=None):
    requester = requester or post_embeddings
    vectors = []
    for start in range(0, len(texts), batch_size):
        payload = {"model": settings["model"], "input": texts[start:start + batch_size],
                   "dimensions": dimensions, "encoding_format": "float"}
        identity = {"base_url": settings["base_url"].rstrip("/"), "payload": payload}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cache_path = cache_dir / (digest + ".json")
        if cache_path.exists() and not refresh:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            prompt, total = usage_counts(cached)
            batch_vectors = validate_vectors(cached["data"], len(payload["input"]), dimensions)
            stats["cache_hits"] += 1
            stats["cached_source_tokens"] += total
        else:
            if not settings["api_key"]:
                raise ValueError("No API key. Configure .local/embedding_api.json or DASHSCOPE_API_KEY.")
            begin = time.perf_counter()
            stats["api_requests"] += 1
            try:
                result = requester(settings["base_url"], settings["api_key"], payload, timeout)
            except Exception:
                stats["unaccounted_requests"] += 1
                raise
            finally:
                stats["api_seconds"] += time.perf_counter() - begin
            try:
                prompt, total = usage_counts(result)
            except Exception:
                stats["unaccounted_requests"] += 1
                raise
            # Count known usage even if returned vectors subsequently fail validation.
            stats["prompt_tokens"] += prompt
            stats["total_tokens"] += total
            stats["successful_api_responses"] += 1
            checkpoint()
            batch_vectors = validate_vectors(result.get("data"), len(payload["input"]), dimensions)
            write_json(cache_path, {"data": result["data"], "usage": result["usage"]})
        vectors.extend(batch_vectors)
        checkpoint()
    return vectors


def cluster_vectors(vectors, damping):
    import numpy as np
    from sklearn.cluster import AffinityPropagation
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.preprocessing import StandardScaler

    begin = time.perf_counter()
    scaled = StandardScaler().fit_transform(np.asarray(vectors, dtype=float))
    scaling_seconds = time.perf_counter() - begin
    begin = time.perf_counter()
    if len(vectors) == 1:
        return [0], scaling_seconds, time.perf_counter() - begin
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        model = AffinityPropagation(damping=damping, random_state=0)
        labels = model.fit_predict(scaled)
    if any(issubclass(w.category, ConvergenceWarning) for w in caught) or (labels < 0).any():
        raise ValueError("Affinity Propagation did not converge; adjust damping or inspect embeddings.")
    return labels.tolist(), scaling_seconds, time.perf_counter() - begin


def main(argv=None):
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default="AIRMS")
    parser.add_argument("--input-dir", type=Path, help="Directory containing typeData.json, or JSON file")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--base-url", help="Override the compatible API base URL for your workspace/region")
    parser.add_argument("--model")
    parser.add_argument("--dimensions", type=int, choices=[256, 512, 768, 1024], default=1024)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--damping", type=float, default=0.8)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--refresh", action="store_true", help="Bypass cache; requests may incur new charges")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and dependencies without sending requests")
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 10 or not 0.5 <= args.damping < 1 or args.timeout <= 0:
        parser.error("batch-size must be 1..10, damping 0.5..<1, timeout >0")
    source = args.input_dir or ROOT / "data" / args.app
    source = source / "typeData.json" if source.is_dir() else source
    output = args.output or ROOT / "data" / args.app / "api_decomposition.json"
    stats_path = output.with_suffix(".stats.json")
    if output.resolve() == source.resolve() or stats_path.resolve() == source.resolve():
        parser.error("Output paths must not overwrite input.")
    settings = load_settings(args.config)
    settings["base_url"] = args.base_url or settings["base_url"]
    settings["model"] = args.model or settings["model"]
    stats = {
        "status": "running", "model": settings["model"], "dimensions": args.dimensions,
        "api_requests": 0, "successful_api_responses": 0, "unaccounted_requests": 0,
        "prompt_tokens": 0, "total_tokens": 0, "cache_hits": 0, "cached_source_tokens": 0,
        "api_seconds": 0.0, "embedding_seconds": 0.0,
        "scaling_seconds": 0.0, "clustering_seconds": 0.0,
        "timing_scope": "From main entry through result write; excludes interpreter startup, imports before main and final stats serialization.",
        "token_scope": "Current run API usage only; cached_source_tokens are historical and excluded from total_tokens.",
    }

    def checkpoint():
        stats["total_seconds"] = time.perf_counter() - started
        stats["usage_complete"] = stats["unaccounted_requests"] == 0
        write_json(stats_path, stats)

    try:
        records = json.loads(source.read_text(encoding="utf-8"))
        validate_records(records)
        # Fail before paid requests if scientific dependencies are missing.
        import numpy  # noqa: F401
        import sklearn  # noqa: F401
        stats["input_records"] = len(records)
        if args.dry_run:
            print(json.dumps({"mode": "dry-run", "records": len(records), "model": settings["model"],
                              "key_configured": bool(settings["api_key"]), "dependencies": "available",
                              "output": str(output)}, ensure_ascii=False))
            return 0
        begin = time.perf_counter()
        vectors = generate_embeddings(
            [r["content"] for r in records], settings, args.dimensions, args.batch_size,
            ROOT / "data" / "api_embeddings", args.refresh, args.timeout, stats, checkpoint,
        )
        stats["embedding_seconds"] = time.perf_counter() - begin
        labels, stats["scaling_seconds"], stats["clustering_seconds"] = cluster_vectors(vectors, args.damping)
        clusters = []
        for label in sorted(set(labels)):
            group = [r for r, value in zip(records, labels) if value == label]
            clusters.append({"cluster": int(label), "members": [r["fullName"] for r in group],
                             "service_names": [r.get("serviceName", "") for r in group]})
        result = {"application": args.app, "method": "bailian-embedding-standardscaler-affinity",
                  "is_monoembed": False, "is_monoembed_variant": True,
                  "warning": "API encoder variant; not the paper's ME-llm2vec-340K reproduction.",
                  "model": settings["model"], "dimensions": args.dimensions, "input": str(source),
                  "damping": args.damping, "random_state": 0,
                  "statistics_file": str(stats_path), "clusters": clusters}
        write_json(output, result)
        stats["status"] = "completed"
        stats["clusters"] = len(clusters)
        checkpoint()
        print(json.dumps({"output": str(output), "statistics": str(stats_path),
                          "total_tokens": stats["total_tokens"], "total_seconds": stats["total_seconds"],
                          "cache_hits": stats["cache_hits"]}, ensure_ascii=False))
        return 0
    except Exception as exc:
        stats["status"] = "failed"
        stats["error_type"] = type(exc).__name__
        checkpoint()
        # Only our controlled error strings are printed; provider exceptions can contain payloads.
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError, ModuleNotFoundError)) else type(exc).__name__
        if settings["api_key"]:
            message = message.replace(settings["api_key"], "[REDACTED]")
        print(f"Failed: {message}. Statistics: {stats_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
