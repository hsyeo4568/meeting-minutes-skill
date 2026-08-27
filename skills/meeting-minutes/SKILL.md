---
name: meeting-minutes
description: "회의록 자동화 엔진 — 녹취(.txt)/노트 → 회의록 작성·공유·정본 저장. Use when \"회의록 작성/정리/만들어줘\", minutes 생성, 데일리/정기/워크샵 산출물. 카테고리 분기(데일리=팀챗 MD / 정기=Canvas+메일 / 워크샵=Canvas) + Vault 정본. config.yaml + profile. NOT 녹취 원문 교정(→stt-transcript-fix), 표 양식 PPT(→meeting-minutes-ppt). 도구 없으면 파일 fallback."
argument-hint: "[source-file | folder]"
---

# meeting-minutes (generic engine)

Config-driven engine. Proper nouns live in `config.yaml` + `profiles/<active>/`, not here.

```
/meeting-minutes [source-file]
/meeting-minutes [folder]
/meeting-minutes
```

## 0. Boot — config → category (stop; do not dump the rest)

**Stop after this section.** Do not Read writing-principles / pipeline / CONTRACT / RUNTIME-PROTOCOL / tooling / SETUP / the vault / glossary / contacts / ontology until a later phase names them.

1. **config.yaml** at skill root. Absent → `ONBOARDING.md` interview. Keys: `identity`, `paths`, `project.profile`, `categories`, `channels`, `tools`, `locale`.
2. **Category first.** Sample transcript head (~50 lines) + filename — do not full-read materials to classify. Emit only that row's flags (detail_md/share_md/canvas/gmail/vault).
3. **Profile (narrow):** `profiles/<name>/structure.md` for category signals only. If `project.profile` is null, placeholders.
4. **Tools:** detect only what the category row needs (`slack_mcp` / `gmail_mcp`). **Do not detect `ontology` or `qmd` at boot. Do not run phase 7.** Missing tool → file fallback. Never fail on a missing tool.

## 1. Draft — writing rules then, not before

`body_mode` from config (`chronological` | `axis`). Load `references/engine/writing-principles.md` **only when drafting**. Load profile `conventions.md` + `domain-glossary.md` + `contacts.md` at draft/cross-check. `FEEDBACK.md` is archive — do not load.

Do **not** reread the vault. Context-link = immediately previous meeting + lookback Action/link sections only (`pipeline.md` phase 3). Missing previous → `직전 회의록 미탐지 — 수동 확인 필요`.

## 2. Pipeline — current phase heading only

Open `references/engine/pipeline.md` **at the heading for the phase you are in**, not the whole file. `CONTRACT.md` only if you must check an interface.

- **1.5 materials:** only if the folder has decks/sheets. Digest, don't dump. `python scripts/materials_digest.py`.
- **6.5 topic sync:** only if `config.paths.topics_moc` exists.
- **7 knowledge-graph / ontology: default OFF.** Run only if the user asked. Do not load ontology otherwise. When run, missing runner is fail-close (exit 2), not skip; `load` mints entity notes via targeted sync.

**MD-first (required, all categories):** draft MD in the work folder → user review/edits → approval → `python scripts/mm_run.py approve` (immutable snapshot + lease) → phase 6 canonical save → phase 5 canvas/gmail. Every artifact: `gate → record → verify`; **only `verify` makes it done**; body solely from `snapshot_path`. Blocking exits: 3 = MD changed after approval, 4 = read-back mismatch, 5 = lease held, 7 = close with unverified artifacts. Never one turn unless the user **explicitly pre-approves in the request** (gmail stays draft-only). No Python/PyYAML → prose fallback, never a failed run. Full contract: `RUNTIME-PROTOCOL.md` — load **before share**, not at boot.

### Register gate (정기 only)

- 회의록 본문 → `개조식-명사종결`
- 메일 본문 → `존댓말-완결문`

```bash
python prose_lint.py "<path>" --register "<id>" --json
```

Apply corrections before sharing. For mail, also `prose-gate` (은유/경구/드라마 도입). 데일리 팀즈 MD is not gated.

## 3. Paths (all from config)

| Value | Source |
|---|---|
| Work folder | `config.paths.work_folder` |
| Canonical store | `config.paths.vault` + `config.paths.vault_meetings_subpath` |
| Canonical filename | `<YYYY-MM-DD> <category> <슬러그>` (`config.project.slug`) |
| Vault frontmatter | `config.vault_frontmatter.required` |
| Slack IDs / URL | `config.channels.*` |

## 4. Share (phase 5) — load tooling here

Load `references/engine/tooling.md` and `RUNTIME-PROTOCOL.md` **before creating anything**, not at boot.

Phase 5 **remaps** the approved snapshot — it is not a new draft. Body from `gate`'s `snapshot_path` only. Do not Read the transcript, materials, glossary, contacts, or `writing-principles.md`.
- canvas: heading remap, 개조식 유지. Do not invent sections.
- vault: copy snapshot body + frontmatter. Do not restack.
- gmail: same facts, 개조식→존댓말; greeting/closing from profile or **one** latest sent minutes mail (envelope only).

Share-time hard rules (phase 5) — load `tooling.md` before creating anything:
- Slack canvas: `dm_user_id` + `user_ids` = `config.channels.slack_user_id`. Never `channel_id` unless the user asked to auto-post. Never `{{slack_bot_dm_id}}` as destination (user cannot view those canvases). A URL the user cannot open is not done.
- Gmail: create a draft, then confirm a draft id. No id → write `.eml` to the work folder and say so. Never report 임시보관함 without an id. Do not fetch prior threads with `FULL_CONTENT`.
- **Harness (required):** before claiming canvas/gmail success, write the destination plan JSON and run `python scripts/mm_run.py share-check --plan <plan.json> --config config.yaml`. Exit 8 = blocked (bot DM / missing `user_ids` / unconfirmed draft). Do not say 완료. Recreate with `user_ids: [{{slack_user_id}}]` or keep the `.eml`.

## 5. Onboarding (not a runtime read)

No `config.yaml` → `ONBOARDING.md`. `SETUP.md` is install-only. `python scripts/preflight.py` must show READY. Changing the skill: `python scripts/dry_run.py` + `bash verify.sh`. Personal data stays in gitignored `config.yaml` + profile. Labels default Korean; `locale.headers` overrides.

## References (load only at the named phase)

- `writing-principles.md` — draft
- `pipeline.md` — current phase heading
- `CONTRACT.md` — interface, on demand
- `RUNTIME-PROTOCOL.md` — before share
- `output-templates.md` — share form remap (not a re-draft)
- `tooling.md` — before canvas/gmail
- profile `structure.md` — classify; `conventions` / `domain-glossary` / `contacts` — draft
