# -*- coding: utf-8 -*-
"""Shared utilities for stt-transcript-fix scripts."""
import contextlib
import os
import re
import sys
import time
from pathlib import Path

# Windows cp949 console: warnings/notes contain em-dash/Korean — force UTF-8 stdout
# (guarded: stdout may be None under pythonw / detached tasks).
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    with contextlib.suppress(OSError, ValueError):  # non-fatal: may mojibake but never crash
        sys.stdout.reconfigure(encoding="utf-8")

_encoding_warned = set()

# Single source of truth for quick-scan variant density threshold.
# Conservative: false-positives (extra pass) OK, false-negatives not.
QUICK_SCAN_MIN_DENSITY = 0.0003

# Stale-lock threshold in seconds (10 minutes).
_LOCK_STALE_SECONDS = 600


# Plausible non-ASCII blocks for a real-world transcript: Hangul (syllables,
# jamo), Latin-1 Supplement (café/José — English meetings with accents), and
# General Punctuation (smart quotes/em-dash from word processors). Accidental
# cross-decodes (cp949-as-utf-8, utf-8-as-utf-16) land mostly OUTSIDE these.
_PLAUSIBLE_BLOCKS = (
    ('가', '힣'), ('ㄱ', 'ㅎ'), ('ㅏ', 'ㅣ'),
    ('À', 'ÿ'),   # Latin-1 Supplement letters
    ('‐', '‧'),   # dashes, smart quotes, ellipsis
)


def _plausible_ratio(s: str) -> float:
    """Fraction of non-ASCII chars in plausible transcript blocks. 1.0 for pure ASCII."""
    non_ascii = [ch for ch in s if ord(ch) > 127]
    if not non_ascii:
        return 1.0
    hits = sum(1 for ch in non_ascii if any(lo <= ch <= hi for lo, hi in _PLAUSIBLE_BLOCKS))
    return hits / len(non_ascii)


def detect_encoding(p: Path) -> str:
    """Detect file encoding: BOM first, then Hangul-plausibility arbitration.

    A bare successful decode is NOT proof — CP949 bytes frequently decode
    "successfully" as UTF-8 or UTF-16-LE mojibake (codex review 2026-07-12 #3),
    which would silently re-encode the whole official transcript as garbage.
    Candidates are gated (bare UTF-16 requires NUL bytes — any ASCII char in
    UTF-16 produces one; CP949/UTF-8 never contain NUL) and the decode whose
    non-ASCII chars look most like Hangul wins.

    Raises UnicodeError when nothing decodes — callers must fail closed (no write).
    """
    raw = p.read_bytes()
    if raw[:3] == b'\xef\xbb\xbf':
        # utf-8-sig strips the BOM on read (line-1 speaker header stays clean)
        # and re-adds it on write — byte-identical round-trip.
        return 'utf-8-sig'
    if raw[:2] == b'\xff\xfe':
        return 'utf-16-le'
    if raw[:2] == b'\xfe\xff':
        return 'utf-16-be'

    candidates = ['utf-16-le', 'utf-16-be'] if b'\x00' in raw else ['utf-8', 'cp949']
    scored = []
    for enc in candidates:
        try:
            scored.append((_plausible_ratio(raw.decode(enc)), -candidates.index(enc), enc))
        except UnicodeDecodeError:
            continue
    if not scored:
        raise UnicodeError(
            f"cannot determine encoding of {p.name} — refusing to process (fail-closed)")
    _, _, best = max(scored)
    if best != 'utf-8' and str(p) not in _encoding_warned:
        print(f"NOTE: detected {best} (no BOM): {p.name}")
        _encoding_warned.add(str(p))
    return best


def detect_line_ending(text: str) -> str:
    """Detect line ending style. Returns '\\r\\n' or '\\n'."""
    if '\r\n' in text:
        return '\r\n'
    return '\n'


