"""Run every claim form and every damage photo through Amazon Bedrock Data Automation, cache the results and score them.

  python scripts/run_bda_ingest.py            (needs AWS credentials and CLAIMS_CLAIMS_BUCKET / CLAIMS_BDA_PROJECT_ARN)

Outputs
  data/bda/<claim>.json            what the product reads: form fields and photo fields for one claim
  evals/reports/bda_photo.json     BDA damaged parts versus the dataset's own annotations, over all 70 photos
  evals/reports/bda_form.json      BDA form fields versus the known values the form was generated from, over all 63 forms
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.services import vision  # noqa: E402
from app.services.bda import PARTS, BdaClient, photo_parts  # noqa: E402
from app.services.extract import LocalPdfExtractor  # noqa: E402

SRC = ROOT / "data" / "real" / "car_damage_coco"
CLAIMS = ROOT / "data" / "claims"
OUT = ROOT / "data" / "bda"
REPORTS = ROOT / "evals" / "reports"
FORM_FIELDS = ["claim_id", "policy_no", "holder", "vehicle_reg", "incident_date", "report_date", "claimed_amount"]


def norm(v) -> str:
    return "".join(ch for ch in str(v).lower() if ch.isalnum())


def run_photos(client: BdaClient, truth: dict[str, set[str]]) -> dict:
    files = {p.name: p for p in sorted(SRC.glob("img/*.jpg"))}
    cache = OUT / "photos.json"
    done: dict = json.loads(cache.read_text()) if cache.exists() else {}

    def one(name: str) -> tuple[str, dict]:
        return name, client.process(files[name], "coco")
    todo = [n for n in files if n in truth and n not in done]
    with ThreadPoolExecutor(4) as pool:
        for name, r in pool.map(one, todo):
            done[name] = r
            print("photo", name, r["seconds"], photo_parts(r), flush=True)
    cache.write_text(json.dumps(done))
    tp = fp = fn = exact = vehicles = 0
    for name, r in done.items():
        got, want = set(photo_parts(r)), truth[name]
        tp, fp, fn = tp + len(got & want), fp + len(got - want), fn + len(want - got)
        exact += got == want
        vehicles += bool(r["custom"].get("is_vehicle_photo"))
    p, rc = tp / max(1, tp + fp), tp / max(1, tp + fn)
    per_part = {}
    for part in sorted(PARTS):
        a = sum(part in photo_parts(r) and part in truth[n] for n, r in done.items())
        g = sum(part in photo_parts(r) for n, r in done.items())
        w = sum(part in truth[n] for n in done)
        per_part[part] = {"precision": round(a / g, 3) if g else None, "recall": round(a / w, 3) if w else None, "photos_with_part": w}
    rep = {"photos": len(done), "recognised_as_vehicle": vehicles, "precision": round(p, 3), "recall": round(rc, 3), "f1": round(2 * p * rc / max(1e-9, p + rc), 3),
           "exact_set_match": exact, "per_part": per_part, "mean_seconds": round(sum(r["seconds"] for r in done.values()) / len(done), 1)}
    (REPORTS / "bda_photo.json").write_text(json.dumps(rep, indent=1))
    print("PHOTO", json.dumps(rep), flush=True)
    return done


def run_vision(names: list[str]) -> dict[str, list[str]]:
    """Damaged parts from the vision model for every photo, cached next to the BDA results."""
    cache = OUT / "photos_vision.json"
    done: dict = json.loads(cache.read_text()) if cache.exists() else {}
    files = {p.name: p for p in sorted(SRC.glob("img/*.jpg"))}
    with ThreadPoolExecutor(3) as pool:
        todo = [n for n in names if n not in done]
        for n, parts in zip(todo, pool.map(lambda n: vision.damaged_parts(files[n]), todo), strict=True):
            done[n] = parts
    cache.write_text(json.dumps(done))
    return done


def run_forms(client: BdaClient) -> dict:
    ex = LocalPdfExtractor()
    cache = OUT / "forms.json"
    done: dict = json.loads(cache.read_text()) if cache.exists() else {}
    ids = [p.name for p in sorted(CLAIMS.iterdir()) if p.is_dir()]

    def one(cid: str) -> tuple[str, dict]:
        return cid, client.process(CLAIMS / cid / "claim_form.pdf", f"forms/{cid}")
    with ThreadPoolExecutor(4) as pool:
        for cid, r in pool.map(one, [c for c in ids if c not in done]):
            done[cid] = r
            print("form", cid, r["seconds"], flush=True)
    cache.write_text(json.dumps(done))
    right = {f: 0 for f in FORM_FIELDS}
    for cid in ids:
        want, got = ex.extract(CLAIMS / cid), done[cid]["custom"]
        for f in FORM_FIELDS:
            right[f] += norm(got.get(f, "")) == norm(want.get(f, ""))
    rep = {"forms": len(ids), "field_accuracy": {f: round(n / len(ids), 3) for f, n in right.items()},
           "all_fields_correct": sum(all(norm(done[c]["custom"].get(f, "")) == norm(ex.extract(CLAIMS / c).get(f, "")) for f in FORM_FIELDS) for c in ids),
           "mean_seconds": round(sum(r["seconds"] for r in done.values()) / len(done), 1)}
    (REPORTS / "bda_form.json").write_text(json.dumps(rep, indent=1))
    print("FORM", json.dumps(rep), flush=True)
    return done


def main() -> None:
    OUT.mkdir(exist_ok=True)
    client = BdaClient()
    truth: dict[str, set[str]] = {}
    for f in sorted(SRC.glob("*/COCO_mul_*_annos.json")):
        d = json.loads(f.read_text())
        cat, img = {c["id"]: c["name"] for c in d["categories"]}, {i["id"]: i["file_name"] for i in d["images"]}
        for a in d["annotations"]:
            truth.setdefault(img[a["image_id"]], set()).add(cat[a["category_id"]])
    photos = run_photos(client, truth)
    seen = run_vision(sorted(photos))
    forms = run_forms(client)
    mapping = json.loads((ROOT / "data" / "photo_truth.json").read_text())
    for cid, form in forms.items():
        src = mapping.get(cid, {}).get("source")
        photo = photos.get(src)
        (OUT / f"{cid}.json").write_text(json.dumps({"claim_id": cid, "form": form["custom"],
                                                     "photo": {"source": src, "parts": sorted(set(photo_parts(photo)) | set(seen[src])), "parts_bda": photo_parts(photo),
                                                               "parts_vision": seen[src], "severity": photo["custom"].get("severity"),
                                                               "description": photo["custom"].get("description"), "summary": photo["standard"].get("image", {}).get("summary")} if photo else None}, indent=1))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
