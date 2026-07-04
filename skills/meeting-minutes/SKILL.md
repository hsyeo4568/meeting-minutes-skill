---
name: meeting-minutes
description: "회의록 자동화 엔진 — 녹취/노트 → 카테고리별 산출물 분기(데일리=팀챗 공유 MD / 정기=Canvas+메일 / 워크샵=Canvas) + 맥락 연계·세그먼트·작성 규칙 + Vault 정본·Ontology 연동. config.yaml + profile 구동(범용·교체 가능). 도구 부재 시 파일 fallback."
---

# meeting-minutes (generic engine)

녹취/노트 → 카테고리별 산출물까지 자동 생성하는 **config 구동 범용 엔진**.
고유명사(조직·인물·경로·ID)는 **이 파일에 없음** — 전부 `config.yaml` + `profiles/<active>/`에 있다.
다른 회사/프로젝트는 자기 `config.yaml`만 채우면 그대로 쓴다.

```
/meeting-minutes [원본기록파일]      # 지정 파일로 작성
/meeting-minutes                     # 최근 녹취 자동 탐지(work_folder)
```

---

## 0. 부팅 — config 로드 → 도구 감지 → 매트릭스

작업 시작 시 순서대로:

1. **config 로드** — 스킬 루트의 `config.yaml`. **없으면 `ONBOARDING.md` 인터뷰를 먼저 실행**(한 번에 하나씩 질문 → config + profile 생성). 폼 미리 채우라 시키지 말 것.
   - `identity`(me/org), `paths`(vault/work_folder), `project.profile`, `categories` 매트릭스, `channels`, `tools`, `locale`.
2. **profile 로드** — `project.profile` 경로(`profiles/<name>/`). `null`이면 도메인/연락처 교차검증 생략(placeholder로 진행).
3. **도구 감지** — `config.tools`의 slack_mcp/gmail_mcp/qmd/ontology를 `auto`면 런타임 감지. 없는 도구는 파일 fallback(`references/engine/tooling.md`). **도구 부재로 실패하지 않는다.**
4. **카테고리 판별** — 회의가 config `categories` 중 어느 행인지 먼저 결정. **채널 혼동이 가장 잦은 실수.** 그 행의 산출물 플래그(detail_md/share_md/canvas/gmail/vault)만 만든다.

> 카테고리 매트릭스 default(daily=share, regular=canvas+gmail)는 한 조직의 관례일 뿐 — 타 조직은 `config.categories`로 덮어쓴다.

---

## 1. 작성 원칙

본문 작성 전 `references/engine/writing-principles.md` 적용. 핵심: 맥락 연계 필수 / 표 금지·목록 / 세그먼트 용어(`{{segments}}`) / 담당자 명시 / 크로스조직 요청엔 실데이터 / 증상·정량 제목 / AI 냄새 제거 / 식별자 source-of-truth 교차검증 / 매체별 직책·시간·강조 표기.
문체는 `locale.business_style`(korean-gaejosik | plain | english)로 분기 — 개조식은 한국 비즈니스 관례 옵션.

---

## 2. 파이프라인 (7 단계)

상세 `references/engine/pipeline.md`. 단계명은 `references/engine/CONTRACT.md` 정본.

1. Preprocess — 텍스트/PDF/오디오(Whisper). 슬라이드는 python-pptx 먼저.
2. Speaker ID + clean — 화자 매핑(`{{me}}`=나), 추임새 제거.
3. Context-link + draft — 직전 1~2주 회의록 Read → 연계 → 본문(writing-principles) → 식별자 교차검증.
4. Per-category deliverables — config 매트릭스 적용(`references/engine/output-templates.md`).
5. Share routing — 카테고리별 share_md / canvas / gmail. 도구 없으면 `.md` fallback.
6. Canonical save — 정본 저장소(config.paths.vault — 노트 vault·문서 폴더·위키 등)에 frontmatter(config.vault_frontmatter)로 저장 → (선택) 인덱서 가용 시 embed.
7. Knowledge-graph update (선택) — 결정/관계 기록(ontology 스킬 인터페이스만). 도구 없으면 통째로 생략, 유효 실행에 필수 아님.

> 정본 저장소가 source of truth. work_folder 산출물은 사본. 데일리는 사용자가 work_folder MD를 먼저 보고 직접 손보는 경우 많음(MD-first) — 카테고리에 맞춰 순서 결정.

