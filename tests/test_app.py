"""Smoke tests for the Streamlit app."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "app.py")


def run():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    return at


def all_md(at):
    return "\n".join(m.value for m in at.markdown)


def test_sample_loads_with_issues():
    at = run()
    assert "Prohibited AI practice not retired" in all_md(at)
    assert at.metric[0].value == "12"  # active use cases


def test_add_use_case_calculates_intensity():
    at = run()
    at.text_input(key="f_name").input("CV screener")
    at.selectbox(key="f_tier").select("high")
    at.selectbox(key="f_level").select("4")
    at.button(key="f_submit").click().run()
    assert not at.exception
    assert len(at.session_state.rows) == 14
    added = at.session_state.rows[-1]
    assert added["name"] == "CV screener" and added["governance_intensity"] == "strict" and added["use_case_id"] == "UC-014"


def test_empty_register():
    at = run()
    at.button(key="btn_empty").click().run()
    assert not at.exception and at.session_state.rows == []


def test_positioning_and_limits_visible():
    at = run()
    assert any("Already have a register" in m.value for m in at.markdown)
    assert any("What this register is" in e.label for e in at.expander)


def test_training_log_tab_and_evidence_pack():
    at = run()
    assert len(at.session_state.training) == 6
    assert any("AI literacy" in t.label for t in at.tabs)
    md = all_md(at)
    assert "Enhanced or strict use case without a trained overseer" in md
    assert any("Preview the evidence pack" in e.label for e in at.expander)


def test_empty_clears_training_log():
    at = run()
    at.button(key="btn_empty").click().run()
    assert not at.exception and at.session_state.training == []
