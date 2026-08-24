# -*- coding: utf-8 -*-
"""Schema-v2 tests for machine-readable meeting metadata."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mm_schema as MS  # noqa: E402


VALID_V2 = """---
schema_version: 2
recordings:
  - path: 2026. 8. 21. 오전 9_35 녹음.txt
    corrected_path: 2026. 8. 21. 오전 9_35 녹음.corrected.txt
    review_path: 2026. 8. 21. 오전 9_35 녹음.handoff.json
action_items:
  - id: 2026-08-21-ACME-01
    org: 소속사
    owner: 담당자
    due: 2026-08-21
    status: open
    text: 수집 필드 매핑 정리
artifacts:
  vault: {status: pending}
---

# 회의록
"""


def test_v2_schema_accepts_structured_recordings_and_action_items():
    assert MS.validate_text(VALID_V2) == []


def test_legacy_frontmatter_stays_compatible():
    assert MS.validate_text("---\nrecording: raw.txt\naction_items: 3\n---\n# old\n") == []


def test_v2_schema_rejects_scalar_recording_and_unstructured_actions():
    invalid = VALID_V2.replace(
        "recordings:\n  - path: 2026. 8. 21. 오전 9_35 녹음.txt\n    corrected_path: 2026. 8. 21. 오전 9_35 녹음.corrected.txt\n    review_path: 2026. 8. 21. 오전 9_35 녹음.handoff.json",
        "recordings: raw.txt",
    ).replace(
        "action_items:\n  - id: 2026-08-21-ACME-01\n    org: 소속사\n    owner: 담당자\n    due: 2026-08-21\n    status: open\n    text: 수집 필드 매핑 정리",
        "action_items: 3",
    )
    errors = MS.validate_text(invalid)
    assert "recordings must be a list" in errors
    assert "action_items must be a list" in errors


def test_v2_schema_rejects_non_iso_due_string():
    errors = MS.validate_text(VALID_V2.replace("due: 2026-08-21", "due: '2026/08/21'"))
    assert "action_items[1].due must be an ISO calendar date (YYYY-MM-DD)" in errors
