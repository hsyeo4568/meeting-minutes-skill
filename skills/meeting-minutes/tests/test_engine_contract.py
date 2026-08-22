from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "references" / "engine" / "CONTRACT.md"


def test_required_ontology_is_a_degraded_deferred_artifact_not_a_skip():
    """Task 6: contract must agree with runtime and pipeline semantics."""
    text = CONTRACT.read_text(encoding="utf-8")
    assert "degraded, deferred-load artifact" in text
    assert "else skip entirely (optional add-on, not required for a valid run)" not in text
