# -*- coding: utf-8 -*-
"""Shared utilities for stt-transcript-fix scripts."""
import os
import sys
import time
from pathlib import Path

_encoding_warned = set()

def detect_encoding(p: Path) -> str:
    """Detect file encoding. Handles BOM and bare UTF-16."""
    raw = p.read_bytes()
    if raw[:2] == b'\xff\xfe':
        return 'utf-16-le'
    if raw[:2] == b'\xfe\xff':
        return 'utf-16-be'
    try:
        raw.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        pass
    try:
        raw.decode('utf-16-le')
        name = str(p)
        if name not in _encoding_warned:
            print(f"NOTE: no BOM, assuming UTF-16-LE: {p.name}")
            _encoding_warned.add(name)
        return 'utf-16-le'
    except UnicodeDecodeError:
        return 'utf-8'


def detect_line_ending(text: str) -> str:
    """Detect line ending style. Returns '\r\n' or '\n'."""
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
            if age > 600:  # 10 min stale → auto-clean
                try:
                    lock.unlink(missing_ok=True)
                except Exception:
                    pass
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except (FileExistsError, OSError):
            time.sleep(0.3 + (hash(str(p)) % 100) / 1000.0)  # jitter
    return False


def release_lock(p: Path):
    """Release lockfile."""
    lock = p.with_name(p.name + ".lock")
    try:
        lock.unlink(missing_ok=True)
    except Exception:
        pass


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
                if text[j] == "(" and j + 1 < len(text) and text[j+1] != "*":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
                if j - i > 200:
                    print(f"WARNING: (* comment exceeds 200 chars — cut at position {j}")
                    break
                nlpos = text.find("\n\n", j)
                if nlpos != -1 and j > nlpos and depth > 0:
                    print(f"WARNING: (* comment imbalanced — cut at blank line (position {nlpos})")
                    j = nlpos
                    break
            ph = f"__CMT{i:08d}__"
            spans.append((ph, text[i:j]))
            result.append(ph)
            i = j
        else:
            result.append(text[i])
            i += 1
    return "".join(result), spans


def is_substring_risky(old: str, new: str) -> bool:
    """True if old is a substring of new or vice versa."""
    return old in new or new in old


def safe_replace(text: str, old: str, new: str) -> str:
    """Replace old→new, using word-boundary regex if substring risk exists."""
    if is_substring_risky(old, new):
        import re
        pattern = r'(?<![가-힣㐀-䶿a-zA-Z0-9])' + re.escape(old) + r'(?![가-힣㐀-䶿a-zA-Z0-9])'
        rx = get_cached_regex(pattern)
        return rx.sub(new, text)
    return text.replace(old, new)


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
    """Returns True if file passes density check (warrants full pass)."""
    total_chars = max(len(text), 1)
    total_hits = sum(text.count(old) for old, _, _ in variants)
    density = total_hits / total_chars
    print(f"  QUICK-SCAN: {total_hits} hits, density={density:.5f} (threshold={min_density})")
    return density >= min_density


# Re-export for external use
__all__ = [
    'detect_encoding', 'detect_line_ending', 'acquire_lock', 'release_lock',
    'mask_comments', 'is_substring_risky', 'safe_replace', 'compute_line_diff',
    'quick_scan_variants', 'get_cached_regex', 'glossary_variants_cache'
]

# === Performance caches ===
_glossary_variants_cache = None  # (text, tokens) cache
_safe_replace_regex_cache = {}

def glossary_variants_cache():
    return _glossary_variants_cache

def set_glossary_variants_cache(val):
    global _glossary_variants_cache
    _glossary_variants_cache = val

def get_cached_regex(pattern: str):
    if pattern not in _safe_replace_regex_cache:
        import re
        _safe_replace_regex_cache[pattern] = re.compile(pattern)
    return _safe_replace_regex_cache[pattern]
