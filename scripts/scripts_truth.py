"""Dataset part annotations (Kaggle Coco Car Damage Detection Dataset, CC0), shared by the evaluation scripts."""
import json
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "data" / "real" / "car_damage_coco"


def truth() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted(SRC.glob("*/COCO_mul_*_annos.json")):
        d = json.loads(f.read_text())
        cat, img = {c["id"]: c["name"] for c in d["categories"]}, {i["id"]: i["file_name"] for i in d["images"]}
        for a in d["annotations"]:
            out.setdefault(img[a["image_id"]], set()).add(cat[a["category_id"]])
    return out