def acquire_lock(p: Path, timeout: int = 60) -> bool:
    """Create lockfile. Auto-cleans stale locks (>10min)."""
    lock = p.with_name(p.name + ".lock")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if lock.exists():
            age = time.time() - os.path.getmtime(str(lock))
            if age > _LOCK_STALE_SECONDS:
                try:
                    lock.unlink(missing_ok=True)
                except OSError as e:
                    print(f"NOTE: stale lock cleanup failed ({e}); retrying acquire")
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))  # owner token
            os.close(fd)
            return True
        except (FileExistsError, OSError):
            time.sleep(0.3 + (hash(str(p)) % 100) / 1000.0)  # jitter
    return False


def release_lock(p: Path) -> None:
    """Release lockfile — only if this process owns it (PID token match).

    Guards against releasing a lock another process acquired after ours was
    stale-cleaned (codex review 2026-07-12 #4). Legacy/empty locks (no token)
    are released as before.
    """
    lock = p.with_name(p.name + ".lock")
    try:
        owner = lock.read_text(encoding="ascii", errors="replace").strip()
        if owner and owner != str(os.getpid()):
            print(f"NOTE: lock owned by PID {owner}, not us — leaving for owner/stale-clean")
            return
    except FileNotFoundError:
        return
    except OSError:
        pass  # unreadable → treat as legacy lock, fall through to unlink
    try:
        lock.unlink(missing_ok=True)
    except OSError as e:
        print(f"NOTE: lock release failed ({e}); leaving stale lock for auto-clean")


def _line_end(text: str, j: int) -> int:
    """Index of the next newline at/after j, or len(text)."""
    nl = text.find("\n", j)
    return len(text) if nl < 0 else nl


def mask_comments(text: str):
    """Replace (*...) spans with placeholders. Returns (masked_text, spans_list)."""
    spans = []
    result = []
    i = 0
    while i < len(text):
        if text[i:i+2] == "(*":
            depth = 1
            j = i + 2
            while j < len(text) and depth > 0:
                if text[j] == "(":
                    if text[j:j+2] == "(*":
                        # Nested marker inside a span — SKILL.md promises Tier-C escalation.
                        print(f"WARNING: nested (* inside marker span at position {j} — Tier-C: verify span manually")
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
                if j - i > 200:
                    # SKILL.md fail-closed contract: forced-cut line freezes for the
                    # whole run — extend the masked span to end-of-line so the tail
                    # cannot be corrected (codex review 2026-07-12 #5).
                    j = _line_end(text, j)
                    print(f"WARNING: (* marker exceeds 200 chars — cut at position {j}; line frozen (fail-closed)")
                    break
                if depth > 0 and (text[j:j+2] == "\n\n" or text[j:j+4] == "\r\n\r\n"):
                    # CRLF variant included — Windows transcripts are the norm;
                    # checking only "\n\n" let the span swallow the next paragraph.
                    print(f"WARNING: (* marker imbalanced — cut at blank line (position {j}); line frozen (fail-closed)")
                    break
            ph = f"__CMT{i:08d}__"
            spans.append((ph, text[i:j]))
            result.append(ph)
            i = j
        else:
            result.append(text[i])
            i += 1
    return "".join(result), spans


def is_substring_of_either(old: str, new: str) -> bool:
    """True if old is a substring of new or vice versa."""
    return old in new or new in old


# Backward-compat alias — callers that used the old name still work.
is_substring_risky = is_substring_of_either


# Chars treated as "word" chars for boundary detection: Hangul, CJK, ASCII alnum.
_WORD_CLASS = r'가-힣㐀-䶿a-zA-Z0-9'
_WORD_EDGE_RE = re.compile(f'[{_WORD_CLASS}]')


