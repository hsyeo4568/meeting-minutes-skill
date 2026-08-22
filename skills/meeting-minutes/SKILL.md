---
name: meeting-minutes
description: "회의록 자동화 엔진 — 녹취(.txt)/노트 → 회의록 작성·공유·정본 저장 원스톱. Use when \"회의록 작성/정리/만들어줘\", minutes 생성, 회의 내용 요약·공유, 데일리/정기/워크샵 회의 산출물 요청. 카테고리별 분기(데일리=팀챗 공유 MD / 정기=Canvas+메일 / 워크샵=Canvas) + Vault 정본·Ontology 연동. config.yaml + profile 구동(범용·교체 가능). NOT for 녹취 원문 오타 교정(→stt-transcript-fix), 표 양식 PPT 회의록(→meeting-minutes-ppt). 도구 부재 시 파일 fallback."
argument-hint: "[source-file | folder]"
---

# meeting-minutes (generic engine)

A **config-driven generic engine** that auto-generates categorized outputs from transcripts/notes.
Proper nouns (org, people, paths, IDs) are **not in this file** — they all live in `config.yaml` + `profiles/<active>/`.
Other companies/projects just fill in their own `config.yaml` and use it as-is.

```
/meeting-minutes [source-file]      # run with a specified file
/meeting-minutes [folder]           # transcript + every material in the folder (decks/sheets/reports)
/meeting-minutes                    # auto-detect latest transcript (work_folder)
```

---

## 0. Boot — load config → detect tools → matrix

At task start, in order:

1. **Load config** — `config.yaml` at skill root. **If absent, run the `ONBOARDING.md` interview first** (batch related questions per message, infer-then-confirm → generate config + profile; see ONBOARDING `배치 원칙`). Do not ask the user to pre-fill a form.
   - `identity` (me/org), `paths` (vault/work_folder), `project.profile`, `categories` matrix, `channels`, `tools`, `locale`.
2. **Load profile** — path from `project.profile` (`profiles/<name>/`). If `null`, skip domain/contact cross-validation (proceed with placeholders).
3. **Detect tools** — for each entry in `config.tools` (slack_mcp/gmail_mcp/qmd/ontology), if set to `auto`, detect at runtime. Missing tools fall back to files (`references/engine/tooling.md`). **Never fail due to a missing tool.** Materials handlers (`config.materials.handlers`) are detected the same way — per ext, first available in the chain wins; an uninstalled entry just yields to the next.
4. **Determine category** — decide which row in config `categories` the meeting falls under first. **Channel confusion is the most common mistake.** Classification may need input signals: build the input manifest + sample the transcript head (pipeline.md phase 1) — do NOT full-read all materials just to classify. Only produce the output flags (detail_md/share_md/canvas/gmail/vault) for that row.
5. **Corrected STT handoff (conditional)** — when the source transcript was processed by `stt-transcript-fix`, create and validate its JSON sidecar with `python scripts/transcript_handoff.py validate --handoff <handoff.json> --transcript <corrected.txt> --glossary <glossary.md>`. Continue to phase 1 only when it returns `eligible: true`. A transcript/glossary hash mismatch, stale or missing fixstamp, pending Tier-B candidate, or Tier-C hold is blocking: surface every blocker and do not compose or publish meeting artifacts. The handoff is a boundary check only; category selection, MD-first approval, canonical save, and `gate → record → verify` remain this engine's responsibility.

> The default category matrix (daily=share, regular=canvas+gmail) reflects one org's convention only — other orgs override via `config.categories`.

---

## 1. Writing principles

Body layout branches on the category's `body_mode` (config `categories.<cat>.body_mode`): `chronological` = agenda items in the order they came up; `axis` = reorganized by discussion axis (`## N.` per axis, `1)` sub-items) — rules in writing-principles §11.

Apply `references/engine/writing-principles.md` before drafting any body text — it owns the full rule set (context-linking, no-tables, segments, owner attribution, real data, symptom headings, AI-smell removal, cross-validation, per-medium formatting). Writing style branches on `locale.business_style` (korean-gaejosik | plain | english).

---

## 2. Pipeline (7 phases)

Full skeleton in `references/engine/pipeline.md`; canonical phase names in `references/engine/CONTRACT.md`. Phases 1.5 (materials comprehension) and 6.5 (topic sync) are optional — omit entirely if the config key / tool is absent. Phase 7 (knowledge-graph) follows `config.ontology.required`: when true it is a normal step of every run, and a missing runner degrades to a saved `.ttl` rather than a skip.

> **Materials are not optional context.** With `config.materials` set, every attached deck/sheet/report in the input folder is digested (phase 1.5) *before* drafting, and the closing summary states which handler read what. Drafting an agenda item from a filename while its deck sat unread in the folder is a failed run, not a shortcut.

> The canonical repository is the source of truth; work_folder outputs are copies. Daily meetings are often MD-first (user reviews/edits the work_folder MD) — let the category set the order.

