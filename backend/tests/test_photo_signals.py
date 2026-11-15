from app.services import data, signals

LINES = [{"name": "Bonnet", "category": "metal", "cost": 14000}, {"name": "Windshield", "category": "glass", "cost": 12500}]


def test_photo_matching_estimate_raises_no_signal():
    assert signals.photo_signals({"lines": LINES, "photo": {"parts": ["hood"]}}) == []


def test_photo_showing_unestimated_damage_is_flagged():
    out = signals.photo_signals({"lines": LINES, "photo": {"parts": ["hood", "rear_bumper"]}})
    assert out and out[0]["severity"] == "medium" and "rear bumper" in out[0]["detail"]


def test_estimate_part_not_in_photo_is_low_severity():
    out = signals.photo_signals({"lines": LINES, "photo": {"parts": ["door"]}})
    assert {s["severity"] for s in out} == {"medium", "low"}


def test_no_photo_means_no_signal():
    assert signals.photo_signals({"lines": LINES, "photo": None}) == []


def test_claim_with_cached_bda_result_carries_photo_fields():
    with_photo = [c for c in data.list_claim_ids() if data.extract_claim(c)["photo"]]
    assert len(with_photo) >= 40
    ph = data.extract_claim(with_photo[0])["photo"]
    assert ph["engine"].startswith("bedrock-data-automation") and set(ph["parts_bda"]) | set(ph["parts_vision"]) == set(ph["parts"])


def test_live_runs_also_get_the_photo_signal(monkeypatch):
    from app import events
    from app.runner import add_document_signals
    monkeypatch.setattr(events, "_current", None)  # an earlier test can leave a bus whose event loop is closed
    events._bus.set(None)
    from app.runstate import RunState
    s = RunState("CLM-X")
    s.extracted = {"lines": LINES, "photo": {"parts": ["hood", "rear_bumper"]}}
    s.signals = [{"kind": "garage", "severity": "low", "detail": "x"}]
    add_document_signals(s)
    add_document_signals(s)  # twice must not duplicate
    assert [g["kind"] for g in s.signals].count("photo_vs_estimate") == 1


def test_form_readers_that_disagree_raise_a_signal():
    from app.services import data
    bda = {"claim_id": "CLM-1", "holder": "Nisha lyer", "claimed_amount": 56300}
    parser = {"claim_id": "CLM-1", "holder": "Nisha Iyer", "claimed_amount": 56300}
    mism = data.compare_form(parser, bda)
    assert [m["field"] for m in mism] == ["holder"]
    out = signals.extraction_signals({"extraction_check": {"mismatches": mism}})
    assert out[0]["severity"] == "low" and "lyer" in out[0]["detail"]
    amount = signals.extraction_signals({"extraction_check": {"mismatches": [{"field": "claimed_amount", "bda": 5630, "parser": 56300}]}})
    assert amount[0]["severity"] == "medium"
    assert signals.extraction_signals({"extraction_check": None}) == []


def test_cached_bda_forms_match_the_parser_except_the_known_ocr_confusion():
    from app.services import data
    holders = []
    for c in data.list_claim_ids():
        ex = data.extract_claim(c)
        for m in (ex["extraction_check"] or {}).get("mismatches", []):
            assert m["field"] == "holder", f"{c}: {m}"
            holders.append(m["bda"])
    assert len(holders) == 5 and all("lyer" in h for h in holders)
