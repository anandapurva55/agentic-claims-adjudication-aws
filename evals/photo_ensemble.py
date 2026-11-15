"""Combine Bedrock Data Automation and a Bedrock vision model on the 70 real damage photos, and score the union and the intersection.

  python evals/photo_ensemble.py [model]       (default claude-haiku-4.5; needs evals/reports/vision_predictions.json from evals/vision_eval.py)

BDA is precise but misses parts, the vision model finds more but is less precise. The union keeps what either finds, the intersection keeps what both find.
The rule is fixed in advance, nothing is tuned here. Also reports the held-out half (odd positions by file name) that was not used to edit the blueprint.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))
from app.services.bda import photo_parts  # noqa: E402
from scripts_truth import truth  # noqa: E402


def prf(pred: dict[str, set], gold: dict[str, set], names: list[str]) -> dict:
    tp = sum(len(pred[n] & gold[n]) for n in names)
    fp = sum(len(pred[n] - gold[n]) for n in names)
    fn = sum(len(gold[n] - pred[n]) for n in names)
    p, r = tp / max(1, tp + fp), tp / max(1, tp + fn)
    return {"photos": len(names), "precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / max(1e-9, p + r), 3)}


def main(model: str = "claude-haiku-4.5") -> None:
    gold = truth()
    names = sorted(gold)
    bda = {n: set(photo_parts(r)) for n, r in json.loads((ROOT / "data" / "bda" / "photos.json").read_text()).items()}
    llm = {n: set(p) for n, p in json.loads((ROOT / "evals" / "reports" / "vision_predictions.json").read_text())[model].items()}
    systems = {"bda": bda, model: llm, "union": {n: bda[n] | llm[n] for n in names}, "intersection": {n: bda[n] & llm[n] for n in names}}
    held = names[1::2]
    report = {"all_70": {k: prf(v, gold, names) for k, v in systems.items()}, "held_out_half": {k: prf(v, gold, held) for k, v in systems.items()}}
    (ROOT / "evals" / "reports" / "photo_ensemble.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:2])
