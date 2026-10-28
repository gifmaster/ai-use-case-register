"""Tests for the register engine."""

import copy
from datetime import date
from pathlib import Path

import pytest
import yaml

from usecasereg import (
    SCHEMA,
    Checks,
    council_report,
    expected_intensity,
    from_risk_check,
    read_any,
    read_csv,
    suggested_next_review,
    to_csv,
    to_xlsx,
    value_errors,
)
from usecasereg.engine import RULES_DIR

ROOT = Path(__file__).parents[1]
SAMPLE = (ROOT / "samples" / "fjordvik_logistik_register.csv").read_bytes()
KEY = yaml.safe_load((Path(__file__).parent / "expected_issues.yaml").read_text(encoding="utf-8"))
TODAY = date.fromisoformat(KEY["today"])

# Header of templates/ai-register.csv in gifmaster/ai-governance-framework
FRAMEWORK_HEADER = ("use_case_id,name,purpose,business_unit,use_case_owner,ai_system,vendor,our_role,affected_people,"
                    "personal_data,oversight_level,eu_ai_act_tier,governance_intensity,dpia_required,fria_required,"
                    "status,approved_by,approved_on,next_review,notes").split(",")


def test_schema_matches_framework_template():
    assert SCHEMA.ids == FRAMEWORK_HEADER


def test_sample_is_valid():
    assert value_errors(read_csv(SAMPLE)) == []


@pytest.mark.parametrize("uc", list(KEY["issues"]))
def test_health_checks_match_answer_key(uc):
    issues = Checks().run(read_csv(SAMPLE), TODAY)
    got = {i.check_id for i in issues if i.use_case_id == uc}
    assert got == set(KEY["issues"][uc])


def test_every_check_is_exercised_by_the_sample():
    used = {c for v in KEY["issues"].values() for c in v}
    assert {k["id"] for k in Checks().checks} == used


@pytest.mark.parametrize("tier, level, want", [
    ("minimal", "2", "light"), ("minimal", "5", "enhanced"),
    ("limited", "3", "standard"), ("high", "3", "enhanced"),
    ("high", "4", "strict"), ("high", "5", "redesign"),
    ("prohibited", "2", "stop"), ("prohibited", "", "stop"),
    ("", "3", None),
])
def test_intensity_matrix(tier, level, want):
    assert expected_intensity({"eu_ai_act_tier": tier, "oversight_level": level}) == want


def test_value_errors():
    rows = read_csv(to_csv([{"use_case_id": "X", "status": "running", "approved_on": "26/10/2026"},
                            {"use_case_id": "X"}]))
    errs = " ".join(value_errors(rows))
    assert "status = 'running'" in errs and "not a date" in errs and "duplicate" in errs


def test_semicolon_csv_and_excel_roundtrip():
    rows = read_csv(SAMPLE)
    semi = to_csv(rows).replace(",", ";")
    assert len(read_csv(semi)) == len(rows)
    xlsx = to_xlsx(rows, Checks().run(rows, TODAY))
    back = read_any(xlsx, "register.xlsx")
    assert back == rows


def test_suggested_review_follows_intensity():
    assert suggested_next_review({"governance_intensity": "strict"}, date(2026, 10, 26)) == "2027-04-26"
    assert suggested_next_review({"governance_intensity": "light"}, date(2026, 1, 31)) == "2027-01-28"


RISK_CHECK_REPORT = """# EU AI Act risk check: CV screener

- **Result:** High risk
- **Role assessed:** Deployer
- **Date:** 2026-10-26
- **Rulebook:** eu-ai-act v2026.10

## Why

- **Art. 6(2), Annex III point 4.** AI used in recruitment or decisions about workers is high risk.
"""


def test_import_from_risk_check():
    got = from_risk_check(RISK_CHECK_REPORT)
    assert got["name"] == "CV screener" and got["eu_ai_act_tier"] == "high" and got["our_role"] == "deployer"
    assert "Annex III point 4" in got["notes"] and "2026-10-26" in got["notes"]
    with pytest.raises(ValueError):
        from_risk_check("# Some other document")


def test_council_report():
    rows = read_csv(SAMPLE)
    md = council_report(rows, Checks().run(rows, TODAY), "Fjordvik Logistik", TODAY)
    assert "Active use cases:** 12" in md and "Prohibited AI practice not retired" in md


@pytest.mark.parametrize("mutate, msg", [
    (lambda k: k["checks"].append(dict(k["checks"][0])), "Duplicate"),
    (lambda k: k["checks"][0].update(severity="critical"), "severity"),
    (lambda k: k["checks"][0]["when"].append({"field": "nope", "eq": "x"}), "unknown field"),
    (lambda k: k["checks"][0]["when"].append({"field": "status", "like": "x"}), "bad condition"),
])
def test_check_validation(mutate, msg):
    data = copy.deepcopy(yaml.safe_load((RULES_DIR / "checks.yaml").read_text(encoding="utf-8")))
    mutate(data)
    with pytest.raises(ValueError, match=msg):
        Checks(data)


def test_platform_csv_uses_plain_headers_and_yes_no():
    from usecasereg import to_platform_csv

    rows = read_csv((ROOT / "samples" / "fjordvik_logistik_register.csv").read_bytes())
    lines = to_platform_csv(rows).splitlines()
    assert lines[0].startswith("ID,Name,Description,")
    assert "Yes" in lines[1] or "No" in lines[1]
    assert len(lines) == len(rows) + 1