> **MD-first approval gate (required, all categories) — enforced, not remembered.** Draft MD in the work folder → user review/edits → approval → `python scripts/mm_run.py approve` (immutable snapshot + lease) → phase 6 canonical save → phase 5 canvas/gmail. Every artifact runs `gate → record → verify`, and **only `verify` makes it done**; build the body solely from the `snapshot_path` `gate` returns. Blocking exits: 3 = the MD changed after approval (re-approve, re-derive), 4 = read-back mismatch, 5 = another session holds the lease, 7 = closing with unverified artifacts. Never one turn — unless the user **explicitly pre-approves in the request** (that message = the approval step; gmail stays draft-only). Runner missing (no Python/PyYAML) → prose fallback, never a failed run.
> Full contract: `references/engine/RUNTIME-PROTOCOL.md`. Phase ordering: `pipeline.md`; save order also in profile conventions `초안·정본 저장 순서`.

### Register gate (정기 only)

Before emitting the mail body or Canvas, check both artifacts — they are different registers:

- 회의록 본문 → `개조식-명사종결`
- 메일 본문 → `존댓말-완결문`

```text
<profile-configured prose-lint command> "<artifact-path>" --register "<register-id>" --json
```

Apply the corrections before sharing. For the mail, also invoke `prose-gate` — the linter cannot see 은유, 경구, 드라마 도입, or a rhetorical 대조 균형절.

데일리 (팀즈 MD) is not gated: high volume, internal, and the friction would exceed the value.

---

## 3. Paths and constants (all from config)

| Value | Source |
|---|---|
| Work folder (source transcripts/sheets) | `config.paths.work_folder` |
| Canonical repository path (vault/folder/wiki) | `config.paths.vault` + `config.paths.vault_meetings_subpath` |
| Canonical filename | `<YYYY-MM-DD> <category> <슬러그>.md` (slug based on `config.project.slug`) |
| Vault frontmatter fields | `config.vault_frontmatter.required` |
| Slack workspace/channel/user ID, URL | `config.channels.*` |
| Ontology namespace · entity IRIs · store · runner | `config.ontology.{namespace,entity_namespace,store,runner,runner_env}` |

---

## 4. Fallback / degradation

Detail in `references/engine/tooling.md`. Boot: detect tools → produce only available outputs, **never fail on a missing tool** (every branch has a `.md` fallback). Known-bug fallbacks (no parallel canvas updates, `missing_scope`, `canvas_tab_creation_failed`) also in tooling.md.

---

## 5. Onboarding (new project / new team member)

> **Full install guide: `SETUP.md`** (required/recommended/optional tiers + troubleshooting).

- Environment: `pip install -r requirements.txt` → `python scripts/preflight.py` (must show READY).
- No `config.yaml` → `/meeting-minutes` runs the `ONBOARDING.md` interview (one question at a time, auto-generates config + profile). Manual alternative: copy `config.example.yaml` + `profiles/_template/`, fill in all `<...>`. `profiles/example-acme/` = sanitized format reference.
- Validate before first run: `python scripts/dry_run.py` (**PASS**) + `bash verify.sh` (when modifying the skill — engine purity + placeholder↔config).
- All integrations (Slack/Gmail/qmd) are **optional**; ontology follows `config.ontology.required` — absent → `.md` fallback, not a failure. Detail in `SETUP.md` §3.

> Personal information (real contacts, customer names) goes in `config.yaml` and your own profile — both are `.gitignore`d. Only the engine, `_template`, and `example-acme` go into the shared repo.
> **Language**: Output boilerplate (`# 개요` / `Action Items` / 메일 인사말, etc.) **defaults to Korean**. `locale.language` / `business_style` drives the *prose style* guidance for body text; header/label strings are overridden via the `config.yaml locale.headers` map (e.g. `{"이전 회의 연계 맥락": "Prior Meeting Context"}`) — `build_prompt.py --config` applies it to the generated prompt, and the runtime must honor the same map when emitting deliverables.

---

## References (load only at the relevant phase)

Engine (generic, shared):
- `references/engine/CONTRACT.md` — interface (placeholder vocabulary, canonical phases, purity rules)
- `references/engine/writing-principles.md` — writing principles (context-linking, no-tables, segments, AI-smell removal, cross-validation, per-medium formatting)
- `references/engine/pipeline.md` — 7-phase skeleton
- `references/engine/RUNTIME-PROTOCOL.md` — publish gate: command sequence, exit codes, supersede + failure-record policy (load before any external sharing)
- `references/engine/output-templates.md` — output structure templates (with placeholders)
- `references/engine/tooling.md` — tool detection + degradation matrix + known-bug fallbacks

Profile (replaceable, specialized): `profiles/<active>/{structure,domain-glossary,contacts,conventions}.md` (`FEEDBACK.md` is archived — do not load at runtime; rules are encoded in conventions/structure). **structure.md = meeting shape** (sections, categories, Action grouping, title rules) — the engine does not enforce shape; it comes from here and the interview.

Validation: run `bash verify.sh` from the skill root (engine purity + placeholder↔config gate).
