"""Rules the money engine must hold to. Found by running 20,000 random claims through it: a report date before the incident was approved, an estimate whose
total did not match its own lines was approved, an unreadable date crashed, and about one payout in ten was a rupee off because of float arithmetic and
banker's rounding. Every test here fails against the engine as it was before those fixes."""
import random
from datetime import date, timedelta
from fractions import Fraction
from math import floor

import pytest
from app.rules import AUTHORITY_LIMIT, Facts, Line, Schedule, adjudicate, dep_rate, vehicle_age

SCHEDULE = Schedule("P", 650_000, 2_000, 2024, "2026-01-01", "2026-12-31", "KA01")


def facts(lines=None, labour=3_000, total=None, claimed=None, incident="2026-06-01", reported="2026-06-02", **kw) -> Facts:
    lines = lines if lines is not None else [Line("Front bumper", "plastic", 9_000)]
    gross = sum(ln.cost for ln in lines) + labour
    return Facts("C", "P", "KA01", "KA01", incident, reported, gross if claimed is None else claimed, gross if total is None else total, lines, labour,
                 police_fir=None, **kw)


def test_a_clean_claim_is_still_approved():
    d = adjudicate(facts(), SCHEDULE)
    assert d.decision == "approve" and d.payable > 0


def test_a_report_date_before_the_incident_is_referred_not_approved():
    d = adjudicate(facts(incident="2026-06-10", reported="2026-06-03"), SCHEDULE)
    assert d.decision == "refer" and d.clauses == ["INT.CONSIST"]
    assert "before the incident date" in d.reasons[0]


def test_an_estimate_whose_total_does_not_match_its_lines_is_referred():
    d = adjudicate(facts(total=99_000, claimed=99_000), SCHEDULE)  # lines and labour add up to 12,000
    assert d.decision == "refer" and d.clauses == ["INT.CONSIST"]
    assert "does not equal its lines and labour" in d.reasons[0] and "12,000" in d.reasons[0]


def test_every_problem_in_the_documents_is_listed_not_just_the_first():
    d = adjudicate(facts(total=50_000, incident="2026-06-10", reported="2026-06-03"), SCHEDULE)
    assert d.decision == "refer" and d.reasons[0].count(";") == 2  # amounts differ, total off, date order


@pytest.mark.parametrize("bad", ["2026-13-45", "not a date", "", "2026-02-30", "31/12/2026"])
def test_an_unreadable_date_is_referred_instead_of_crashing(bad):
    for f in (facts(incident=bad), facts(reported=bad)):
        d = adjudicate(f, SCHEDULE)
        assert d.decision == "refer" and d.clauses == ["INT.CONSIST"] and "could not be read" in d.reasons[0]


def test_money_rounds_halves_up_not_to_even():
    # 501 of plastic loses 50 percent, so 250.50 is owed, and a half rupee rounds up to 251 (Python's round() gives 250)
    d = adjudicate(facts(lines=[Line("Cover", "plastic", 501)], labour=0), Schedule("P", 650_000, 0, 2024, "2026-01-01", "2026-12-31", "KA01"))
    assert d.decision == "approve" and d.payable == 251


def test_the_constructive_total_loss_threshold_is_exact():
    s = Schedule("P", 400_000, 2_000, 2024, "2026-01-01", "2026-12-31", "KA01")
    at = adjudicate(facts(lines=[Line("Body", "metal", 297_000)], labour=3_000), s)   # exactly 75 percent of the insured value
    over = adjudicate(facts(lines=[Line("Body", "metal", 297_001)], labour=3_000), s)  # one rupee over
    assert "SEC1.CTL" not in at.clauses and "SEC1.CTL" in over.clauses


def _independent_partial_payable(f: Facts, s: Schedule) -> int:
    """A second implementation written separately, with Fraction, that rounds half up. The engine must agree with it on every random claim."""
    age = vehicle_age(s.reg_year, f.incident_date)
    owed = sum(Fraction(ln.cost * (100 - dep_rate(ln.category, age)), 100) for ln in f.lines) + f.labour - s.deductible
    return max(floor(owed + Fraction(1, 2)), 0)


def _random_claim(rng: random.Random) -> tuple[Facts, Schedule]:
    idv, start = rng.choice([250_000, 400_000, 650_000, 900_000]), date(2026, 1, 1) + timedelta(days=rng.randint(0, 100))
    s = Schedule("P", idv, rng.choice([1_000, 2_000, 5_000, 10_000]), rng.randint(2012, 2026), start.isoformat(), (start + timedelta(days=364)).isoformat(), "KA01")
    inc = start + timedelta(days=rng.randint(0, 364))
    lines = [Line("Part", rng.choice(["metal", "plastic", "rubber", "battery", "fibreglass", "glass"]), rng.randint(500, 40_000)) for _ in range(rng.randint(0, 5))]
    f = facts(lines=lines, labour=rng.randint(0, 15_000), incident=inc.isoformat(), reported=(inc + timedelta(days=rng.randint(-5, 25))).isoformat(),
              salvage=rng.choice([0, 0, rng.randint(0, 100_000)]), theft=rng.random() < 0.05)
    f.police_fir = rng.choice([True, False, None])
    return f, s


def test_payouts_match_an_independent_exact_implementation_on_random_claims():
    rng, checked = random.Random(20261116), 0
    for _ in range(4_000):
        f, s = _random_claim(rng)
        d = adjudicate(f, s)
        if d.decision == "approve" or (d.clauses and d.clauses[0] == "INT.AUTH"):
            gross = sum(ln.cost for ln in f.lines) + f.labour
            if not f.theft and gross * 4 <= 3 * s.idv:
                assert d.payable == _independent_partial_payable(f, s), (f, s)
                checked += 1
    assert checked > 300, "the random claims must actually exercise the partial-loss path"


def test_invariants_hold_on_random_claims():
    rng = random.Random(7)
    for _ in range(6_000):
        f, s = _random_claim(rng)
        d = adjudicate(f, s)  # must never raise
        assert 0 <= d.payable <= s.idv
        if d.decision == "approve":
            assert 0 < d.payable <= AUTHORITY_LIMIT and d.clauses
        if d.decision == "deny":
            assert d.payable == 0
        assert d.decision in {"approve", "deny", "refer"} and d.next_steps


def test_the_first_and_last_day_of_the_policy_are_covered_and_the_days_just_outside_it_are_not():
    """The independent oracle checks the last day and the day after it. This pins the first day and the day before it, so both ends of the period are tested."""
    for incident, reported in [("2026-01-01", "2026-01-02"), ("2026-12-31", "2027-01-01")]:
        assert adjudicate(facts(incident=incident, reported=reported), SCHEDULE).decision == "approve", incident
    for incident, reported in [("2025-12-31", "2026-01-01"), ("2027-01-01", "2027-01-02")]:
        d = adjudicate(facts(incident=incident, reported=reported), SCHEDULE)
        assert (d.decision, d.clauses) == ("deny", ["PERIOD"]), incident
