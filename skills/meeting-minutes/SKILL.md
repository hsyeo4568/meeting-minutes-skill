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

`body_mode` from config (`chronological` | `axis`). Load `references/engine/writing-principles.md` **only when drafting**. Load profile `conventions.md` (voice / titles / lookback) + `domain-glossary.md` + `contacts.md` at draft/cross-check. Hemingway reads `conventions.md` only — not `conventions-publish.md`. `FEEDBACK.md` is archive — do not load.

Do **not** reread the vault. Context-link = immediately previous meeting + lookback Action/link sections only (`pipeline.md` phase 3). Missing previous → `직전 회의록 미탐지 — 수동 확인 필요`.

## 2. Pipeline — current phase heading only

After approve, do **not** open `pipeline.md` or `RUNTIME-PROTOCOL.md`. Follow §4. For draft/preprocess/materials: open `references/engine/pipeline.md` **at the heading for the phase you are in**, not the whole file. `CONTRACT.md` only if you must check an interface.

- **1.5 materials:** only if the folder has decks/sheets. Digest, don't dump. `python scripts/materials_digest.py`.
- **6.5 topic sync:** only if `config.paths.topics_moc` exists.
- **7 knowledge-graph / ontology: default OFF.** Run only if the user asked. Do not load ontology otherwise. When run, missing runner is fail-close (exit 2), not skip; `load` mints entity notes via targeted sync.

**MD-first (required, all categories):** draft MD in the work folder → user review/edits → approval → `python scripts/mm_run.py approve` (immutable snapshot + lease) → phase 5 dest share-check 0 → create_canvas once → canvas_id → URL → phase 6 vault → gmail. Every artifact: `gate → record → verify`; **only `verify` makes it done**; body solely from `snapshot_path`. Blocking exits: 3 = MD changed after approval, 4 = read-back mismatch, 5 = lease held, 7 = close with unverified artifacts. **One-turn ban is draft only** — never mix draft+share in one turn. After approve, Canvas then vault+Gmail may run in one breath (gmail stays draft-only). Never Canvas/Gmail before approve. **Create canvas once — ban recrate after approve.** No Python/PyYAML → prose fallback, never a failed run.

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

## 4. Share (phase 5) — after approve only

MD-first one-turn ban is **draft only**. After approve, Canvas then vault+Gmail may run in one breath. Never mix draft+share. Never Canvas/Gmail before approve. **Create canvas once. Ban recrate after approve.**
Phase 5 **remaps** `gate`'s `snapshot_path` only. Do not Read the transcript, materials, glossary, contacts, `writing-principles.md`, or a gold sent mail.
- canvas: heading remap to a work-folder `.md`. `create_canvas` is title+content only (`dm_user_id` is gone; `user_ids` is record-only). Pass `content` from that Path. Path.read_text still wraps in tool JSON (dest unbound; do not patch canvas.ts). Never retype Korean.
**Order after approve:** (1) dest `share-check` (`destination` = `{{slack_user_id}}`, not bot DM, not `user_ids`-only) Exit 8 **before** any `create_canvas` (2) snapshot Path `create_canvas` once (3) `canvas_id` then live `read_canvas` — user must open. Plan dest is not create dest. 권한 없음 → stop, no Recreate, no URL, no 완료 (4) URL only if `openable` (5) **then** vault. Vault must not delay the URL.
- gmail: same facts, 개조식→존댓말. Daily envelope from `gmail_envelope` / `conventions-publish.md` — do not reread a gold sent mail. Draft-only.
**Harness:** dest `python scripts/mm_run.py share-check --plan <plan.json> --config config.yaml` **before create**. After create: live `read_canvas` then share-check with `canvas_id` + `openable` **before URL**. Exit 8 = blocked (bot DM / missing dest / not openable / missing `user_ids` / unconfirmed draft). Never dest `{{slack_bot_dm_id}}`. dest = `{{slack_user_id}}` (never empty, never `user_ids`-only). No `create_canvas` on Exit 8. 권한 없음 after one create = stop, not Recreate, not URL-as-success. Ban recrate after approve. Do not say 완료.
Do not load `RUNTIME-PROTOCOL.md` or `tooling.md` at share unless share-check fails.

## 5. Onboarding (not a runtime read)

No `config.yaml` → `ONBOARDING.md`. `SETUP.md` is install-only. `python scripts/preflight.py` must show READY. Changing the skill: `python scripts/dry_run.py` + `bash verify.sh`. Personal data stays in gitignored `config.yaml` + profile. Labels default Korean; `locale.headers` overrides.

## References (load only at the named phase)

- `writing-principles.md` — draft
- `pipeline.md` — current phase heading (draft only; not after approve)
- `CONTRACT.md` — interface, on demand
- `RUNTIME-PROTOCOL.md` / `tooling.md` — only if share-check fails
- `output-templates.md` — share form remap (not a re-draft)
- profile `structure.md` — classify; `conventions.md` — draft/Hemingway; `conventions-publish.md` — share envelope; `domain-glossary` / `contacts` — draft
