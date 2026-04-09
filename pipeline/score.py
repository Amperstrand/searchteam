#!/usr/bin/env python3
"""
Venue scoring pipeline for conference venue selection.

Usage:
    python3 score.py                    # Score all venues in venues/
    python3 score.py --venue vulkan     # Score a single venue
    python3 score.py --reweight         # Show what-if weight adjustments

Input:
    venues/requirements.yaml   - Criteria definitions with weights/thresholds
    venues/*.yaml              - Individual venue data files (not requirements.yaml)

Output:
    Scores printed to stdout. Re-run anytime criteria or venue data changes.
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

ORDINAL_SCORES = {"poor": 0, "fair": 1, "good": 2, "excellent": 3}
ORDINAL_LABELS = {0: "poor", 1: "fair", 2: "good", 3: "excellent"}


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def resolve_venue_data(raw: dict) -> dict:
    if "data" in raw and isinstance(raw["data"], dict):
        return {**raw, **raw["data"]}
    return raw


def check_must_haves(venue_data: dict, criteria: list[dict]) -> list[dict]:
    failures = []
    for c in criteria:
        if c["requirement"] != "must":
            continue
        cid = c["id"]
        val = venue_data.get(cid)
        threshold = c["threshold"]

        if val is None:
            failures.append({"id": cid, "label": c["label"], "reason": "no data"})
            continue

        if isinstance(threshold, bool):
            if val is not True:
                failures.append({"id": cid, "label": c["label"], "reason": f"got {val}"})
        elif isinstance(threshold, (int, float)):
            if isinstance(val, (int, float)) and val < threshold:
                failures.append({
                    "id": cid, "label": c["label"],
                    "reason": f"{val} < {threshold} {c.get('unit', '')}",
                })
    return failures


def score_criterion(c: dict, val) -> tuple[float, str]:
    cid = c["id"]
    ctype = c.get("type")
    threshold = c.get("threshold")

    if val is None:
        return 0.0, "no data"

    if ctype == "boolean":
        return (1.0, "yes") if val else (0.0, "no")

    if ctype == "ordinal":
        if isinstance(val, str) and val.lower() in ORDINAL_SCORES:
            score = ORDINAL_SCORES[val.lower()] / 3.0
            return score, val
        if isinstance(val, (int, float)):
            score = min(val / 3.0, 1.0)
            return score, ORDINAL_LABELS.get(val, str(val))
        return 0.0, f"unknown ordinal: {val}"

    if isinstance(val, (int, float)) and isinstance(threshold, (int, float)):
        if threshold > 0:
            if val <= threshold:
                return 1.0, f"{val} {c.get('unit', '')}"
            ratio = threshold / val
            return max(0.0, ratio), f"{val} {c.get('unit', '')} (threshold: {threshold})"
        return 0.5, f"{val} {c.get('unit', '')} (no threshold)"

    return 0.5, str(val)


def score_venue(venue_data: dict, criteria: list[dict]) -> dict:
    must_failures = check_must_haves(venue_data, criteria)
    if must_failures:
        return {
            "name": venue_data.get("name", "unknown"),
            "slug": venue_data.get("slug", "unknown"),
            "status": "DISQUALIFIED",
            "must_failures": must_failures,
            "total_score": 0,
            "max_score": 0,
            "pct": 0,
            "categories": {},
        }

    categories: dict[str, dict] = {}
    total_score = 0.0
    total_weight = 0

    for c in criteria:
        if c["requirement"] == "must":
            continue

        cat = c["category"]
        val = venue_data.get(c["id"])
        raw, detail = score_criterion(c, val)
        weight = c.get("weight", 1)
        weighted = raw * weight
        total_score += weighted
        total_weight += weight

        if cat not in categories:
            categories[cat] = {"score": 0, "max": 0, "items": []}
        categories[cat]["score"] += weighted
        categories[cat]["max"] += weight
        categories[cat]["items"].append({
            "id": c["id"],
            "label": c["label"],
            "weight": weight,
            "raw": raw,
            "weighted": weighted,
            "detail": detail,
        })

    pct = (total_score / total_weight * 100) if total_weight > 0 else 0
    return {
        "name": venue_data.get("name", "unknown"),
        "slug": venue_data.get("slug", "unknown"),
        "status": venue_data.get("status", "unknown"),
        "total_score": total_score,
        "max_score": total_weight,
        "pct": round(pct, 1),
        "categories": categories,
    }


def print_scores(result: dict):
    status_marker = {"DISQUALIFIED": "✖", "current": "●", "rejected": "✗", "considered": "◐", "candidate": "○"}.get(result["status"], "?")
    print(f"\n{status_marker} {result['name']}  [{result['slug'].upper()}]  — {result['status']}")

    if result["status"] == "DISQUALIFIED":
        for f in result["must_failures"]:
            print(f"  ✖ BLOCKED: {f['label']} ({f['reason']})")
        return

    print(f"  Score: {result['total_score']:.1f} / {result['max_score']}  ({result['pct']}%)\n")

    for cat_name, cat in result["categories"].items():
        cat_pct = (cat["score"] / cat["max"] * 100) if cat["max"] > 0 else 0
        bar_len = 20
        filled = int(bar_len * cat_pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"  {cat_name:14s} [{bar}] {cat_pct:5.1f}%")
        for item in cat["items"]:
            marker = "✓" if item["raw"] >= 0.7 else ("~" if item["raw"] >= 0.3 else "✗")
            print(f"    {marker} {item['label']:42s} w{item['weight']:2d}  {item['detail']}")


def main():
    parser = argparse.ArgumentParser(description="Score venues against criteria")
    parser.add_argument("--venue", help="Score a single venue by slug")
    parser.add_argument("--requirements", default=None, help="Path to requirements.yaml")
    parser.add_argument("--venues-dir", default=None, help="Path to venues directory")
    parser.add_argument("--json", action="store_true", help="Output results as JSON instead of text")
    args = parser.parse_args()

    base = Path(__file__).parent.parent
    req_path = Path(args.requirements) if args.requirements else base / "venues" / "requirements.yaml"
    venues_dir = Path(args.venues_dir) if args.venues_dir else base / "venues"

    req = load_yaml(req_path)
    criteria = req.get("criteria", [])

    venue_files = sorted(venues_dir.glob("*.yaml"))
    venue_files = [f for f in venue_files if not f.name.startswith("_") and f.name != "requirements.yaml"]

    if args.venue:
        venue_files = [f for f in venue_files if f.stem == args.venue]
        if not venue_files:
            print(f"Venue '{args.venue}' not found in {venues_dir}", file=sys.stderr)
            sys.exit(1)

    results = []
    for vf in venue_files:
        raw = load_yaml(vf)
        if "name" not in raw:
            continue
        data = resolve_venue_data(raw)
        result = score_venue(data, criteria)
        results.append(result)

    results.sort(key=lambda r: r.get("pct", 0), reverse=True)

    if args.json:
        output = {
            "event": req["event"],
            "results": results,
            "qualified": [r for r in results if r["status"] != "DISQUALIFIED"],
        }
        json.dump(output, sys.stdout, indent=2)
        print()
        return

    print("=" * 70)
    print(f"VENUE SCORING: {req['event']['name']}")
    print(f"Budget: {req['event'].get('budget_range_nok', 'N/A')} NOK | Target attendance: {req['event'].get('expected_attendance', 'N/A')}")
    print("=" * 70)

    for r in results:
        print_scores(r)

    qualified = [r for r in results if r["status"] != "DISQUALIFIED"]
    if qualified:
        print(f"\n{'─' * 70}")
        print("RANKING")
        for i, r in enumerate(qualified, 1):
            print(f"  {i}. {r['name']:40s} {r['pct']:5.1f}%  ({r['slug']})")


if __name__ == "__main__":
    main()
