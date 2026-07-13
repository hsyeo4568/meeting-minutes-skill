# Output Templates (per-category deliverable structures)

> GENERIC structures only. ZERO proper nouns. Fill specifics from config.yaml + profile.
> Tokens used here: `{{project_name}}` `{{orgs}}` `{{slack_url_base}}` `{{slack_workspace_id}}`
> `{{slack_channel_id}}`. Example bodies use neutral fakes (`Org A`, `이름`) — never real names.
> Header strings in templates are defaults — if config `locale.headers` provides overrides, use those.

The `categories` matrix in config decides which of these a given meeting emits.

Deliverable templates in this file:
- [`share_md`](#share_md) — plain-text team-chat share copy
- [`detail_md`](#detail_md) — full working-folder copy (source of truth for vault)
- [`canvas`](#canvas) — periodic / workshop review surface
- [`gmail`](#gmail) — meeting-minutes mail draft
- [`vault`](#vault) — authoritative copy

> Title/label + honorific notation across ALL blocks: the active **profile `structure.md` §산출물 제목** is the single authority — templates here show neutral illustrations only.

---

## share_md — plain-text team-chat share copy (e.g. Teams)

Filename: `YYMMDD_<category>_공유.md`. Derived from detail_md with internal mentions removed and compressed.
Title/label format: **profile structure.md §산출물 제목 규칙 is the authoritative source** — the example first line below is a neutral illustration only; do not use it verbatim.

```
(Daily, M/D) {{project_name}} 데일리 이슈 회의

주요 논의 내용

1. 안건 제목 (담당자) — 연계 시 "M/D 정기 N 후속"
본문 1줄 핵심 요약
 - 세부 항목
   · 더 깊은 들여쓰기

2. 다음 안건 제목 (담당자)
본문 1줄 핵심 요약

Action Items

Org A
- 항목 (to.담당자) / 완료 시 ~~취소선~~

Org B
- 항목 (to.기관)
```

Prohibited: all emoji, markdown bold `**`, header symbols `#`, markdown tables `| |`, code fences.
Rules:
- Top-level section headers are plain text only (`주요 논의 내용`, `Action Items`).
- Individual agenda items use `1. 제목` numbering — `[bracket]` grouping by topic is prohibited.
- One blank line between agenda items is mandatory (prevents list-rendering breakage).
- Indentation: `2 spaces + - ` (level 1) / `4 spaces + · ` (level 2).
- Mention/title notation: **profile honorific rules are authoritative** (default `@담당자 직급`; follow profile if it specifies name-only).
- Action Items: group by org + append `(시점/주기)` at the end.
- Completed items: `~~취소선~~`.

---

## detail_md — full working-folder copy (source of truth for vault)

Filename: `YYMMDD_<category>.md`. Richer than share_md — preserve all error codes and timestamps.

```
# <category> 회의록 (M/D 요일)

- 일시: YYYY-MM-DD HH:MM
- 참석: 이름(Org A), 이름(Org B)
- 불참: 이름(Org A)

## 이전 회의(M/D) 연계 맥락
> 직전 N건(context_lookback) 회의에서 이어진 안건 요약 + 미해소 이슈 carry.

## 핵심 논의

## 1. 안건 제목 (담당자)
본문.
> 연계 인용블록: 이전 회의 발언/결정 그대로 인용.
- 세부: 오류코드 `E-XXX`, 타임스탬프 `HH:MM:SS` 등 원자료 전부.

## Action Items
(same structure as share_md, but internal mentions included)
```

---

## canvas — periodic / workshop review surface

Tables absolutely prohibited — Action Items and all content must use checkbox lists.
Top-level three-section structure: `# 개요` / `# 논의 내용` / `# Action Items`. AI-generated headers such as "핵심 발견" are prohibited.

```
# 개요
- 일시 / 참석 / 안건 요약

# 논의 내용
## 1. 섹션 제목
- 내용

## 2. 섹션 제목
- 내용

# Action Items
### Org A
- [ ] 항목 — 담당 `기한`
### Org B
- [ ] 항목 — 담당 `기한`

# 일정 (있을 때만)
- YYYY-MM-DD 이벤트명·내용
```

Share URL format: `{{slack_url_base}}/docs/{{slack_workspace_id}}/<canvas_id>`
(Do not use the web UI URL format returned by the tool as-is — convert it to the `/docs/` format above.)
Use `{{slack_channel_id}}` when posting to a channel.

---

## gmail — meeting-minutes mail draft

> ⚠️ **Mail body form (subject, greeting, body depth, closing, mention notation) differs completely by org → profile is authoritative.**
> Read `profiles/<active>/conventions.md` §채널 관례's Gmail template **exactly as-is** before following it.
> If the profile has no Gmail template (or profile=null), use the generic minimal skeleton below + **mirror the most recent sent mail**.

```
제목: [{{project_name}}] <category> 회의록 공유드립니다. (라벨, M/D)
받는사람 / 참조: profile contacts 매핑

인사(고정 문구는 profile) → 회의록 본문 → Action Items(조직별) → 맺음(고정 문구는 profile)
```

- **Meeting-minutes mail = full meeting-minutes body in the mail body.** A summary-only or "Canvas link only" single line is prohibited — depth standard = **the most recent sent meeting-minutes mail** (Read only the latest 1 item then mirror; do not re-read others). Attachments (reports) are announced in the greeting only.
- Tables prohibited; use lists/checklists. To/CC filled from profile contacts mapping. `create_draft` accepts plain email only (the `이름 <메일>` format is not supported).
- Attendees not found in contacts must be explicitly printed in the To field as `[미확인: 이름]` placeholder — no guessing or silent omission (the user fills them in during draft review).

---

## vault — authoritative copy

Frontmatter is composed from `config.vault_frontmatter.required` fields.
Body section order (fixed):

```
---
(config.vault_frontmatter.required 필드)
---

# 개요

## 이전 회의 연계

## 핵심 논의

## 1. 안건

## 2. 안건

## Action Items
### Org A
- [ ] 항목 — 담당 `기한`
### Org B
- [ ] 항목 — 담당 `기한`

## 일정
```

After saving, index with qmd if available; record decisions/relations with ontology if available.
