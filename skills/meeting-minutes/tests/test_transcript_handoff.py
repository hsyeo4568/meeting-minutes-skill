import hashlib
import json
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import transcript_handoff as TH  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stamped_source(tmp_path: Path) -> tuple[Path, Path]:
    transcript = tmp_path / "meeting.txt"
    glossary = tmp_path / "glossary.md"
    transcript.write_text("09:00 A: 회의 시작\n", encoding="utf-8")
    glossary.write_text("## 1. 용어\n", encoding="utf-8")
    transcript.with_name(transcript.name + ".fixstamp").write_text(
        json.dumps(
            {
                "file_sha256": _sha(transcript),
                "glossary_sha256": _sha(glossary),
                "skill_version": "2.3",
            }
        ),
        encoding="utf-8",
    )
    return transcript, glossary


def test_handoff_binds_stamped_transcript_glossary_and_marker_summary(tmp_path):
    transcript, glossary = _stamped_source(tmp_path)
    review = {
        "tier_b_pending": [],
        "tier_c_holds": [],
        "marker_summary": {"existing": 1, "inserted": 2},
    }

    handoff = TH.build_handoff(transcript, glossary, review)

    assert handoff["schema"] == TH.SCHEMA
    assert handoff["transcript"]["sha256"] == _sha(transcript)
    assert handoff["glossary"]["sha256"] == _sha(glossary)
    assert handoff["fixstamp_version"] == "2.3"
    assert handoff["marker_summary"] == review["marker_summary"]
    assert TH.validate_handoff(handoff, transcript, glossary) == {
        "eligible": True,
        "blockers": [],
    }


def test_handoff_blocks_pending_review_and_hash_drift(tmp_path):
    transcript, glossary = _stamped_source(tmp_path)
    review = {
        "tier_b_pending": [{"line": 2, "source": "지원님"}],
        "tier_c_holds": [{"line": 3, "reason": "value ambiguous"}],
        "marker_summary": {"existing": 0, "inserted": 0},
    }
    handoff = TH.build_handoff(transcript, glossary, review)

    pending = TH.validate_handoff(handoff, transcript, glossary)
    assert pending["eligible"] is False
    assert "tier_b_pending: 1" in pending["blockers"]
    assert "tier_c_holds: 1" in pending["blockers"]

    cleared = dict(handoff, review={"tier_b_pending": [], "tier_c_holds": []})
    transcript.write_text("09:00 A: 수정 후 회의 시작\n", encoding="utf-8")
    drifted = TH.validate_handoff(cleared, transcript, glossary)
    assert drifted["eligible"] is False
    assert "transcript_sha256 mismatch" in drifted["blockers"]


def test_minutes_skill_requires_a_valid_handoff_before_composition():
    skill = (Path(__file__).resolve().parent.parent / "SKILL.md").read_text(encoding="utf-8")
    assert "transcript_handoff.py" in skill
    assert "eligible" in skill


def test_orchestrator_skill_keeps_stt_and_minutes_engines_separate():
    """Task 5: the wrapper must validate a handoff, not reimplement either engine."""
    skills_root = Path(__file__).resolve().parents[3]
    matches = list(skills_root.glob("*/meeting-artifact-orchestrator/SKILL.md"))
    assert len(matches) == 1, "meeting-artifact-orchestrator skill is missing or ambiguous"
    text = matches[0].read_text(encoding="utf-8")
    for required in (
        "stt-transcript-fix",
        "transcript_handoff.py",
        "eligible",
        "Tier-B",
        "Tier-C",
        "meeting-minutes",
        "gate → record → verify",
    ):
        assert required in text
    assert "fix_template.py" not in text
