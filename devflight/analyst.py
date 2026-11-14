"""Deterministic analyst: comparable evidence, explicit promotion gates, audit trail."""
import json
import math
import statistics
from collections import defaultdict
from .core import Trace, atomic_json, file_lock

def percentile(values, p):
    return sorted(values)[max(0, math.ceil(len(values)*p)-1)]

def metrics(rows):
    return {"runs": len(rows), "success_rate": statistics.mean(r["success"] for r in rows),
        "accuracy": statistics.mean(r.get("accuracy", r["success"]) for r in rows),
        "p50_seconds": statistics.median(r["seconds"] for r in rows),
        "p95_seconds": percentile([r["seconds"] for r in rows], .95),
        "median_tokens": statistics.median(r["tokens"] for r in rows),
        "tool_errors": sum(r.get("tool_errors", 0) for r in rows),
        "cost": sum(r.get("cost", 0) for r in rows),
        "no_reveal": all(r.get("no_reveal") is True for r in rows)}

def analyze(queue, events, kind, champion="baseline", sql="local queue (explicit offline mode)", policy=False):
    trace = Trace(queue, agent="devflight-analyst", kind=kind)
    groups = defaultdict(dict)
    for e in {e["event_id"]: e for e in events}.values():
        if e["event_type"] != "eval.grade" or e["task"]["kind"] != kind:
            continue
        d = e["data"]
        if not all(k in d for k in ("recipe", "dataset", "split", "seconds", "tokens", "success", "recipe_config")):
            continue
        if not isinstance(d["success"], bool) or any(not isinstance(d[k], (int,float)) or not math.isfinite(d[k]) or d[k] < 0 for k in ("seconds", "tokens")):
            continue
        if policy and (not isinstance(d.get("accuracy"), (int, float)) or not 0 <= d["accuracy"] <= 1 or not isinstance(d.get("no_reveal"), bool)):
            continue
        if not isinstance(d["recipe_config"], dict) or any(key in d["recipe_config"] for key in ("name", "version")):
            continue
        # Separate recipe versions and matching evaluation cohorts; never count repeated events as runs.
        key = (d["recipe"], d["dataset"], d["split"], d.get("suite_version", "1"), json.dumps(d["recipe_config"], sort_keys=True))
        groups[key][e["run_id"]] = (e, d)
    with file_lock(queue.home / "recipes.lock"):
        path = queue.home / "recipes.json"
        recipes = json.loads(path.read_text()) if path.exists() else {}
        champion = recipes.get(kind, {}).get("name", champion)
        candidates = []
        for key, runs in groups.items():
            name, dataset, split, suite, config = key
            if name == champion or len(runs) < 3:
                continue
            bases = [r for k,r in groups.items() if k[0] == champion and k[1:4] == key[1:4] and len(r) >= 3]
            if len(bases) != 1:
                continue
            base = bases[0]
            current, proposed = metrics([d for _,d in base.values()]), metrics([d for _,d in runs.values()])
            improve = proposed["success_rate"] > current["success_rate"] or (
                proposed["success_rate"] == current["success_rate"] and proposed["p50_seconds"] < current["p50_seconds"] and proposed["median_tokens"] < current["median_tokens"])
            passed = improve
            if policy:
                passed = passed and split == "validation" and proposed["accuracy"] >= current["accuracy"] and proposed["no_reveal"] and proposed["p95_seconds"] <= current["p95_seconds"] * 1.05
            evidence = {"champion": champion, "candidate": name, "dataset": dataset, "split": split,
                "suite_version": suite, "sql": sql, "metrics": proposed, "previous_metrics": current,
                "evidence_event_ids": [e["event_id"] for e,d in list(base.values()) + list(runs.values())],
                "recipe": json.loads(config), "gates_passed": passed, "policy": policy}
            trace.emit("decision.candidate", evidence)
            if passed:
                candidates.append(evidence)
        if not candidates:
            return {"promoted": False, "reason": "No candidate passes comparable-run gates", "champion": champion}
        best = sorted(candidates, key=lambda e: (-e["metrics"]["success_rate"], e["metrics"]["p50_seconds"], e["metrics"]["median_tokens"], e["candidate"]))[0]
        event = trace.emit("decision.promoted", best)
        recipes[kind] = {"name": best["candidate"], "version": event["event_id"], **best["recipe"]}
        atomic_json(path, recipes)
        if policy:
            atomic_json(queue.home / "policy-pack.json", {"version": event["event_id"], "recipe": recipes[kind], "evidence": best})
        return {"promoted": True, **best}
