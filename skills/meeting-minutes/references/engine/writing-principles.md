# Meeting Minutes Writing Principles (generic engine)

> When SKILL/profile is Hemingway-first, this file is not a parent compose pass (Hemingway uses conventions.md).
> Methodology applied when composing meeting minutes body content. All proper nouns, paths, and concrete values use placeholders or neutral examples.
> Style rules branch on a locale condition (`{{business_style}}`) — culture-specific writing conventions are not imposed as universal rules.
> **This file covers only universal writing hygiene, independent of meeting type.** Meeting *form* (section order, categories, Action grouping, titles) belongs to profile `structure.md` (see §Section Order below). §3/§5/§6/§9 lean on *operational-meeting examples* — if they don't fit the meeting type, follow structure.md.

Sections: §1 context-link · §2 locale style · §3 segments · §4 assignee attribution · §5 cross-org data · §6 symptom titles · §7 AI-smell removal · §8 identifier cross-check · §9 no report duplication · §10 abbreviations · §11 body mode (chronological/axis) · §Section-Order→structure.md · §medium labeling

## 1. Context Linking (context-link)

- Before drafting, read the immediately preceding meeting in full + the previous few meetings (profile-configurable count cap, default 3) in link/Action sections only. **Read scope and depth can be narrowed by the profile (profile takes precedence).** Daily immediately-previous = `## 이전 회의 연계` + `## Action Items` only — not the full previous vault note (profile/SKILL win over this default and over pipeline phase 3). Use a per-category count cap, not a calendar window — daily cadence makes a "1–2 weeks" window blow up to ~10 minutes. **Unresolved-issue override:** an open issue older than the cap is still tracked back to the meeting where it opened (carry invariant > count cap) — never drop a live follow-up just because it fell outside the window.
- For each agenda item, explicitly state which prior meeting's unresolved issue it follows up on.
- Add a `## Prior Meeting (date) Context` section at the top, or per-item quotation blocks (`> Prior meeting #N follow-up`).
- Items that are genuinely new — not follow-ups — must be explicitly labeled "신규" (new) so readers can track continuity.

## 2. Writing Style — locale-conditional (`{{business_style}}`)

- When style is `korean-gaejosik` (bullet-style Korean):
  - 3–7 lines per agenda item. Use arrows (→), lists, and noun-ending sentences (명사 종결).
  - No loose translated prose (번역체 풀어쓰기 금지). Quotations: one line of key statement only (if the profile bans quotations outright, profile wins).
  - No tables — Action Items, data, and comparisons all use lists/indentation.
  - No [bracket] labels on sub-item headers.
  - **⚠️ Naturalness > compression (over-compression guard).** 개조식 means abbreviation, not coining new words. If noun-condensation produces **non-standard or awkward neologisms**, revert to natural phrasing. Real correction examples: 곤란→"예측 어려움", 부자연→"자연스럽지 않음", 유리론→"유리할 것으로 판단", "명확 진술"→"명확히 주장", "당장 착수 X"→"대기". Test: **if it sounds unnatural when read aloud, compression has failed** — invented two-syllable Sino-Korean words (e.g. 부자연, 곤란화) and symbol endings (X, △) are prohibited.
  - **Do not over-delete context.** Even short sentences must retain the premises needed for the conclusion to make sense (e.g. "V2G만 단독 운용중", "모빌리티 needs"). Cutting for brevity must not sever cause-and-effect — if it conflicts with §1 context linking, context linking wins.
  - **Preserve stance and hedging.** Proposals and wishes must not be compressed into assertions ("~하라고 전달" ✗ → "~하지 않으면 좋겠다는 의견" ✓). Do not upgrade a statement's certainty level (agreed/proposed/wished) during compression.
- For other styles (e.g. narrative/bulleted-en): follow the conventions of that locale — the above constraints do not apply.
- Common principles (locale-independent): one conclusion per agenda item, remove unnecessary modifiers, facts first. **However, if "remove unnecessary modifiers" strips naturally flowing Korean, that is over-compression — readability wins.**

## 3. Segment Terminology (`{{segments}}`)

- Group by business segment (`{{segments}}`, e.g. B2B/B2C within Org A) instead of listing individual site/location/customer names.
- Readers think in segment units → aggregated grouping is more readable than enumerating individual identifiers.
- Exception: when a specific identifier is the target of an action (see §5 below).

## 4. Assignee Attribution

- For agenda items with a responsible party, include parenthetical attribution in the title: `(이름 직급)` format.
- Action Items: fix accountability with `@담당자 직급` mentions.
- If an assignee is undecided, do not leave `@TBD` — elevate "assignee needs to be designated" as an action item.

## 5. Cross-org Requests Require Operational Data

- When requesting logs/data from another organization (one of `{{orgs}}`), specify identifiers concretely:
  - Target identifier (vehicle X / device Y), timestamp (`2026-01-05 14:03`), observed symptom, our-side response.
- Use indented lists, not tables — the minutes themselves become the request documentation.

## 6. Agenda Titles = Symptom-Based + Quantitative Markers

