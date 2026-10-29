"""AI literacy training log: load, validate and check it against the register.

Columns and check texts live in ``rules/training.yaml``. The checks compare two files (the log and the
register), so their logic is written here, one function per check id.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

from .engine import RULES_DIR, SEVERITY_ORDER, Issue, Row, _clean, expected_intensity, _load

TRAINING_FILE = "training.yaml"


class TrainingSchema:
    def __init__(self, data: dict | None = None):
        data = data or _load(TRAINING_FILE)
        self.columns: list[dict] = data["columns"]
        self.ids = [c["id"] for c in self.columns]
        self.labels = {c["id"]: c["label"] for c in self.columns}
        self.allowed = {c["id"]: [str(v) for v in c["allowed"]] for c in self.columns if "allowed" in c}
        self.dates = {c["id"] for c in self.columns if c.get("type") == "date"}
        self.counts = {c["id"] for c in self.columns if c.get("type") == "count"}
        self.overseer_needed_for = set(data["overseer_needed_for"])
        self.checks = {k["id"]: k for k in data["checks"]}
        self.last_reviewed = str(data.get("last_reviewed", ""))
        for k in self.checks.values():
            if k["severity"] not in SEVERITY_ORDER or k.get("scope") not in ("log", "use_case", "entry"):
                raise ValueError(f"Training check {k['id']}: bad severity or scope")


TRAINING = TrainingSchema()


# --------------------------------------------------------------------------- #
# Load and save
# --------------------------------------------------------------------------- #


def normalise_training(rows: list[dict], schema: TrainingSchema = TRAINING) -> list[Row]:
    out = []
    for r in rows:
        row = {c: _clean(r.get(c, "")) for c in schema.ids}
        for c in schema.allowed:
            row[c] = row[c].lower()
        for c in schema.dates:
            row[c] = row[c][:10]
        if any(row.values()):
            out.append(row)
    return out


def read_training(data: bytes, filename: str = "training-log.csv") -> list[Row]:
    if filename.lower().endswith(".xlsx"):
        from openpyxl import load_workbook

        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        it = ws.iter_rows(values_only=True)
        header = [_clean(h) for h in next(it)]
        return normalise_training([dict(zip(header, r)) for r in it])
    if not filename.lower().endswith((".csv", ".txt")):
        raise ValueError("Use a CSV or Excel (.xlsx) file.")
    text = data.decode("utf-8-sig")
    delim = ";" if text[:2000].count(";") > text[:2000].count(",") else ","
    return normalise_training(list(csv.DictReader(io.StringIO(text), delimiter=delim)))


def training_to_csv(rows: list[Row], schema: TrainingSchema = TRAINING) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=schema.ids, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in schema.ids})
    return out.getvalue()


def covered_use_cases(entry: Row) -> list[str]:
    """Use case IDs an entry covers. Several may be given, separated by ';' or ','."""
    return [x.strip() for x in re.split(r"[;,]", entry.get("use_case_id", "")) if x.strip()]


def training_errors(rows: list[Row], schema: TrainingSchema = TRAINING) -> list[str]:
    errors, seen = [], set()
    for n, r in enumerate(rows, start=1):
        rid = r.get("entry_id") or f"row {n}"
        if not r.get("entry_id"):
            errors.append(f"Row {n}: missing entry_id")
        elif r["entry_id"] in seen:
            errors.append(f"{rid}: duplicate entry_id")
        seen.add(r.get("entry_id"))
        for c, allowed in schema.allowed.items():
            if r.get(c) and r[c] not in allowed:
                errors.append(f"{rid}: {c} = '{r[c]}' is not one of {', '.join(allowed)}")
        for c in schema.dates:
            if r.get(c):
                try:
                    date.fromisoformat(r[c])
                except ValueError:
                    errors.append(f"{rid}: {c} = '{r[c]}' is not a date (YYYY-MM-DD)")
        for c in schema.counts:
            if r.get(c) and not r[c].isdigit():
                errors.append(f"{rid}: {c} = '{r[c]}' is not a whole number")
    return errors


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #


def needs_overseer(row: Row, schema: TrainingSchema = TRAINING) -> bool:
    """A live use case whose recorded or calculated intensity is enhanced or strict."""
    if row.get("status") != "live":
        return False
    return bool({row.get("governance_intensity"), expected_intensity(row)} & schema.overseer_needed_for)


def _issue(schema: TrainingSchema, check_id: str, ref_id: str, name: str) -> Issue:
    k = schema.checks[check_id]
    return Issue(ref_id, name, check_id, k["severity"], k["title"], k["action"], k["ref"])


def check_training(training: list[Row], register: list[Row], today: date | None = None,
                   schema: TrainingSchema = TRAINING) -> list[Issue]:
    today = today or date.today()
    issues: list[Issue] = []

    in_use = [r for r in register if r.get("status") in ("assessment", "live")]
    if in_use and not any(e.get("learner_group") == "all_staff" for e in training):
        issues.append(_issue(schema, "no_all_staff_training", "Training log", "All staff"))

    trained_overseers = {uc for e in training if e.get("learner_group") == "overseer" for uc in covered_use_cases(e)}
    for r in register:
        if needs_overseer(r, schema) and r.get("use_case_id") not in trained_overseers:
            issues.append(_issue(schema, "overseer_training_missing", r.get("use_case_id", ""), r.get("name", "")))

    known = {r.get("use_case_id") for r in register}
    for e in training:
        eid, name = e.get("entry_id", ""), e.get("audience", "")
        try:
            if e.get("next_refresh") and date.fromisoformat(e["next_refresh"]) < today:
                issues.append(_issue(schema, "refresh_overdue", eid, name))
        except ValueError:
            pass
        if not e.get("evidence"):
            issues.append(_issue(schema, "no_evidence", eid, name))
        if any(uc not in known for uc in covered_use_cases(e)):
            issues.append(_issue(schema, "unknown_use_case", eid, name))

    issues.sort(key=lambda i: (SEVERITY_ORDER[i.severity], i.use_case_id))
    return issues


def literacy_summary(training: list[Row], register: list[Row], schema: TrainingSchema = TRAINING) -> dict:
    """Counts used in the app and the evidence pack."""
    by_group: dict[str, dict[str, int]] = {}
    for e in training:
        g = by_group.setdefault(e.get("learner_group") or "not set", {"sessions": 0, "people": 0})
        g["sessions"] += 1
        g["people"] += int(e["people"]) if e.get("people", "").isdigit() else 0
    dates = sorted(e["delivered_on"] for e in training if e.get("delivered_on"))
    need = [r for r in register if needs_overseer(r, schema)]
    trained = {uc for e in training if e.get("learner_group") == "overseer" for uc in covered_use_cases(e)}
    return {
        "by_group": by_group,
        "sessions": len(training),
        "last_session": dates[-1] if dates else "",
        "overseer_needed": [r.get("use_case_id", "") for r in need],
        "overseer_covered": [r.get("use_case_id", "") for r in need if r.get("use_case_id") in trained],
    }


__all__ = ["TRAINING", "TrainingSchema", "check_training", "covered_use_cases", "literacy_summary", "needs_overseer",
           "normalise_training", "read_training", "training_errors", "training_to_csv", "RULES_DIR"]
