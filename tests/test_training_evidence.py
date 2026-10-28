"""Tests for the AI literacy training log and the evidence pack."""

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest
import yaml
from pypdf import PdfReader

from usecasereg import Checks, read_csv
from usecasereg.evidence import evidence_pack, evidence_zip
from usecasereg.training import (
    TRAINING,
    TrainingSchema,
    check_training,
    covered_use_cases,
    literacy_summary,
    read_training,
    training_errors,
    training_to_csv,
)

ROOT = Path(__file__).parents[1]
REGISTER = read_csv((ROOT / "samples" / "fjordvik_logistik_register.csv").read_bytes())
LOG_BYTES = (ROOT / "samples" / "fjordvik_logistik_training_log.csv").read_bytes()
LOG = read_training(LOG_BYTES)
KEY = yaml.safe_load((Path(__file__).parent / "expected_training_issues.yaml").read_text(encoding="utf-8"))
TODAY = date.fromisoformat(KEY["today"])

# Header of templates/training-log.csv in gifmaster/ai-governance-framework
FRAMEWORK_TRAINING_HEADER = ("entry_id,learner_group,audience,people,module,use_case_id,delivered_on,delivered_by,"
                             "format,evidence,next_refresh").split(",")


def test_training_columns_match_framework_template():
    assert TRAINING.ids == FRAMEWORK_TRAINING_HEADER


def test_sample_log_is_valid():
    assert training_errors(LOG) == []
    assert len(LOG) == 6


@pytest.mark.parametrize("item", list(KEY["issues"]))
def test_training_checks_match_answer_key(item):
    got = {i.check_id for i in check_training(LOG, REGISTER, TODAY) if i.use_case_id == item}
    assert got == set(KEY["issues"][item])


def test_no_issue_outside_the_answer_key():
    got = {i.use_case_id for i in check_training(LOG, REGISTER, TODAY)}
    assert got <= set(KEY["issues"])


def test_every_training_check_is_exercised():
    used = {c for v in KEY["issues"].values() for c in v} | {"no_all_staff_training"}
    assert set(TRAINING.checks) == used


def test_missing_all_staff_training_fires():
    log = [e for e in LOG if e["learner_group"] != "all_staff"]
    ids = [i.check_id for i in check_training(log, REGISTER, TODAY)]
    assert "no_all_staff_training" in ids


def test_empty_log_and_register_in_use():
    issues = check_training([], REGISTER, TODAY)
    ids = {(i.use_case_id, i.check_id) for i in issues}
    assert ("Training log", "no_all_staff_training") in ids
    assert ("UC-008", "overseer_training_missing") in ids and ("UC-010", "overseer_training_missing") in ids


def test_no_baseline_issue_when_nothing_is_in_use():
    retired = [dict(r, status="retired") for r in REGISTER]
    assert check_training([], retired, TODAY) == []


def test_overseer_needed_uses_calculated_intensity_too():
    row = dict(REGISTER[0], use_case_id="UC-900", status="live", eu_ai_act_tier="high", oversight_level="3",
               governance_intensity="")
    ids = {i.use_case_id for i in check_training(LOG, REGISTER + [row], TODAY)}
    assert "UC-900" in ids


def test_several_use_cases_in_one_entry():
    assert covered_use_cases({"use_case_id": "UC-003; UC-030,UC-031"}) == ["UC-003", "UC-030", "UC-031"]


def test_value_errors_are_caught():
    bad = [dict(LOG[0], learner_group="everyone", people="many", delivered_on="15/09/2026"),
           dict(LOG[1], entry_id="T-001")]
    errors = training_errors(bad)
    assert any("learner_group" in e for e in errors)
    assert any("people" in e for e in errors)
    assert any("delivered_on" in e for e in errors)
    assert any("duplicate" in e for e in errors)


def test_csv_round_trip_and_semicolons():
    assert read_training(training_to_csv(LOG).encode()) == LOG
    import csv

    out = io.StringIO()  # how Danish Excel saves CSV: semicolons, fields with ';' quoted
    w = csv.writer(out, delimiter=";")
    w.writerow(TRAINING.ids)
    w.writerows([e[c] for c in TRAINING.ids] for e in LOG)
    assert read_training(out.getvalue().encode()) == LOG


def test_excel_round_trip():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(TRAINING.ids)
    for e in LOG:
        ws.append([e[c] for c in TRAINING.ids])
    buf = io.BytesIO()
    wb.save(buf)
    assert read_training(buf.getvalue(), "log.xlsx") == LOG


def test_bad_check_scope_is_rejected():
    import copy

    data = yaml.safe_load((ROOT / "src" / "usecasereg" / "rules" / "training.yaml").read_text(encoding="utf-8"))
    data = copy.deepcopy(data)
    data["checks"][0]["scope"] = "everywhere"
    with pytest.raises(ValueError):
        TrainingSchema(data)


def test_literacy_summary():
    s = literacy_summary(LOG, REGISTER)
    assert s["sessions"] == 6 and s["last_session"] == "2026-10-10"
    assert s["by_group"]["all_staff"]["people"] == 64
    assert s["overseer_needed"] == ["UC-008", "UC-010"] and s["overseer_covered"] == ["UC-008"]


def _pack(log=LOG):
    issues = Checks().run(REGISTER, TODAY)
    return evidence_pack(REGISTER, issues, log, check_training(log, REGISTER, TODAY), "Fjordvik Logistik A/S", TODAY)


def test_evidence_pack_contents():
    md = _pack()
    for text in ("# AI governance evidence pack: Fjordvik Logistik A/S", "## 1. AI use cases", "## 2. Impact assessments",
                 "## 3. AI literacy measures", "## 4. Open issues", "## 5. What this pack is, and is not",
                 "Regulation (EU) 2026/1744", "UC-010 Shift scheduling: **not logged**", "UC-008 Demand forecasting: logged",
                 "Enhanced or strict use case without a trained overseer", "Prohibited AI practice not retired"):
        assert text in md, text
    assert "UC-012" not in md.split("## 2.")[0]  # retired use case not listed as active
    assert "\u2014" not in md  # no em dashes (house style)


def test_evidence_pack_without_log_says_so():
    assert "No training log was provided" in _pack(log=[])


def test_evidence_zip_contains_all_annexes():
    issues = Checks().run(REGISTER, TODAY)
    z = zipfile.ZipFile(io.BytesIO(evidence_zip(REGISTER, issues, LOG, check_training(LOG, REGISTER, TODAY),
                                                "Fjordvik", TODAY, slug="fjordvik")))
    names = set(z.namelist())
    assert names == {"fjordvik-evidence-pack.pdf", "fjordvik-evidence-pack.md", "fjordvik-register.csv",
                     "fjordvik-training-log.csv", "fjordvik-register-and-health-check.xlsx"}
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(z.read("fjordvik-evidence-pack.pdf"))).pages)
    assert "AI literacy measures" in text
    assert read_training(z.read("fjordvik-training-log.csv")) == LOG
