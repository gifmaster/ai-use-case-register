"""Tests for the ambassador roster and the team coverage check, against the hand-worked answer key."""

from datetime import date
from pathlib import Path

import pytest
import yaml

from usecasereg.ambassadors import (
    AMBASSADORS,
    COVERAGE,
    ambassador_errors,
    ambassador_summary,
    check_ambassadors,
    coverage_errors,
    foundation_ceilings,
    read_ambassadors,
    read_coverage,
)

ROOT = Path(__file__).parents[1]
AMB = read_ambassadors((ROOT / "samples" / "fjordvik_logistik_ambassadors.csv").read_bytes())
COV = read_coverage((ROOT / "samples" / "fjordvik_logistik_team_coverage.csv").read_bytes())
KEY = yaml.safe_load((Path(__file__).parent / "expected_ambassador_issues.yaml").read_text(encoding="utf-8"))
TODAY = date.fromisoformat(KEY["today"])


def test_sample_files_are_valid():
    assert ambassador_errors(AMB) == []
    assert coverage_errors(COV) == []
    assert len(AMB) == 5 and len(COV) == 9


@pytest.mark.parametrize("item", list(KEY["issues"]))
def test_checks_match_answer_key(item):
    got = {i.check_id for i in check_ambassadors(AMB, COV, TODAY) if i.use_case_id == item}
    assert got == set(KEY["issues"][item])


def test_no_issue_outside_the_answer_key():
    assert {i.use_case_id for i in check_ambassadors(AMB, COV, TODAY)} <= set(KEY["issues"])


def test_every_check_is_exercised():
    used = {c for v in KEY["issues"].values() for c in v} | {"network_too_small"}
    assert set(AMBASSADORS.checks) == used


def test_network_too_small_fires_below_three_active():
    two = [a for a in AMB if a["ambassador_id"] in ("A-001", "A-002")]
    ids = {(i.use_case_id, i.check_id) for i in check_ambassadors(two, COV, TODAY)}
    assert ("Ambassador network", "network_too_small") in ids
    assert ("Ambassador network", "network_too_small") not in {(i.use_case_id, i.check_id) for i in check_ambassadors(AMB, COV, TODAY)}


def test_paused_and_ended_ambassadors_do_not_count():
    paused = [dict(a, status="paused") if a["ambassador_id"] == "A-001" else a for a in AMB]
    s = ambassador_summary(paused, COV, TODAY)
    assert s["active_ambassadors"] == 4


def test_small_teams_are_exempt_from_ambassador_cover():
    got = {i.use_case_id for i in check_ambassadors(AMB, COV, TODAY) if i.check_id == "team_without_ambassador"}
    assert got == {"Transport", "Warehouse"}  # Marketing (4) and Legal (2) are below the team size of 5


def test_summary_matches_answer_key():
    s = ambassador_summary(AMB, COV, TODAY)
    k = KEY["summary"]
    assert s["active_ambassadors"] == k["active_ambassadors"]
    assert s["hours_per_month"] == k["hours_per_month"]
    assert s["headcount"] == k["headcount"] and s["trained"] == k["trained"]
    assert s["share_trained"] == pytest.approx(k["share_trained"], abs=0.005)
    assert s["non_volunteer_reach"] == pytest.approx(k["non_volunteer_reach"], abs=0.0005)
    assert s["last_exchange"] == k["last_exchange"]


def test_ceilings_follow_the_scoring_guides():
    c = foundation_ceilings(AMB, COV, TODAY)
    assert c["ambassadors"][0] == KEY["caps"]["ambassadors"]
    assert c["training"][0] == KEY["caps"]["training"]


def test_ceiling_2_when_nobody_has_protected_time():
    no_time = [dict(a, hours_per_month="0") for a in AMB]
    assert foundation_ceilings(no_time, COV, TODAY)["ambassadors"][0] == 2


def test_training_ceiling_3_when_volunteers_are_not_tracked():
    untracked = [dict(c, volunteers_trained="") for c in COV]
    c = foundation_ceilings(AMB, untracked, TODAY)["training"]
    assert c[0] == 3 and "volunteer" in c[1].lower()


def test_no_data_gives_low_ceilings_with_a_reason():
    c = foundation_ceilings([], [], TODAY)
    assert c["ambassadors"][0] == 1 and c["training"][0] == 3
    assert c["ambassadors"][1] and c["training"][1]


def test_validation_catches_impossible_numbers():
    bad = [dict(COV[0], trained_level1="99")]
    assert any("more trained than headcount" in e for e in coverage_errors(bad))
    bad = [dict(COV[0], volunteers_trained="99")]
    assert any("volunteers" in e for e in coverage_errors(bad))


def test_columns_are_stable():
    assert AMBASSADORS.ids == ["ambassador_id", "name", "team", "hours_per_month", "manager_agreed", "start_date",
                               "last_exchange", "status"]
    assert COVERAGE.ids == ["team", "headcount", "trained_level1", "volunteers_trained"]
