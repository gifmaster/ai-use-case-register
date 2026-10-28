"""Evidence pack: one report, and one ZIP, for a customer questionnaire, an auditor or an authority.

It bundles what the register and the training log already hold. It adds no judgement of its own:
it shows what is recorded, and which gaps the checks found.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

from .engine import SCHEMA, Issue, Row, expected_intensity, summary, to_csv, to_xlsx
from .pdf import markdown_to_pdf
from .training import TRAINING, covered_use_cases, literacy_summary, training_to_csv

GROUP_LABELS = {
    "all_staff": "All staff",
    "frequent_user": "Frequent users",
    "overseer": "Overseers",
    "management": "Management",
    "governance": "AI Governance Lead and AI Council",
}
INTENSITY_ORDER = ["stop", "redesign", "strict", "enhanced", "standard", "light", ""]


def _cell(v: str) -> str:
    return (v or "").replace("|", "/").replace("\n", " ") or "-"


def evidence_pack(rows: list[Row], issues: list[Issue], training: list[Row], training_issues: list[Issue],
                  org: str = "", today: date | None = None) -> str:
    today = today or date.today()
    active = [r for r in rows if r.get("status") != "retired"]
    s = summary(active)
    lit = literacy_summary(training, rows)
    all_issues = sorted(issues + training_issues, key=lambda i: ({"high": 0, "medium": 1, "low": 2}[i.severity], i.use_case_id))

    L = [
        f"# AI governance evidence pack{': ' + org if org else ''}",
        "",
        f"*Prepared {today.isoformat()} from the AI register and the AI literacy training log. "
        "It shows what is recorded. It does not show that the records are true or complete.*",
        "",
        "## At a glance",
        "",
        f"- **AI use cases recorded:** {len(active)} active, {s['status'].get('live', 0)} live, "
        f"{len(rows) - len(active)} retired",
        f"- **High-risk under the EU AI Act:** {s['eu_ai_act_tier'].get('high', 0)}. "
        "Deployer duties for Annex III high-risk systems apply from 2 December 2027.",
        f"- **AI literacy measures logged:** {lit['sessions']}"
        + (f", most recent on {lit['last_session']}" if lit["last_session"] else ""),
        f"- **Use cases that need a trained overseer:** {len(lit['overseer_needed'])}, "
        f"of which {len(lit['overseer_covered'])} have one logged",
        f"- **Open issues:** {len(all_issues)} ({sum(i.severity == 'high' for i in all_issues)} high)",
        "",
        "## 1. AI use cases",
        "",
        "Every active use case, with its classification under the EU AI Act, its governance intensity and who is accountable.",
        "",
        "| ID | Use case | Vendor | EU AI Act tier | Intensity | Status | Owner | Approved | Next review |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    key = {k: n for n, k in enumerate(INTENSITY_ORDER)}
    for r in sorted(active, key=lambda r: (key.get(r.get("governance_intensity", ""), 9), r.get("use_case_id", ""))):
        L.append("| " + " | ".join(_cell(r.get(c, "")) for c in
                 ("use_case_id", "name", "vendor", "eu_ai_act_tier", "governance_intensity", "status",
                  "use_case_owner", "approved_on", "next_review")) + " |")

    L += ["", "## 2. Impact assessments", "",
          "Decisions on data protection impact assessments (GDPR Art. 35) and fundamental rights impact assessments "
          "(EU AI Act Art. 27), for use cases that involve personal data or are high-risk.", ""]
    relevant = [r for r in active if r.get("personal_data") == "yes" or r.get("eu_ai_act_tier") == "high"]
    if relevant:
        L += ["| ID | Use case | Personal data | Tier | DPIA required | FRIA required |", "|---|---|---|---|---|---|"]
        for r in relevant:
            L.append(f"| {_cell(r.get('use_case_id'))} | {_cell(r.get('name'))} | {_cell(r.get('personal_data'))} | "
                     f"{_cell(r.get('eu_ai_act_tier'))} | {r.get('dpia_required') or 'not decided'} | "
                     f"{r.get('fria_required') or 'not decided'} |")
    else:
        L.append("No active use case involves personal data or is high-risk.")

    L += ["", "## 3. AI literacy measures", "",
          "Providers and deployers take measures to support a sufficient level of AI literacy among the people who use AI "
          "on their behalf (EU AI Act Art. 4, as amended by Regulation (EU) 2026/1744).", ""]
    if training:
        L += ["| Group | Sessions | People reached |", "|---|---|---|"]
        for g in list(GROUP_LABELS) + [g for g in lit["by_group"] if g not in GROUP_LABELS]:
            if g in lit["by_group"]:
                v = lit["by_group"][g]
                L.append(f"| {GROUP_LABELS.get(g, g)} | {v['sessions']} | {v['people'] or '-'} |")
        L += ["", "| ID | Group | Audience | Module | Use cases | Delivered | Evidence | Next refresh |",
              "|---|---|---|---|---|---|---|---|"]
        for e in sorted(training, key=lambda e: e.get("delivered_on", ""), reverse=True):
            L.append(f"| {_cell(e.get('entry_id'))} | {GROUP_LABELS.get(e.get('learner_group', ''), _cell(e.get('learner_group')))} | "
                     f"{_cell(e.get('audience'))} | {_cell(e.get('module'))} | {_cell('; '.join(covered_use_cases(e)))} | "
                     f"{_cell(e.get('delivered_on'))} | {_cell(e.get('evidence'))} | {_cell(e.get('next_refresh'))} |")
    else:
        L.append("**No training log was provided.** Add one to show the AI literacy measures taken.")
    if lit["overseer_needed"]:
        L += ["", "**Trained overseers for enhanced and strict use cases:**", ""]
        names = {r.get("use_case_id"): r.get("name", "") for r in rows}
        for uc in lit["overseer_needed"]:
            mark = "logged" if uc in lit["overseer_covered"] else "**not logged**"
            L.append(f"- {uc} {names.get(uc, '')}: {mark}")

    L += ["", "## 4. Open issues", ""]
    if all_issues:
        L += ["| Item | Severity | Issue | Proposed action | Reference |", "|---|---|---|---|---|"]
        for i in all_issues:
            L.append(f"| {_cell(i.use_case_id)} {_cell(i.name)} | {i.severity} | {i.title} | {i.action} | {i.ref} |")
    else:
        L.append("The checks found no open issues.")

    L += ["", "## 5. What this pack is, and is not", "",
          "- **It is** a summary of the organisation's own records: the AI register and the training log, with the gaps "
          "the register's rule-based checks found.",
          "- **It is not** an audit, a certification or legal advice. The checks find gaps in what was written down. "
          "They cannot tell whether what was written down is true.",
          "- **Other records may be required.** GDPR Art. 30 requires a record of processing activities, and financial "
          "entities under DORA keep a Register of Information (Art. 28(3)). This pack does not replace them.",
          "- **Annexes** in the ZIP download: the register (CSV), the training log (CSV) and the register with its health "
          "check (Excel).",
          "", "---", "",
          f"*Generated by the AI Use Case Register. Register rules last reviewed {SCHEMA.last_reviewed}, "
          f"training rules last reviewed {TRAINING.last_reviewed}.*", ""]
    return "\n".join(L)


def evidence_zip(rows: list[Row], issues: list[Issue], training: list[Row], training_issues: list[Issue],
                 org: str = "", today: date | None = None, slug: str = "ai-governance") -> bytes:
    report = evidence_pack(rows, issues, training, training_issues, org, today)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{slug}-evidence-pack.pdf",
                   markdown_to_pdf(report, "AI governance evidence pack", reviewed=SCHEMA.last_reviewed))
        z.writestr(f"{slug}-evidence-pack.md", report)
        z.writestr(f"{slug}-register.csv", to_csv(rows))
        z.writestr(f"{slug}-training-log.csv", training_to_csv(training))
        z.writestr(f"{slug}-register-and-health-check.xlsx", to_xlsx(rows, issues + training_issues))
    return buf.getvalue()


__all__ = ["evidence_pack", "evidence_zip", "expected_intensity"]
