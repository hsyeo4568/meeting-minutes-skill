#!/usr/bin/env python3
"""Dry-run: boot the meeting-minutes engine with config.yaml + profile, no side effects.
Validates: config parses, every engine {{token}} resolves to a concrete value,
profile files load, degradation (tools off) yields file-only plan."""
import sys, re, pathlib
sys.stdout.reconfigure(encoding="utf-8")
try:
    import yaml
except ImportError:
    print("FAIL: PyYAML not installed (pip install pyyaml)"); sys.exit(2)

ROOT = pathlib.Path(__file__).resolve().parent.parent
fail = 0

# 1. config parses
cfg_path = ROOT / "config.yaml"
if not cfg_path.exists():
    print("FAIL: config.yaml missing -> cp config.example.yaml config.yaml 후 값 채우기"); sys.exit(1)
cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
print(f"== config.yaml parsed OK — project={cfg['project']['name']} me={cfg['identity']['me']}")

# 2. token -> config value map (mirrors CONTRACT.md vocabulary)
def g(*ks):
    v = cfg
    for k in ks: v = v[k]
    return v
TOKMAP = {
    "me": g("identity","me"), "org": g("identity","org"),
    "project_name": g("project","name"), "project_slug": g("project","slug"),
    "vault_path": g("paths","vault"), "work_folder": g("paths","work_folder"),
    "vault_meetings_subpath": g("paths","vault_meetings_subpath"),
    "slack_workspace_id": g("channels","slack_workspace_id"),
    "slack_channel_id": g("channels","slack_channel_id"),
    "slack_user_id": g("channels","slack_user_id"),
    "slack_url_base": g("channels","slack_url_base"),
    "language": g("locale","language"), "business_style": g("locale","business_style"),
}
PROFILE_SUPPLIED = {"segments","orgs"}

# 3. collect tokens used by engine + SKILL, confirm each resolves to concrete value
files = [f for f in (ROOT/"references"/"engine").glob("*.md")
         if f.name != "CONTRACT.md"] + [ROOT/"SKILL.md"]  # CONTRACT.md = spec prose
used = set()
for f in files:
    used |= set(re.findall(r"\{\{([a-z_]+)\}\}", f.read_text(encoding="utf-8")))
print(f"== engine uses {len(used)} placeholder tokens")
for t in sorted(used):
    if t in PROFILE_SUPPLIED:
        continue
    val = TOKMAP.get(t)
    if val is None:
        print(f"  UNRESOLVED: {{{{{t}}}}} has no config mapping"); fail = 1
    elif "<" in str(val) or str(val).strip() == "":   # catches "<...>" anywhere, e.g. projects/<slug>/meetings
        print(f"  PLACEHOLDER LEFT: {{{{{t}}}}} = {val!r} (config not filled)"); fail = 1
if not fail:
    print("  all tokens resolve to concrete config values")

# 4. profile loads
prof = ROOT / cfg["project"]["profile"]
need = ["domain-glossary.md","contacts.md","conventions.md"]
missing = [n for n in need if not (prof/n).exists()]
print(f"== profile {cfg['project']['profile']}: " +
      ("OK" if not missing else f"MISSING {missing}"))
if missing: fail = 1

# 5. degradation: all tools off -> file-only plan for a 'daily' meeting
print("== degradation dry-run (tools all OFF, category=daily)")
cat = cfg["categories"]["daily"]
plan = []
for d, on in cat.items():
    if not on or on == "optional":  # optional skipped when tool absent
        continue
    if d == "canvas":  plan.append("canvas -> .md fallback (slack off)")
    elif d == "gmail": plan.append("gmail -> .md fallback (gmail off)")
    else:              plan.append(f"{d} -> file")
print("  outputs:", ", ".join(plan) if plan else "(none)")
print("  -> file-only, no errors" )

print("\nDRY-RUN:", "PASS" if not fail else "FAIL")
sys.exit(fail)
