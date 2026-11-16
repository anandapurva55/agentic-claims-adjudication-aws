"""Record the static demo: everything the site needs when there is no server.

  python scripts/build_static_demo.py            (needs the generated data: python scripts/generate_data.py)

The site on GitHub Pages cannot run the API, so this script runs the real API once, in replay mode, and writes down what it said:
  frontend/public/demo-data/demo.json     health, topology, the claim list, every claim's extracted fields, every claim's recorded run (the exact event
                                          stream and the recommendation it stored), the sample attacks with the guardrail's answer, and the red team report
  frontend/public/api/claims/<id>/files/  each claim's photo and PDFs, at the URL the app already uses, so the images load with no code
Nothing here is written by hand: if the backend changes, running this again changes the demo. The agents are not run, so no model is called and nothing costs money.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402

OUT = ROOT / "frontend" / "public"
FILES = ("damage_photo.jpg", "claim_form.pdf", "repair_estimate.pdf")


def main() -> None:
    settings.mode = "replay"
    settings.replay_pace = 0.0  # the site paces the events itself, so recording needs no pauses
    settings.cognito_user_pool_id = ""
    settings.runtime_dir = Path(tempfile.mkdtemp(prefix="static-demo-"))

    from app.api.main import app
    from app.services import data
    from fastapi.testclient import TestClient

    client = TestClient(app)
    claims = client.get("/api/claims").json()
    assert claims and all(c["stage"] == "new" for c in claims), "record from a clean state: every claim must start as new"

    details, runs = {}, {}
    for c in claims:
        cid = c["claim_id"]
        details[cid] = client.get(f"/api/claims/{cid}").json()["extracted"]
        with client.stream("POST", f"/api/claims/{cid}/run?mode=replay") as r:
            assert r.status_code == 200, (cid, r.status_code)
            events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ") and line != "data: {}"]
        ai = client.get(f"/api/claims/{cid}").json()["ai"]
        assert ai and ai["run_id"] and events[-1]["type"] == "result", cid
        runs[cid] = {"events": events, "ai": ai}
        dest = OUT / "api" / "claims" / cid / "files"
        dest.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            src = data.claim_dir(cid) / name
            if src.exists():
                shutil.copyfile(src, dest / name)

    attacks = client.get("/api/security/attacks").json()
    scans = {a["payload"]: client.post("/api/security/scan", json={"text": a["payload"]}).json() for a in attacks}
    health = client.get("/api/health").json()
    report = client.get("/api/security/report")
    demo = {
        "generated": time.strftime("%Y-%m-%d"),
        "health": {**health, "region": "recorded demo"},
        "topology": client.get("/api/topology").json(),
        "claims": claims,  # the list as a first visitor sees it: nothing run yet
        "details": details,
        "runs": runs,
        "attacks": attacks,
        "scans": scans,
        "report": report.json() if report.status_code == 200 else None,
    }
    (OUT / "demo-data").mkdir(parents=True, exist_ok=True)
    for shot in ("observability_top.png", "observability_cost.png"):  # the Observability tab shows real screenshots from the live deployment
        shutil.copyfile(ROOT / "docs" / "images" / "app" / shot, OUT / "demo-data" / shot)
    target = OUT / "demo-data" / "demo.json"
    target.write_text(json.dumps(demo, separators=(",", ":")))
    print(f"{len(claims)} claims, {sum(len(r['events']) for r in runs.values())} recorded events, {len(attacks)} attacks, {target.stat().st_size / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
