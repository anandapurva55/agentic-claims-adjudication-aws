"""Attach real damage photographs to the claims.

Source: the Kaggle "Coco Car Damage Detection Dataset" (CC0 1.0, public domain), 70 photos of damaged cars, each annotated with which
parts are damaged (headlamp, front_bumper, rear_bumper, hood, door). Each claim gets the unused photo whose damaged parts best match the
parts on its repair estimate. A claim whose estimate lists none of those five parts gets no photo, which is realistic and says so in the UI.

Writes data/claims/<id>/damage_photo.jpg and data/photo_truth.json (the dataset's own annotations, used only to MEASURE the vision step,
never shown to the agents).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.extract import LocalPdfExtractor  # noqa: E402

SRC = ROOT / "data" / "real" / "car_damage_coco"
PART_OF = {"Front bumper": "front_bumper", "Bonnet": "hood", "Left front door panel": "door", "Headlamp assembly": "headlamp", "Rear bumper": "rear_bumper"}


def photo_parts() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted(SRC.glob("*/COCO_mul_*_annos.json")):
        d = json.loads(f.read_text())
        cat = {c["id"]: c["name"] for c in d["categories"]}
        img = {i["id"]: i["file_name"] for i in d["images"]}
        for a in d["annotations"]:
            out.setdefault(img[a["image_id"]], set()).add(cat[a["category_id"]])
    return out


def main() -> None:
    truth = photo_parts()
    ex = LocalPdfExtractor()
    claims = sorted(p for p in (ROOT / "data" / "claims").iterdir() if p.is_dir())
    wanted = {}
    for c in claims:
        lines = ex.extract(c).get("lines", [])
        wanted[c.name] = {PART_OF[ln["name"]] for ln in lines if ln["name"] in PART_OF}
    free, assigned = set(truth), {}
    for cid, w in sorted(wanted.items(), key=lambda kv: -len(kv[1])):  # hardest to match first
        if not w:
            continue
        best = max(sorted(free), key=lambda f: (len(truth[f] & w) / len(truth[f] | w), -len(truth[f])), default=None)
        if best and truth[best] & w:
            assigned[cid] = best
            free.discard(best)
    result = {}
    for c in claims:
        for old in ("damage_photo.png", "damage_photo.jpg"):
            (c / old).unlink(missing_ok=True)
        if c.name in assigned:
            name = assigned[c.name]
            img = Image.open(next(SRC.glob(f"*/{name}"))).convert("RGB")
            img.thumbnail((900, 900))
            img.save(c / "damage_photo.jpg", quality=85)
            result[c.name] = {"source": name, "dataset_parts": sorted(truth[name]), "estimate_parts": sorted(wanted[c.name])}
    (ROOT / "data" / "photo_truth.json").write_text(json.dumps(result, indent=1))
    print(f"{len(result)} of {len(claims)} claims got a real photo; {len(claims) - len(result)} have no usable photo")
    exact = sum(set(v["dataset_parts"]) == set(v["estimate_parts"]) for v in result.values())
    sub = sum(set(v["estimate_parts"]) <= set(v["dataset_parts"]) for v in result.values())
    print(f"photo parts equal estimate parts: {exact}; estimate parts all visible in photo: {sub}")


if __name__ == "__main__":
    main()
