"""Held-out check of the revised damage photo blueprint. Photos are sorted by name; odd positions are the held-out half, which was not looked at while editing the blueprint instruction.
Compares the first blueprint (cached in data/bda/photos.json) with the revised one on the SAME held-out photos."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.bda import BdaClient, photo_parts  # noqa: E402
from scripts_truth import truth  # noqa: E402,I001

SRC = ROOT / "data" / "real" / "car_damage_coco"
t = truth()
names = sorted(t)
held = names[1::2]
cache = ROOT / "data" / "bda" / "photos_v2.json"
done = json.loads(cache.read_text()) if cache.exists() else {}
client = BdaClient()
with ThreadPoolExecutor(4) as pool:
    for n, r in zip([n for n in held if n not in done], pool.map(lambda n: client.process(next(SRC.glob(f"img/{n}")), "coco_v2"), [n for n in held if n not in done]), strict=True):
        done[n] = r
cache.write_text(json.dumps(done))
v1 = json.loads((ROOT / "data" / "bda" / "photos_v1_first_blueprint.json").read_text())


def score(res):
    tp = sum(len(set(photo_parts(res[n])) & t[n]) for n in held)
    fp = sum(len(set(photo_parts(res[n])) - t[n]) for n in held)
    fn = sum(len(t[n] - set(photo_parts(res[n]))) for n in held)
    p, r = tp / max(1, tp + fp), tp / max(1, tp + fn)
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / max(1e-9, p + r), 3), "photos": len(held),
            "headlamp_recall": round(sum("headlamp" in photo_parts(res[n]) and "headlamp" in t[n] for n in held) / max(1, sum("headlamp" in t[n] for n in held)), 3)}


rep = {"held_out_first_blueprint": score(v1), "held_out_revised_blueprint": score(done)}
(ROOT / "evals" / "reports" / "bda_photo_v2.json").write_text(json.dumps(rep, indent=1))
print(json.dumps(rep, indent=1))