> **MD-first 승인 게이트 (필수, 전 카테고리):** 1턴엔 **초안 MD를 작업폴더(사용자가 준 회의 폴더)에 먼저** 생성 → 사용자 검토·수정 대기 → **수정 반영·승인 후에만 vault 정본(phase 6) 저장 + canvas/gmail(phase 5) 생성.** 초안 단계에서 vault에 먼저 넣지 말 것. 한 턴에 몰아 만들지 말 것. canvas는 1회만 생성(재공유는 새 canvas + frontmatter canvas id 갱신). 상세 `references/engine/pipeline.md` + profile conventions `초안·정본 저장 순서`.

---

## 3. 경로·상수 (전부 config)

| 값 | 출처 |
|---|---|
| 작업폴더(원본 녹취/시트) | `config.paths.work_folder` |
| 정본 저장소 경로(vault·폴더·위키) | `config.paths.vault` + `config.paths.vault_meetings_subpath` |
| 정본 파일명 | `<YYYY-MM-DD> <category> <슬러그>.md` (슬러그 = `config.project.slug` 기반) |
| Vault frontmatter 필드 | `config.vault_frontmatter.required` |
| Slack workspace/channel/user ID, URL | `config.channels.*` |
| Ontology 네임스페이스 | `config.ontology.namespace` |

---

## 4. Fallback / degradation

상세 `references/engine/tooling.md`. 요지: 시작 시 도구 감지 → 가용 산출물만 생성. slack 없음→canvas `.md` 출력 / gmail 없음→메일 본문 `.md` 출력 / qmd 없음→인덱싱 생략 / ontology 없음→phase 7 생략 / profile 없음→교차검증 생략. Canvas 병렬 update 금지·`missing_scope`·`canvas_tab_creation_failed` 등 알려진 버그 fallback 포함.

---

## 5. 온보딩 (새 프로젝트/팀원)

> **전체 follow-along 설치 가이드: `SETUP.md`** (필수/권장/선택 티어 + 트러블슈팅). 아래는 요약.

0. 환경: `pip install -r requirements.txt` → `python scripts/preflight.py` (READY 떠야 함).
1. **권장 — 인터뷰:** `config.yaml` 없는 상태로 `/meeting-minutes` 실행 → `ONBOARDING.md` 인터뷰가 **하나씩 물어** config + profile 자동 생성. 형태를 미리 안 정하고 "어떤 회의 하나"부터 물음.
2. (수동 대안) `config.example.yaml` → `config.yaml` 복사 + `profiles/_template/` → `profiles/<your-name>/` 직접 채우기. `<...>` 값 전부 교체.
3. `profiles/example-acme/` = 채워진 **새니타이즈 예시** — 형태 참고용(실데이터 아님).
4. **검증(첫 실행 전 필수)**:
   - `python scripts/dry_run.py` → config·profile 로딩 + 빈칸 미해결 검출. **PASS** 떠야 함.
   - `bash verify.sh` → (스킬 수정 시) engine purity + placeholder↔config 게이트.

> 통합(Slack/Gmail/qmd/ontology)은 **전부 선택** — 없으면 산출물을 `.md`로 떨굼(실패 아님). Slack/qmd/ontology는 작성자 bespoke 로컬 도구라 팀원은 보통 없이 씀. 상세 `SETUP.md` §3.

> 개인정보(실연락처·고객명)는 `config.yaml`·자기 profile에 — 둘 다 `.gitignore`. 공유 레포엔 engine + `_template` + `example-acme`만 올라간다.
> **언어**: 산출물 보일러플레이트(`# 개요`/`Action Items`/메일 인사말 등)는 현재 **한국어 고정**. `locale.language`/`business_style`는 본문 작성 *문체* 지침에 반영되며, 출력 헤더 i18n은 아직 미지원(영문 조직은 템플릿 문자열 직접 교체 필요). 알려진 한계.

---

## References (해당 단계에서만 로드)

엔진(제네릭·공유):
- `references/engine/CONTRACT.md` — 인터페이스(placeholder 어휘·phase 정본·purity 규칙)
- `references/engine/writing-principles.md` — 작성 원칙(맥락·표금지·세그먼트·AI냄새·교차검증·매체별)
- `references/engine/pipeline.md` — 7단계 스켈레톤
- `references/engine/output-templates.md` — 산출물 구조 템플릿(placeholder)
- `references/engine/tooling.md` — 도구 감지 + degradation 매트릭스 + 알려진 버그 fallback

프로필(교체 가능·특화): `profiles/<active>/{structure,domain-glossary,contacts,conventions}.md` (+ 선택 `FEEDBACK.md`). **structure.md = 회의 형태**(섹션·카테고리·Action 그룹·제목 규칙) — 엔진이 형태를 강제하지 않고 여기/인터뷰로 받음.

검증: 스킬 루트에서 `bash verify.sh` (engine purity + placeholder↔config 게이트).
