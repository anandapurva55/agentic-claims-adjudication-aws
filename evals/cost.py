"""Cost per claim from measured tokens per model. Usage: python evals/cost.py <report name, for example live_v2_cost>

Prices are USD per million tokens, from third party price trackers for the global Bedrock endpoints, checked November 2026.
They are not from AWS's own price page, so verify them before relying on the result for billing.
"""
import json
import sys
from pathlib import Path

PRICES = {  # model id: (input, output) USD per 1M tokens
    "global.amazon.nova-2-lite-v1:0": (0.33, 2.75),
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00),
    "global.anthropic.claude-sonnet-4-6": (3.00, 15.00),
}


def main() -> None:
    f = Path(__file__).parent / "reports" / f"{sys.argv[1]}.json"
    preds = [p for p in json.loads(f.read_text())["predictions"] if "error" not in p and p.get("tokens_by_model")]
    if not preds:
        sys.exit("no per model token data in this report")
    totals: dict[str, list[int]] = {}
    for p in preds:
        for model, t in p["tokens_by_model"].items():
            a = totals.setdefault(model, [0, 0])
            a[0] += t["input"]
            a[1] += t["output"]
    cost = 0.0
    print(f"{len(preds)} claims measured")
    for model, (i, o) in totals.items():
        pi, po = PRICES.get(model, (0, 0))
        c = i / 1e6 * pi + o / 1e6 * po
        cost += c
        print(f"  {model:52} in {i / len(preds):>8,.0f}  out {o / len(preds):>6,.0f} per claim   ${c / len(preds):.4f}")
    print(f"cost per claim: ${cost / len(preds):.4f}   (about INR {cost / len(preds) * 88:.1f} at 88 INR per USD)")


if __name__ == "__main__":
    main()
