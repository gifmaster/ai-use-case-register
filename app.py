"""Streamlit front end for the AI Use Case Register.

Run locally:  streamlit run app.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

from usecasereg import (  # noqa: E402
    SCHEMA,
    Checks,
    council_report,
    expected_intensity,
    from_risk_check,
    read_any,
    read_csv,
    suggested_next_review,
    summary,
    to_csv,
    to_xlsx,
    value_errors,
)
from usecasereg.engine import normalise  # noqa: E402
from usecasereg.pdf import markdown_to_pdf  # noqa: E402

RISK_CHECK = "https://ai-act-risk-check.streamlit.app"
REPO = "https://github.com/gifmaster/ai-use-case-register"
SAMPLE = ROOT / "samples" / "fjordvik_logistik_register.csv"
SEV = {"high": "🔴", "medium": "🟠", "low": "🟡"}

st.set_page_config(page_title="AI Use Case Register", page_icon="🗂️", layout="wide")


@st.cache_resource
def checks() -> Checks:
    return Checks()


def set_rows(rows):
    st.session_state.rows = rows
    st.session_state.editor_version = st.session_state.get("editor_version", 0) + 1


if "rows" not in st.session_state:
    set_rows(read_csv(SAMPLE.read_bytes()))
    st.session_state.org = "Fjordvik Logistik A/S (fictional)"

# --- Sidebar -------------------------------------------------------------------
with st.sidebar:
    st.header("Register")
    st.session_state.org = st.text_input("Organisation", st.session_state.get("org", ""))
    up = st.file_uploader("Open a register (CSV or Excel)", type=["csv", "xlsx"])
    if up and st.session_state.get("loaded_file") != (up.name, up.size):
        try:
            set_rows(read_any(up.getvalue(), up.name))
            st.session_state.loaded_file = (up.name, up.size)
            st.success(f"Loaded {len(st.session_state.rows)} use cases.")
        except Exception as exc:
            st.error(f"Could not read the file: {exc}")
    c1, c2 = st.columns(2)
    if c1.button("Sample", width="stretch", key="btn_sample"):
        set_rows(read_csv(SAMPLE.read_bytes()))
        st.session_state.org = "Fjordvik Logistik A/S (fictional)"
        st.rerun()
    if c2.button("Empty", width="stretch", key="btn_empty"):
        set_rows([])
        st.session_state.org = ""
        st.rerun()
    st.caption("Nothing is stored on the server. Download your register before closing the page.")
    st.divider()
    st.markdown(
        f"Same columns as the [framework's register template](https://github.com/gifmaster/ai-governance-framework/blob/main/templates/ai-register.csv). "
        f"Health checks and the intensity matrix are [readable rules]({REPO}/tree/main/src/usecasereg/rules)."
    )

rows = st.session_state.rows
issues = checks().run(rows)
errors = value_errors(rows)

st.title("AI Use Case Register")
st.caption(f"{st.session_state.org or 'Your organisation'} · {len(rows)} use cases · checked {date.today().isoformat()}")

tab_over, tab_reg, tab_health, tab_add, tab_export = st.tabs(["Overview", "Register", f"Health check ({len(issues)})", "Add use case", "Export"])

# --- Overview -----------------------------------------------------------------
with tab_over:
    active = [r for r in rows if r["status"] != "retired"]
    s = summary(active)
    m = st.columns(4)
    m[0].metric("Active use cases", len(active))
    m[1].metric("Live", s["status"].get("live", 0))
    m[2].metric("High-risk", s["eu_ai_act_tier"].get("high", 0))
    m[3].metric("High-severity issues", sum(i.severity == "high" for i in issues))
    if s["eu_ai_act_tier"].get("high"):
        st.info("Deployer duties for high-risk systems listed in Annex III apply from **2 December 2027**.")
    if active:
        charts = [
            ("By governance intensity", s["governance_intensity"],
             ["stop", "redesign", "strict", "enhanced", "standard", "light", "not set"]),
            ("By EU AI Act tier", s["eu_ai_act_tier"],
             ["prohibited", "high", "limited", "minimal", "out_of_scope", "not set"]),
        ]
        for col, (title, counts, order) in zip(st.columns(2), charts):
            keys = [k for k in order if counts.get(k)]
            col.subheader(title)
            col.bar_chart(pd.DataFrame({"use cases": [counts[k] for k in keys]}, index=keys), horizontal=True)
    else:
        st.info("The register is empty. Add a use case or open a register file.")
    st.subheader("Next reviews")
    upcoming = sorted((r for r in active if r["next_review"]), key=lambda r: r["next_review"])[:6]
    if upcoming:
        st.dataframe(pd.DataFrame([{"Due": r["next_review"], "ID": r["use_case_id"], "Use case": r["name"],
                                    "Overdue": "Yes" if r["next_review"] < date.today().isoformat() else ""} for r in upcoming]),
                     hide_index=True, width="stretch")

# --- Register -----------------------------------------------------------------
with tab_reg:
    st.caption("Edit cells directly. The calculated intensity comes from the EU AI Act tier and the oversight level.")
    df = pd.DataFrame(rows, columns=SCHEMA.ids)
    df.insert(13, "calculated_intensity", [expected_intensity(r) or "" for r in rows])
    cfg = {c: st.column_config.SelectboxColumn(SCHEMA.labels[c], options=[""] + v) for c, v in SCHEMA.allowed.items()}
    cfg.update({c: st.column_config.TextColumn(SCHEMA.labels[c]) for c in SCHEMA.ids if c not in SCHEMA.allowed})
    cfg["calculated_intensity"] = st.column_config.TextColumn("Calculated intensity", disabled=True)
    edited = st.data_editor(df, column_config=cfg, num_rows="dynamic", hide_index=True, width="stretch",
                            key=f"editor_{st.session_state.get('editor_version', 0)}")
    new_rows = normalise(edited.drop(columns=["calculated_intensity"]).fillna("").to_dict("records"))
    if new_rows != rows:
        st.session_state.rows = new_rows
        st.rerun()
    if errors:
        st.warning("Values to fix:\n\n" + "\n".join(f"- {e}" for e in errors))

# --- Health check -------------------------------------------------------------
with tab_health:
    if not issues:
        st.success("No issues found.")
    sev_filter = st.multiselect("Severity", ["high", "medium", "low"], default=["high", "medium", "low"])
    for i in [x for x in issues if x.severity in sev_filter]:
        with st.container(border=True):
            st.markdown(f"{SEV[i.severity]} **{i.use_case_id} {i.name}** · {i.title}  \n{i.action}  \n`{i.ref}` · rule `{i.check_id}`")

# --- Add use case -------------------------------------------------------------
with tab_add:
    st.markdown(f"Fill in what you know. Classify first with the [EU AI Act Risk Check]({RISK_CHECK}) and upload its report to fill in the tier.")
    rc = st.file_uploader("Risk Check report (.md), optional", type=["md", "txt"], key="rc")
    pre = {}
    if rc:
        try:
            pre = from_risk_check(rc.getvalue().decode("utf-8"))
            st.success(f"Imported: tier **{pre['eu_ai_act_tier']}**" + (f", role **{pre['our_role']}**" if pre.get("our_role") else ""))
        except ValueError as exc:
            st.error(str(exc))
    with st.form("add", clear_on_submit=True):
        c1, c2 = st.columns(2)
        name = c1.text_input("Name", pre.get("name", ""), key="f_name")
        owner = c2.text_input("Use case owner")
        purpose = st.text_input("Purpose")
        c1, c2, c3 = st.columns(3)
        unit = c1.text_input("Business unit")
        system = c2.text_input("AI system")
        vendor = c3.text_input("Vendor (or 'internal')")
        c1, c2, c3 = st.columns(3)
        role_opts = SCHEMA.allowed["our_role"]
        role = c1.selectbox("Our role", role_opts, index=role_opts.index(pre.get("our_role", "deployer")))
        affected = c2.text_input("Affected people")
        pdata = c3.selectbox("Personal data", ["", "yes", "no"])
        c1, c2 = st.columns(2)
        tiers_opt = [""] + SCHEMA.allowed["eu_ai_act_tier"]
        tier = c1.selectbox("EU AI Act tier", tiers_opt, index=tiers_opt.index(pre.get("eu_ai_act_tier", "")), key="f_tier")
        level = c2.selectbox("Oversight level", [""] + list(SCHEMA.oversight_levels),
                             format_func=lambda k: f"{k} {SCHEMA.oversight_levels[k]}" if k else "", key="f_level")
        notes = st.text_input("Notes", pre.get("notes", ""))
        if st.form_submit_button("Add to register", type="primary", key="f_submit"):
            if not name:
                st.error("Give the use case a name.")
            else:
                nums = [int(r["use_case_id"].split("-")[-1]) for r in rows if r["use_case_id"].split("-")[-1].isdigit()]
                row = {c: "" for c in SCHEMA.ids}
                row.update(use_case_id=f"UC-{(max(nums) + 1 if nums else 1):03d}", name=name, purpose=purpose,
                           business_unit=unit, use_case_owner=owner, ai_system=system, vendor=vendor, our_role=role,
                           affected_people=affected, personal_data=pdata, oversight_level=level,
                           eu_ai_act_tier=tier, status="intake", notes=notes)
                row["governance_intensity"] = expected_intensity(row) or ""
                set_rows(rows + [row])
                st.success(f"Added {row['use_case_id']} with governance intensity **{row['governance_intensity'] or 'not set yet'}**. "
                           f"Suggested first review: {suggested_next_review(row, date.today()) or 'set after classification'}.")
                st.rerun()

# --- Export -------------------------------------------------------------------
with tab_export:
    slug = (st.session_state.org or "ai-register").split("(")[0].strip().lower().replace(" ", "-") or "ai-register"
    st.download_button("Register (CSV)", to_csv(rows), f"{slug}-register.csv", "text/csv")
    st.download_button("Register and health check (Excel)", to_xlsx(rows, issues), f"{slug}-register.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    report = council_report(rows, issues, st.session_state.org)
    st.download_button("AI Council review (PDF)", markdown_to_pdf(report, "AI Use Case Register"),
                       f"{slug}-council-review.pdf", "application/pdf", type="primary",
                       help="Ready to send to the AI Council before the quarterly meeting.")
    st.download_button("AI Council review (Markdown)", report, f"{slug}-council-review.md", "text/markdown")
    with st.expander("Preview the council review"):
        st.markdown(report)
