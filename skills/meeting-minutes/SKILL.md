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

Apply `references/engine/writing-principles.md` before drafting any body text. Key points: context-linking is mandatory / no tables, use lists / segment terminology (`{{segments}}`) / always name the owner / include real data for cross-org requests / symptom-and-quantified headings / remove AI smell / cross-validate identifiers against source-of-truth / title, time, and emphasis formatting per medium.
Writing style branches on `locale.business_style` (korean-gaejosik | plain | english) — korean-gaejosik is the Korean business convention option.

---

## 2. Pipeline (7 phases)

Detail in `references/engine/pipeline.md`. Phase names are canonical in `references/engine/CONTRACT.md`.

1. Preprocess — text/PDF/audio (Whisper). Slides: python-pptx first.
2. Speaker ID + clean — map speakers (`{{me}}`=self), strip filler words.
3. Context-link + draft — Read last 1–2 weeks of minutes → link → body (writing-principles) → cross-validate identifiers.
4. Per-category deliverables — apply config matrix (`references/engine/output-templates.md`).
5. Share routing — share_md / canvas / gmail per category. Fall back to `.md` if tool unavailable.
6. Canonical save — save to canonical repository (config.paths.vault — notes vault, document folder, wiki, etc.) with frontmatter (config.vault_frontmatter) → (optional) embed if indexer available.
6.5. Topic sync (optional) — if `config.paths.topics_moc` exists: compare trigger keywords in the registry table against the minutes body → for matching topic notes, append one line to `## 타임라인` (`- **date** [[minutes]]: figure|hypothesis|decision` format, append-only) + update `last_updated` and MOC table. Rewrite `## 현재 상태` only for meetings where conclusions changed. For newly recurring topics (3+ appearances), propose creating a new note to the user — do not create automatically. Omit this phase entirely if the config key is absent.
7. Knowledge-graph update (optional) — record decisions/relationships (via ontology skill interface only). Omit entirely if tool unavailable; not required for a valid run.

> The canonical repository is the source of truth. Outputs in work_folder are copies. For daily meetings, users often review and edit the work_folder MD themselves first (MD-first) — let the category determine the order.

> **MD-first approval gate (required, all categories):** In turn 1, **generate the draft MD first in the work folder (the meeting folder the user provided)** → wait for user review and edits → **only after edits are incorporated and approval is given: save the canonical version (phase 6) + generate canvas/gmail (phase 5) — immediately after approval, re-Read the draft MD from disk and use only that re-Read version as the source (never regenerate from the in-context draft).** Do not push to vault at the draft stage. Do not produce everything in one turn. Canvas must be created only once (re-sharing requires a new canvas + updating the frontmatter canvas id). Detail in `references/engine/pipeline.md` + profile conventions `초안·정본 저장 순서`.

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

Detail in `references/engine/tooling.md`. Summary: detect tools at boot → produce only available outputs. No Slack → output canvas as `.md` / no Gmail → output mail body as `.md` / no qmd → skip indexing / no ontology → skip phase 7 / no profile → skip cross-validation. Includes fallbacks for known bugs: no parallel canvas updates, `missing_scope`, `canvas_tab_creation_failed`, etc.

---

## 5. Onboarding (new project / new team member)

> **Full follow-along installation guide: `SETUP.md`** (required/recommended/optional tiers + troubleshooting). The below is a summary.

0. Environment: `pip install -r requirements.txt` → `python scripts/preflight.py` (must show READY).
1. **Recommended — interview:** Run `/meeting-minutes` with no `config.yaml` → `ONBOARDING.md` interview asks **one question at a time** and auto-generates config + profile. Starts with "tell me about one meeting you have" rather than asking for a form upfront.
2. (Manual alternative) Copy `config.example.yaml` → `config.yaml` and `profiles/_template/` → `profiles/<your-name>/`, then fill everything in. Replace all `<...>` values.
3. `profiles/example-acme/` = a filled-in **sanitized example** — for reference on format only (not real data).
4. **Validation (required before first run):**
   - `python scripts/dry_run.py` → loads config + profile, detects unresolved blanks. Must show **PASS**.
   - `bash verify.sh` → (when modifying the skill) engine purity + placeholder↔config gate.

> All integrations (Slack/Gmail/qmd/ontology) are **fully optional** — if absent, outputs fall to `.md` (not a failure). Slack/qmd/ontology are bespoke local tools for the primary author; team members typically run without them. Detail in `SETUP.md` §3.

> Personal information (real contacts, customer names) goes in `config.yaml` and your own profile — both are `.gitignore`d. Only the engine, `_template`, and `example-acme` go into the shared repo.
> **Language**: Output boilerplate (`# 개요` / `Action Items` / 메일 인사말, etc.) is currently **fixed in Korean**. `locale.language` / `business_style` affects the *prose style* guidance for body text, but output header i18n is not yet supported (English-language orgs need to replace the template strings directly). Known limitation.

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
