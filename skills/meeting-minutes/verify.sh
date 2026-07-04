#!/usr/bin/env bash
# meeting-minutes portability gates. Run from skill root: bash verify.sh
# Gate #1: engine purity (no proper nouns). Gate #3: every {{placeholder}} exists in config.example.yaml.
# Gate #2 (degradation) is a manual SKILL.md read-through — not scripted.
set -u
cd "$(dirname "$0")"
ENGINE="references/engine"
CFG="config.example.yaml"
ALLOW_PROFILE="segments|orgs"   # placeholders the profile supplies (not in config)
fail=0

# Engine content files + SKILL.md (all shareable). CONTRACT.md legitimately names forbidden tokens.
# Portable array build (no mapfile — broken on macOS bash 3.2, where it would silently yield an
# empty FILES list and FALSE-PASS the purity gate).
FILES=()
while IFS= read -r f; do [ -n "$f" ] && FILES+=("$f"); done < <(find "$ENGINE" -name '*.md' ! -name 'CONTRACT.md'; echo SKILL.md)
if [ "${#FILES[@]}" -lt 2 ]; then echo "  FATAL: found ${#FILES[@]} files to scan (expected >=2) — aborting, refusing false PASS"; exit 2; fi

echo "== Gate #1: engine purity =="
# Denylist: proper nouns + structural secrets that must never appear in engine content.
# Customize the leading terms for YOUR org/people/clients — the trailing regexes catch
# absolute paths and ID/VIN-shaped strings generically. Example terms shown; replace them.
PAT='YourOrg|YourClient|YourName|your-workspace|C:/Users|/Users/|[TCUD]0[A-Z0-9]{8,}|[0-9]{2}[가-힣][0-9]{4}|VIN [A-Z0-9]{11,}'
hits=0
for f in "${FILES[@]}"; do
  if grep -nEi "$PAT" "$f" >/tmp/mm_purity 2>/dev/null; then
    echo "  IMPURE $f:"; sed 's/^/    /' /tmp/mm_purity; hits=$((hits+1))
  fi
done
if [ "$hits" -eq 0 ]; then echo "  OK — engine clean"; else echo "  FAIL — $hits file(s) impure"; fail=1; fi

echo "== Gate #3: placeholder <-> config =="
miss=0
toks=$(grep -rhoE '\{\{[a-z_]+\}\}' "$ENGINE" SKILL.md 2>/dev/null | sed -E 's/\{\{|\}\}//g' | sort -u)
for t in $toks; do
  if echo "$t" | grep -qE "^($ALLOW_PROFILE)$"; then continue; fi   # profile-supplied
  if grep -qE "\{\{$t\}\}" "$CFG"; then :; else echo "  MISSING in $CFG: {{$t}}"; miss=$((miss+1)); fi
done
if [ "$miss" -eq 0 ]; then echo "  OK — all placeholders resolved"; else echo "  FAIL — $miss unresolved"; fail=1; fi

echo "== verify.sh: $([ $fail -eq 0 ] && echo PASS || echo FAIL) =="
exit $fail
