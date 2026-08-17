import argparse
import json
import re

from common import ensure_dirs, load_json


def tokens(text):
    return set(re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", str(text).lower()))


def jaccard(left, right):
    a = tokens(left)
    b = tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def main():
    parser = argparse.ArgumentParser(description="Recommend evidence-based modeling patterns. Never generates models.")
    parser.add_argument("--goal", default="")
    parser.add_argument("--target-variable", default="")
    parser.add_argument("--dataset", default="")
    parser.add_argument("--sample-size", default=None)
    parser.add_argument("--constraints", default="")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--data-root", default=None)
    args = parser.parse_args()

    data_root = ensure_dirs(args.data_root)
    patterns = load_json(data_root / "patterns.json", [])
    if not patterns:
        print(json.dumps({"message": "no patterns available; run analyze.py first", "recommendations": []}, ensure_ascii=False, indent=2))
        return 0

    preferences = load_json(data_root / "preferences.json", [])
    preference_by_id = {}
    for preference in preferences:
        pattern_id = preference.get("pattern_id")
        vote = preference.get("vote", 0)
        preference_by_id[pattern_id] = preference_by_id.get(pattern_id, 0.0) + (0.1 * float(vote))

    query = " ".join(filter(None, [args.goal, args.target_variable, args.dataset, args.constraints, f"sample_size {args.sample_size}" if args.sample_size else ""]))

    recommendations = []
    for pattern in patterns:
        corpus = " ".join([
            pattern.get("statement", ""),
            " ".join(pattern.get("applies_when", [])),
            " ".join(pattern.get("supporting_models", [])),
            " ".join(pattern.get("does_not_apply_when", [])),
        ])
        overlap = jaccard(query, corpus)
        confidence = float(pattern.get("confidence", 0.0))
        preference = preference_by_id.get(pattern.get("pattern_id"), 0.0)
        score = (0.65 * confidence) + (0.25 * overlap) + preference
        recommendations.append({
            "pattern_id": pattern.get("pattern_id"),
            "statement": pattern.get("statement"),
            "score": round(max(0.0, score), 3),
            "confidence": round(confidence, 3),
            "query_overlap": round(overlap, 3),
            "preference_adjustment": round(preference, 3),
            "applies_when": pattern.get("applies_when", []),
            "does_not_apply_when": pattern.get("does_not_apply_when", []),
            "rationale": pattern.get("rationale", ""),
            "risks": pattern.get("risks", []),
        })

    recommendations.sort(key=lambda item: item["score"], reverse=True)
    top_k = int(args.top_k or len(recommendations))
    recommendations = recommendations[:top_k]

    print(json.dumps({
        "query": query,
        "recommendations": recommendations,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
