"""AI ambassador roster and team coverage: load, validate, check, and show the evidence ceilings.

Columns, thresholds and check texts live in ``rules/ambassadors.yaml``. The checks compare the roster with the
team coverage figures, so their logic is written here, one branch per check id.

The coverage file holds counts per team, not names of staff, on purpose: tracking training by person is HR data,
and counts are enough to see who is not reached.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from .engine import SEVERITY_ORDER, Issue, Row, _clean, _load

FILE = "ambassadors.yaml"
NETWORK = "Ambassador network"


class AmbassadorSchema:
    def __init__(self, data: dict | None = None):
        data = data or _load(FILE)
        self.columns = data["ambassador_columns"]
        self.ids = [c["id"] for c in self.columns]
        self.labels = {c["id"]: c["label"] for c in self.columns}
        self.allowed = {c["id"]: [str(v) for v in c["allowed"]] for c in self.columns if "allowed" in c}
        self.dates = {c["id"] for c in self.columns if c.get("type") == "date"}
        self.counts = {c["id"] for c in self.columns if c.get("type") == "count"}
        self.t = data["thresholds"]
        self.checks = {k["id"]: k for k in data["checks"]}
        self.last_reviewed = str(data.get("last_reviewed", ""))
        for k in self.checks.values():
            if k["severity"] not in SEVERITY_ORDER or k.get("scope") not in ("network", "ambassador", "team"):
                raise ValueError(f"Ambassador check {k['id']}: bad severity or scope")
        self.coverage_columns = data["coverage_columns"]


class CoverageSchema:
    def __init__(self, data: dict | None = None):
        data = data or _load(FILE)
        self.columns = data["coverage_columns"]
        self.ids = [c["id"] for c in self.columns]
        self.labels = {c["id"]: c["label"] for c in self.columns}
        self.counts = {c["id"] for c in self.columns if c.get("type") == "count"}


AMBASSADORS = AmbassadorSchema()
COVERAGE = CoverageSchema()
T = AMBASSADORS.t


# --------------------------------------------------------------------------- #
# Load, save, validate
# --------------------------------------------------------------------------- #


def _normalise(rows: list[dict], ids: list[str], lower: set[str] = frozenset(), dates: set[str] = frozenset()) -> list[Row]:
    out = []
    for r in rows:
        row = {c: _clean(r.get(c, "")) for c in ids}
        for c in lower:
            row[c] = row[c].lower()
        for c in dates:
            row[c] = row[c][:10]
        if any(row.values()):
            out.append(row)
    return out


def normalise_ambassadors(rows: list[dict], schema: AmbassadorSchema = AMBASSADORS) -> list[Row]:
    return _normalise(rows, schema.ids, set(schema.allowed), schema.dates)


def normalise_coverage(rows: list[dict], schema: CoverageSchema = COVERAGE) -> list[Row]:
    return _normalise(rows, schema.ids)


def _read(data: bytes, filename: str, normalise) -> list[Row]:
    if filename.lower().endswith(".xlsx"):
        from openpyxl import load_workbook

        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        it = ws.iter_rows(values_only=True)
        header = [_clean(h) for h in next(it)]
        return normalise([dict(zip(header, r)) for r in it])
    if not filename.lower().endswith((".csv", ".txt")):
        raise ValueError("Use a CSV or Excel (.xlsx) file.")
    text = data.decode("utf-8-sig")
    delim = ";" if text[:2000].count(";") > text[:2000].count(",") else ","
    return normalise(list(csv.DictReader(io.StringIO(text), delimiter=delim)))


def read_ambassadors(data: bytes, filename: str = "ambassadors.csv") -> list[Row]:
    return _read(data, filename, normalise_ambassadors)


def read_coverage(data: bytes, filename: str = "team-coverage.csv") -> list[Row]:
    return _read(data, filename, normalise_coverage)


def _to_csv(rows: list[Row], ids: list[str]) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=ids, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in ids})
    return out.getvalue()


def ambassadors_to_csv(rows: list[Row], schema: AmbassadorSchema = AMBASSADORS) -> str:
    return _to_csv(rows, schema.ids)


def coverage_to_csv(rows: list[Row], schema: CoverageSchema = COVERAGE) -> str:
    return _to_csv(rows, schema.ids)


def ambassador_errors(rows: list[Row], schema: AmbassadorSchema = AMBASSADORS) -> list[str]:
    errors, seen = [], set()
    for n, r in enumerate(rows, start=1):
        rid = r.get("ambassador_id") or f"row {n}"
        if not r.get("ambassador_id"):
            errors.append(f"Row {n}: missing ambassador_id")
        elif r["ambassador_id"] in seen:
            errors.append(f"{rid}: duplicate ambassador_id")
        seen.add(r.get("ambassador_id"))
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


def _num(v: str) -> int | None:
    return int(v) if v.isdigit() else None


def coverage_errors(rows: list[Row], schema: CoverageSchema = COVERAGE) -> list[str]:
    errors, seen = [], set()
    for n, r in enumerate(rows, start=1):
        team = r.get("team") or f"row {n}"
        if not r.get("team"):
            errors.append(f"Row {n}: missing team")
        elif r["team"] in seen:
            errors.append(f"{team}: team listed twice")
        seen.add(r.get("team"))
        for c in schema.counts:
            if r.get(c) and not r[c].isdigit():
                errors.append(f"{team}: {c} = '{r[c]}' is not a whole number")
        head, trained, vol = _num(r.get("headcount", "")), _num(r.get("trained_level1", "")), _num(r.get("volunteers_trained", ""))
        if head is not None and trained is not None and trained > head:
            errors.append(f"{team}: more trained than headcount")
        if trained is not None and vol is not None and vol > trained:
            errors.append(f"{team}: volunteers cannot exceed the number trained")
        if head is not None and vol is not None and vol > head:
            errors.append(f"{team}: volunteers cannot exceed the headcount")
    return errors


# --------------------------------------------------------------------------- #
# Figures and checks
# --------------------------------------------------------------------------- #


def active(ambassadors: list[Row]) -> list[Row]:
    return [a for a in ambassadors if (a.get("status") or "active") == "active"]


def _days_since(iso: str, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(iso)).days
    except ValueError:
        return None


def team_figures(c: Row) -> dict:
    """Share trained and non-volunteer reach for one team. None where the data to work it out is missing."""
    head, trained, vol = _num(c.get("headcount", "")), _num(c.get("trained_level1", "")), _num(c.get("volunteers_trained", ""))
    share = trained / head if head and trained is not None else None
    reach = None
    if head is not None and trained is not None and vol is not None and head - vol > 0:
        reach = (trained - vol) / (head - vol)
    return {"headcount": head, "trained": trained, "volunteers": vol, "share": share, "reach": reach}


def ambassador_summary(ambassadors: list[Row], coverage: list[Row], today: date | None = None) -> dict:
    today = today or date.today()
    act = active(ambassadors)
    heads = [team_figures(c) for c in coverage]
    headcount = sum(f["headcount"] or 0 for f in heads)
    trained = sum(f["trained"] or 0 for f in heads)
    tracked = [f for f in heads if f["volunteers"] is not None and f["headcount"] is not None and f["trained"] is not None]
    non_vol = sum(f["headcount"] - f["volunteers"] for f in tracked)
    non_vol_reached = sum(f["trained"] - f["volunteers"] for f in tracked)
    exchanges = sorted(a["last_exchange"] for a in act if a.get("last_exchange"))
    return {
        "active_ambassadors": len(act),
        "hours_per_month": sum(int(a["hours_per_month"]) for a in act if a.get("hours_per_month", "").isdigit()),
        "headcount": headcount,
        "trained": trained,
        "share_trained": round(trained / headcount, 4) if headcount else None,
        "non_volunteer_reach": round(non_vol_reached / non_vol, 4) if non_vol else None,
        "volunteers_tracked_in": len(tracked),
        "teams": len(coverage),
        "last_exchange": exchanges[-1] if exchanges else "",
        "staff_per_ambassador": round(headcount / len(act), 1) if act and headcount else None,
    }


def _issue(schema: AmbassadorSchema, check_id: str, ref_id: str, name: str) -> Issue:
    k = schema.checks[check_id]
    return Issue(ref_id, name, check_id, k["severity"], k["title"], k["action"], k["ref"])


def check_ambassadors(ambassadors: list[Row], coverage: list[Row], today: date | None = None,
                      schema: AmbassadorSchema = AMBASSADORS) -> list[Issue]:
    today = today or date.today()
    t = schema.t
    issues: list[Issue] = []
    act = active(ambassadors)

    if len(act) < t["min_active_ambassadors"]:
        issues.append(_issue(schema, "network_too_small", NETWORK, f"{len(act)} active"))

    for a in act:
        aid, name = a.get("ambassador_id", ""), a.get("name", "")
        if not a.get("hours_per_month", "").isdigit() or int(a["hours_per_month"]) == 0:
            issues.append(_issue(schema, "no_protected_time", aid, name))
        if a.get("manager_agreed") != "yes":
            issues.append(_issue(schema, "manager_not_agreed", aid, name))
        since = _days_since(a.get("last_exchange", ""), today)
        if since is None:
            # No exchange yet: only a problem once the ambassador has been in the role longer than the limit.
            started = _days_since(a.get("start_date", ""), today)
            overdue = started is not None and started > t["exchange_max_days"]
        else:
            overdue = since > t["exchange_max_days"]
        if overdue:
            issues.append(_issue(schema, "exchange_overdue", aid, name))

    covered = {a.get("team", "").strip().lower() for a in act}
    for c in coverage:
        team = c.get("team", "")
        f = team_figures(c)
        if f["headcount"] and f["headcount"] >= t["min_team_size_for_ambassador"] and team.strip().lower() not in covered:
            issues.append(_issue(schema, "team_without_ambassador", team, team))
        if f["share"] is not None and f["share"] < t["min_training_coverage"]:
            issues.append(_issue(schema, "low_coverage", team, team))
        if f["reach"] is not None and f["reach"] < t["min_nonvolunteer_reach"]:
            issues.append(_issue(schema, "non_volunteers_not_reached", team, team))

    issues.sort(key=lambda i: (SEVERITY_ORDER[i.severity], i.use_case_id))
    return issues


def foundation_ceilings(ambassadors: list[Row], coverage: list[Row], today: date | None = None,
                        schema: AmbassadorSchema = AMBASSADORS) -> dict[str, tuple[int, str]]:
    """The highest score the evidence on file can support for each foundation, with the reason.

    This is a ceiling, not a score. A person still scores the foundation; the ceiling says what the records
    cannot back up. It applies the caps written in the scoring guides of the toolkits.
    """
    today = today or date.today()
    t = schema.t
    act = active(ambassadors)
    issues = {i.check_id for i in check_ambassadors(ambassadors, coverage, today, schema)}

    if not act:
        amb = (1, "No active ambassadors recorded.")
    elif not any(a.get("hours_per_month", "").isdigit() and int(a["hours_per_month"]) > 0 for a in act):
        amb = (2, "Names with no protected time score 2 at most.")
    elif issues & {"network_too_small", "team_without_ambassador", "exchange_overdue"}:
        amb = (3, "A 4 or 5 needs at least three ambassadors, every team of "
                  f"{t['min_team_size_for_ambassador']} or more covered, and a recent exchange.")
    else:
        amb = (5, "The records support a 4 or 5. Check that the exchange is real and reaches people who would not ask.")

    s = ambassador_summary(ambassadors, coverage, today)
    heads = [team_figures(c) for c in coverage]
    untracked = [c.get("team", "") for c, f in zip(coverage, heads) if f["volunteers"] is None]
    if not coverage:
        trn = (3, "No coverage figures recorded, so nobody can say how many non-volunteers were reached.")
    elif untracked:
        trn = (3, "Volunteers are not tracked in: " + ", ".join(untracked) + ". Without it the score stays at 3 at most.")
    elif s["non_volunteer_reach"] is not None and s["non_volunteer_reach"] < t["min_nonvolunteer_reach"]:
        trn = (3, "Fewer than half of the people who did not volunteer have been trained.")
    elif s["share_trained"] is not None and s["share_trained"] < t["min_training_coverage"]:
        trn = (3, "Fewer than 80 % of staff have had the basic session.")
    else:
        trn = (5, "The records support a 4 or 5. Check the training log and the date of the last refresh.")
    return {"ambassadors": amb, "training": trn}


__all__ = ["AMBASSADORS", "COVERAGE", "NETWORK", "active", "ambassador_errors", "ambassador_summary", "ambassadors_to_csv",
           "check_ambassadors", "coverage_errors", "coverage_to_csv", "foundation_ceilings", "normalise_ambassadors",
           "normalise_coverage", "read_ambassadors", "read_coverage", "team_figures"]
