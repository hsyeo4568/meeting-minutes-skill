from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "references" / "engine" / "CONTRACT.md"
TOOLING = ROOT / "references" / "engine" / "tooling.md"
PIPELINE = ROOT / "references" / "engine" / "pipeline.md"
SKILL = ROOT / "SKILL.md"
SETUP = ROOT / "SETUP.md"


def test_required_ontology_is_a_degraded_deferred_artifact_not_a_skip():
    """Task 6: contract must agree with runtime and pipeline semantics."""
    text = CONTRACT.read_text(encoding="utf-8")
    assert "degraded, deferred-load artifact" in text
    assert "else skip entirely (optional add-on, not required for a valid run)" not in text


def test_ontology_skip_and_degradation_policy_is_consistent_in_user_docs():
    """required=true must never inherit the optional-tool skip wording."""
    for path in (CONTRACT, TOOLING, SETUP):
        text = path.read_text(encoding="utf-8")
        assert "`required: false`" in text, path
        assert "`ontology` key" in text, path
        assert "`required: true`" in text, path
        assert "deferred-load" in text or "deferred TTL" in text, path


def test_runnerless_required_ontology_needs_trusted_validator_receipt_before_completion():
    """No parser proof means a deferred TTL remains manual-required, never verified."""
    for path in (CONTRACT, TOOLING, PIPELINE, SKILL, SETUP):
        text = path.read_text(encoding="utf-8")
        assert "mm-ontology-validator-receipt/1" in text, path
        assert "manual_required" in text, path
        assert "close=7" in text, path
