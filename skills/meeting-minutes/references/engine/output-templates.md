# Output Templates (per-category deliverable structures)

> GENERIC structures only. ZERO proper nouns. Fill specifics from config.yaml + profile.
> Tokens used here: `{{project_name}}` `{{orgs}}` `{{slack_url_base}}` `{{slack_workspace_id}}`
> `{{slack_channel_id}}`. Example bodies use neutral fakes (`Org A`, `이름`) — never real names.

The `categories` matrix in config decides which of these a given meeting emits.

---

## share_md — plain-text 팀챗 공유본 (e.g. Teams)

파일명: `YYMMDD_<category>_공유.md`. detail_md에서 내부 멘션 제거 + 압축한 형태.
제목·라벨 형식은 **profile structure.md §산출물 제목 규칙이 정본** — 아래 예시 첫 줄은 중립 예시일 뿐 그대로 쓰지 말 것.

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

금지: 이모지 일체, 마크다운 굵기 `**`, 헤더 기호 `#`, 마크다운 표 `| |`, 코드펜스.
규칙:
- 최상위 섹션 헤더만 plain text (`주요 논의 내용`, `Action Items`).
- 개별 안건은 `1. 제목` 순번 — 주제별 `[대괄호]` 그룹핑 금지.
- 안건 사이 빈 줄 1개 필수 (리스트 깨짐 방지).
- 들여쓰기 `2칸 + - `(1단계) / `4칸 + · `(2단계).
- 멘션·직책 표기는 **profile 호칭 규칙이 정본** (기본 `@담당자 직급`; profile이 이름만 지시하면 그에 따름).
- Action Items는 조직별 그룹 + 끝에 `(시점/주기)`.
- 완료 항목은 `~~취소선~~`.

---

## detail_md — 작업폴더 상세본 (vault 정본의 사본)

파일명: `YYMMDD_<category>.md`. share_md보다 풍부 — 오류코드/타임스탬프 전부 보존.

```
# <category> 회의록 (M/D 요일)

- 일시: YYYY-MM-DD HH:MM
- 참석: 이름(Org A), 이름(Org B)
- 불참: 이름(Org A)

## 이전 회의(M/D) 연계 맥락
> 직전 1-2주 회의에서 이어진 안건 요약.

## 핵심 논의

## 1. 안건 제목 (담당자)
본문.
> 연계 인용블록: 이전 회의 발언/결정 그대로 인용.
- 세부: 오류코드 `E-XXX`, 타임스탬프 `HH:MM:SS` 등 원자료 전부.

## Action Items
(share_md와 동일 구조, 단 내부 멘션 포함)
```

share_md = 이 상세본에서 내부 멘션 제거 + 1줄 요약으로 압축.

---

## canvas — 정기/워크샵 검토 표면

표 절대 금지 — Action Items 포함 전부 체크박스 리스트.
최상위 3단 구조: `# 개요` / `# 논의 내용` / `# Action Items`. "핵심 발견" 류 AI 헤더 금지.

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

공유 URL 형식: `{{slack_url_base}}/docs/{{slack_workspace_id}}/<canvas_id>`
(도구가 반환하는 웹 UI URL 형식 그대로 주지 말 것 — 위 `/docs/` 형식으로 변환).
채널 게시 시 `{{slack_channel_id}}` 사용.

---

## gmail — 회의록 메일 초안

> ⚠️ **메일 본문 형태(제목·인사·본문 depth·맺음말·멘션 표기)는 조직마다 완전히 다름 → profile이 정본.**
> `profiles/<active>/conventions.md` §채널 관례의 Gmail 템플릿을 **반드시 Read 후 그대로** 따른다.
> profile에 Gmail 템플릿이 없으면(또는 profile=null) 아래 generic 최소본 사용 + **직전 sent 메일 미러**.

```
제목: [{{project_name}}] <category> 회의록 공유드립니다. (라벨, M/D)
받는사람 / 참조: profile contacts 매핑

인사(고정 문구는 profile) → 회의록 본문 → Action Items(조직별) → 맺음(고정 문구는 profile)
```

- **회의록 메일 = 본문에 회의록 전문(full body).** 요약본·"Canvas 링크만" 1줄은 금지 — 깊이 기준 = **직전 sent 회의록 메일**(최신 1건만 Read 후 미러, 그 외 재독 금지). 첨부(리포트)는 인사말 안내만.
- 표 금지, 목록/체크리스트로. 수신/참조는 profile contacts 매핑으로 채움. `create_draft`는 plain 이메일만(`이름 <메일>` 형식 불가).
- contacts에 없는 참석자는 수신란에 `[미확인: 이름]` placeholder로 명시 출력 — 임의 추측·조용한 누락 금지 (사용자가 초안 검토에서 채움).

---

## vault — 정본

frontmatter는 `config.vault_frontmatter.required` 필드로 구성.
본문 섹션 순서 (고정):

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

저장 후 qmd 사용 가능 시 인덱싱, ontology 사용 가능 시 decisions/relations 기록.