def _boundary_regex(old: str) -> re.Pattern:
    """Word-boundary regex around `old`, guarding each side ONLY when old's edge
    char is itself a word char.

    Korean particles attach with no space (e.g. '충전)에'), so an annotation whose
    old string ends in punctuation like ')' must NOT carry a trailing lookahead —
    a following particle would make an otherwise-correct match wrongly fail. Guard
    each edge independently on whether that edge is a word char, so real substring
    risk (e.g. '피던스' inside '임피던스') is still blocked while punctuation-edged
    annotations replace cleanly.
    """
    lead = f'(?<![{_WORD_CLASS}])' if _WORD_EDGE_RE.match(old) else ''
    trail = f'(?![{_WORD_CLASS}])' if _WORD_EDGE_RE.match(old[-1]) else ''
    return get_cached_regex(lead + re.escape(old) + trail)


def safe_replace(text: str, old: str, new: str) -> str:
    """Replace old→new, using word-boundary regex if substring risk exists."""
    if is_substring_of_either(old, new):
        return _boundary_regex(old).sub(new, text)
    return text.replace(old, new)


def count_variant(text: str, old: str, new: str) -> int:
    """Count occurrences the way safe_replace would actually replace them.

    Word-boundary count when substring-risky, else plain count. Keeps the
    verify gate honest: reported count == count that will be replaced.
    """
    if is_substring_of_either(old, new):
        return len(_boundary_regex(old).findall(text))
    return text.count(old)


def compute_line_diff(original: str, changed: str) -> list[str]:
    """Return list of changed line descriptions. Handles unequal line counts."""
    orig_lines = original.splitlines()
    new_lines = changed.splitlines()
    diffs = []
    max_len = max(len(orig_lines), len(new_lines))
    for i in range(max_len):
        ol = orig_lines[i] if i < len(orig_lines) else "(missing)"
        nl = new_lines[i] if i < len(new_lines) else "(missing)"
        if ol != nl:
            o_show = ol[:120] + ("…" if len(str(ol)) > 120 else "")
            n_show = nl[:120] + ("…" if len(str(nl)) > 120 else "")
            diffs.append(f"  L{i+1}: '{o_show}' → '{n_show}'")
    return diffs


def quick_scan_variants(text: str, variants: list, min_density: float) -> bool:
    """Returns True if file passes density check (warrants full pass).

    NOTE: intentionally uses plain text.count() (not count_variant / word-boundary
    regex) for the density gate. This means substring-risky pairs are over-counted
    relative to what safe_replace would actually replace, producing false-positives
    (extra passes) but never false-negatives (skipped files). The conservative
    bias is deliberate — see QUICK_SCAN_MIN_DENSITY docstring.
    """
    total_chars = max(len(text), 1)
    total_hits = sum(text.count(old) for old, _, _ in variants)
    density = total_hits / total_chars
    print(f"  QUICK-SCAN: {total_hits} hits, density={density:.5f} (threshold={min_density})")
    return density >= min_density


# === Performance caches ===
_glossary_variants_cache = None  # (text, tokens) cache
_safe_replace_regex_cache: dict[str, re.Pattern] = {}


def glossary_variants_cache():
    return _glossary_variants_cache


def set_glossary_variants_cache(val) -> None:
    global _glossary_variants_cache
    _glossary_variants_cache = val


def get_cached_regex(pattern: str) -> re.Pattern:
    if pattern not in _safe_replace_regex_cache:
        _safe_replace_regex_cache[pattern] = re.compile(pattern)
    return _safe_replace_regex_cache[pattern]


def clear_caches() -> None:
    """Reset all module-level caches. Call in test setup/teardown to prevent cross-test bleed."""
    global _glossary_variants_cache
    _glossary_variants_cache = None
    _safe_replace_regex_cache.clear()


# Re-export for external use — placed after all defs so every name is defined.
__all__ = [
    'detect_encoding', 'detect_line_ending', 'acquire_lock', 'release_lock',
    'mask_comments', 'is_substring_of_either', 'is_substring_risky',
    'safe_replace', 'count_variant', 'compute_line_diff', 'quick_scan_variants',
    'get_cached_regex', 'glossary_variants_cache', 'set_glossary_variants_cache',
    'clear_caches', 'QUICK_SCAN_MIN_DENSITY', '_LOCK_STALE_SECONDS',
]