- For customer/user-facing issues, title them by symptom (observed fact, not inferred cause).
- Quantitative phenomena: include a numeric marker in the title (e.g. "+50% / 6분").
- Avoid abstract category names ("기타 논의") — the title alone should evoke the content.

## 7. Remove AI-isms (machine smell)

- Ban formulaic headers like "핵심 발견 1/2/3", "주요 시사점", "핵심 메시지".
- Embed insights naturally within numbered section body text.
- Eliminate repeated connectives, excessive balance expressions, and unnecessary meta-sentences.

## 8. Identifier Cross-Verification (cross-check)

- Identifiers (vehicle/device numbers) in transcripts and STT are frequently misrecognized.
- Verify against the source-of-truth sheet in the working folder (e.g. the list tab of `issues_260105.xlsx`) before finalizing.
- Before querying the sheet, print sheet names and column names first to verify whitespace/case — schema first.
- If `profile=null`: skip cross-check — keep placeholders or ask the user to confirm.

## 9. Regular Meetings Only — Avoid Duplicating Report Content

- For meetings that accompany a weekly report: do not reproduce figures/tables already in the report.
- Record only the interpretations, judgments, decisions, and follow-up actions derived from those figures — minutes capture "what is not in the report."

## 10. Title/Name Abbreviations

- Compress repeated long names to abbreviations after first use.
- Exception: Action Items section headers use full official names (expand org abbreviations) to prevent ambiguity when shared externally.

## 11. Body Organization Mode — `body_mode`: `chronological` | `axis`

Each category row in config declares `body_mode` (absent ⇒ `chronological`). It governs **how transcript content maps onto the numbered body sections** — nothing else. Section order, Action grouping, and titles still come from profile `structure.md`; §2 style and §7 AI-smell rules apply to both modes.

- **`chronological`** — one numbered section per issue/agenda, in the order it came up. Correct for short, high-cadence operational meetings where "what happened today" *is* the structure. Do not force axes onto them.
- **`axis`** — reorganize by line of discussion. Transcript order is **input, not output**. For deep-dive, multi-party, or external-org meetings where the same question is revisited three times across an hour and a flat list buries the argument.

### Writing an `axis`-mode body

1. **Extract the axes after reading the whole transcript.** An axis = the question or tension the meeting actually argued (`분모를 무엇으로 볼 것인가`), not a topic label (`실효용량`). Aim for 3–6; more than ~7 means the axes are really sub-items.
2. **One top-level number per axis** (`## 1.` `## 2.` …), ordered by weight — decision-bearing axes first, unresolved/carried next, informational last. Never ordered by clock time.
3. **Sub-items use `1)` `2)` `3)`** inside the axis and carry the depth in argument order: 배경·전제 → 주체별 입장 → 쟁점 → 결론. A third level (`-`) exists only for evidence: figures, identifiers, timestamps, error codes.
4. **Relocate, don't append.** An utterance from the opening minutes belongs under whichever axis it argues, even if that axis was otherwise discussed at the end. Merge the scattered fragments of one axis into one place; split a single stretch of talk across axes when it covers two.
5. **Every axis states its landing point** — 결정 / 미합의(양측 입장 그대로 보존) / 보류(재론 시점·조건). An axis that ended nowhere says so explicitly; it is never dropped for lacking a conclusion.
6. **Residue rule.** Anything fitting no axis goes into exactly one trailing `## N. 기타` at one line each. **No section may reproduce transcript order as a fallback.** If 기타 grows past ~3 items, the axis extraction was too coarse — re-extract.
7. **Reorganization must not change certainty.** §2's stance/hedging preservation binds here: regrouping a proposal next to a decision does not make it one, and attribution (`(주체)` labels) survives the move.

## Section Order · Action Grouping → profile structure.md

- **Not fixed.** Section order, Action Items grouping method (by org / by assignee / flat), and categories are determined by profile `structure.md`.
- If structure.md is absent (profile=null): infer structure from transcript and propose to user for confirmation.
- Universal rule only: Action Items must be collected in one place, not scattered through the body (grouping criterion is per structure.md). Future schedule items go in a separate section.

## Title/Role Labeling by Medium

- Shared Canvas / shared MD: name only (omit title) — **applies to attendee lists and body prose only.** Agenda-item assignee parentheticals and Action mentions (§4) include rank by default; if the profile specifies otherwise, profile wins.
- Official docx: name + title.
- Vault frontmatter: name as wikilink.

## Time · Date

- Absolute timestamps only (MM/DD, HH시). Relative expressions like "금일/어제/방금" are prohibited.
- Recording filename timestamp ≠ meeting start time — do not conflate.
- Cross-check STT date misrecognitions before finalizing.

## Expression Refinement

- Translated prose → operational spoken register (if a reader understands it in one pass, colloquial is fine).
- Remove speaker-attribution labels; keep facts only.
- Exclude internal work notes (TBD etc.) from the minutes body.

## Emphasis (inline code)

- Dates, week numbers, deadlines, system field names, API names → backtick inline code.
- Proper nouns for institutions/regulations → remove backticks (not code).
