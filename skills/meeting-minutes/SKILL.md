---
name: meeting-minutes
description: "회의록 자동화 엔진 — 녹취/노트 → 카테고리별 산출물 분기(데일리=팀챗 공유 MD / 정기=Canvas+메일 / 워크샵=Canvas) + 맥락 연계·세그먼트·작성 규칙 + Vault 정본·Ontology 연동. config.yaml + profile 구동(범용·교체 가능). 도구 부재 시 파일 fallback."
---

# meeting-minutes (generic engine)

A **config-driven generic engine** that auto-generates categorized outputs from transcripts/notes.
Proper nouns (org, people, paths, IDs) are **not in this file** — they all live in `config.yaml` + `profiles/<active>/`.
Other companies/projects just fill in their own `config.yaml` and use it as-is.

```
/meeting-minutes [source-file]      # run with a specified file
/meeting-minutes                    # auto-detect latest transcript (work_folder)
```

---

## 0. Boot — load config → detect tools → matrix

At task start, in order:

1. **Load config** — `config.yaml` at skill root. **If absent, run the `ONBOARDING.md` interview first** (ask one question at a time → generate config + profile). Do not ask the user to pre-fill a form.
   - `identity` (me/org), `paths` (vault/work_folder), `project.profile`, `categories` matrix, `channels`, `tools`, `locale`.
2. **Load profile** — path from `project.profile` (`profiles/<name>/`). If `null`, skip domain/contact cross-validation (proceed with placeholders).
3. **Detect tools** — for each entry in `config.tools` (slack_mcp/gmail_mcp/qmd/ontology), if set to `auto`, detect at runtime. Missing tools fall back to files (`references/engine/tooling.md`). **Never fail due to a missing tool.**
4. **Determine category** — decide which row in config `categories` the meeting falls under first. **Channel confusion is the most common mistake.** Only produce the output flags (detail_md/share_md/canvas/gmail/vault) for that row.

> The default category matrix (daily=share, regular=canvas+gmail) reflects one org's convention only — other orgs override via `config.categories`.

---

## 1. Writing principles

Apply `references/engine/writing-principles.md` before drafting any body text — it owns the full rule set (context-linking, no-tables, segments, owner attribution, real data, symptom headings, AI-smell removal, cross-validation, per-medium formatting). Writing style branches on `locale.business_style` (korean-gaejosik | plain | english).

---

## 2. Pipeline (7 phases)

Full skeleton in `references/engine/pipeline.md`; canonical phase names in `references/engine/CONTRACT.md`. Phases 6.5 (topic sync) and 7 (knowledge-graph) are optional — omit entirely if the config key / tool is absent.

> The canonical repository is the source of truth; work_folder outputs are copies. Daily meetings are often MD-first (user reviews/edits the work_folder MD) — let the category set the order.

> **MD-first approval gate (required, all categories):** draft MD in the work folder first → user review/edits → approval → **re-Read the draft from disk and use only that (never regenerate from the in-context draft — silent loss of user edits)** → phase 6 canonical save → phase 5 canvas/gmail. Never one turn; canvas once only (re-share = new canvas + update frontmatter canvas id). Full ordering + per-artifact re-Read obligation in `pipeline.md`; save order also in profile conventions `초안·정본 저장 순서`.

---

## 3. Paths and constants (all from config)

| Value | Source |
|---|---|
| Work folder (source transcripts/sheets) | `config.paths.work_folder` |
| Canonical repository path (vault/folder/wiki) | `config.paths.vault` + `config.paths.vault_meetings_subpath` |
| Canonical filename | `<YYYY-MM-DD> <category> <슬러그>.md` (slug based on `config.project.slug`) |
| Vault frontmatter fields | `config.vault_frontmatter.required` |
| Slack workspace/channel/user ID, URL | `config.channels.*` |
| Ontology namespace | `config.ontology.namespace` |

---

## 4. Fallback / degradation

Detail in `references/engine/tooling.md`. Boot: detect tools → produce only available outputs, **never fail on a missing tool** (every branch has a `.md` fallback). Known-bug fallbacks (no parallel canvas updates, `missing_scope`, `canvas_tab_creation_failed`) also in tooling.md.

---

## 5. Onboarding (new project / new team member)

> **Full install guide: `SETUP.md`** (required/recommended/optional tiers + troubleshooting).

- Environment: `pip install -r requirements.txt` → `python scripts/preflight.py` (must show READY).
- No `config.yaml` → `/meeting-minutes` runs the `ONBOARDING.md` interview (one question at a time, auto-generates config + profile). Manual alternative: copy `config.example.yaml` + `profiles/_template/`, fill in all `<...>`. `profiles/example-acme/` = sanitized format reference.
- Validate before first run: `python scripts/dry_run.py` (**PASS**) + `bash verify.sh` (when modifying the skill — engine purity + placeholder↔config).
- All integrations (Slack/Gmail/qmd/ontology) are **optional** — absent → `.md` fallback, not a failure. Detail in `SETUP.md` §3.

> Personal information (real contacts, customer names) goes in `config.yaml` and your own profile — both are `.gitignore`d. Only the engine, `_template`, and `example-acme` go into the shared repo.
> **Language**: Output boilerplate (`# 개요` / `Action Items` / 메일 인사말, etc.) **defaults to Korean**. `locale.language` / `business_style` drives the *prose style* guidance for body text; header/label strings are overridden via the `config.yaml locale.headers` map (e.g. `{"이전 회의 연계 맥락": "Prior Meeting Context"}`) — `build_prompt.py --config` applies it to the generated prompt, and the runtime must honor the same map when emitting deliverables.

---

## References (load only at the relevant phase)

Engine (generic, shared):
- `references/engine/CONTRACT.md` — interface (placeholder vocabulary, canonical phases, purity rules)
- `references/engine/writing-principles.md` — writing principles (context-linking, no-tables, segments, AI-smell removal, cross-validation, per-medium formatting)
- `references/engine/pipeline.md` — 7-phase skeleton
- `references/engine/output-templates.md` — output structure templates (with placeholders)
- `references/engine/tooling.md` — tool detection + degradation matrix + known-bug fallbacks

Profile (replaceable, specialized): `profiles/<active>/{structure,domain-glossary,contacts,conventions}.md` (`FEEDBACK.md` is archived — do not load at runtime; rules are encoded in conventions/structure). **structure.md = meeting shape** (sections, categories, Action grouping, title rules) — the engine does not enforce shape; it comes from here and the interview.

Validation: run `bash verify.sh` from the skill root (engine purity + placeholder↔config gate).
