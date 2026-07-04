# Pipeline (generic meeting-minutes engine)

7-phase skeleton. Phase names/numbers are fixed by CONTRACT.md — tooling.md keys off them.
원본 녹취·시트는 `{{work_folder}}` 아래. 정본(canonical) 저장소가 source of truth, work-folder 사본은 중복.
**카테고리는 본문 작성 전에 먼저 판별** (phase 4 매트릭스가 share routing까지 결정).

> **MD-first 승인 게이트 (필수, 외부 공유 전):** phase 번호는 share(5) → canonical(6) 순서지만, **실행 순서는 정본 MD(phase 6: vault + work-folder 사본) 먼저 작성·저장 → 사용자 검토·직접 수정 대기 → 명시 승인 후에만 share(phase 5: canvas/gmail) 실행.**
> 한 턴에 MD + canvas + gmail 몰아 생성 금지. 사용자가 work-folder MD를 직접 손보는 경우가 잦음(화자명·Action·일정 교정) → MD 확정 전 외부 산출물 만들면 stale 양산 + canvas는 사후 edit 불가(재생성 orphan·rate limit).
> 데일리·정기 공통. 사용자가 "이 MD 기준으로 canvas 만들어" 명시하면 그때 share. 카테고리 매트릭스(정기=canvas+gmail+vault)는 *최종 산출 종류*지 *1턴 실행*이 아님.

## 1. Preprocess

- 입력 형태별 처리: 텍스트 그대로 / PDF 추출 / 오디오 → Whisper STT.
- 회의자료 폴더(`{{work_folder}}`)에 슬라이드(PPTX) 있으면 **먼저** python-pptx로 읽어 본문 맥락 확보.
  - markitdown은 한글 깨짐 → 회피. python-pptx로 직접 텍스트 추출.
  - Windows 콘솔 출력 시 `sys.stdout.reconfigure(encoding='utf-8')`.

## 2. Speaker ID + clean

- 발화자 매핑: raw 화자 → 정식 라벨. profile 있으면 contacts로 교차검증, 없으면 placeholder.
- 추임새·중복·잡음 제거. 의미 보존, 입장/합의 구분 유지.
- `{{me}}` = "나"/"I" 화자. 1인칭 발언은 이 라벨로 정규화.

## 3. Context-link + draft body

- 직전 1~2주 회의록 Read → 진행 중 안건의 연계 맥락 정리.
- 각 안건을 원 회의(source meeting)에 연결 → "지난주 X → 이번주 Y" 추적.
- writing-principles.md 적용 (개조식·화살표·세그먼트·담당자·실데이터).
- 식별자(인물/장비/고객 등)는 source-of-truth 시트와 교차검증. 시트 없으면 표기 그대로 두고 플래그.
- **인라인 주석 마커** (사용자가 녹취에 남긴 사후 코멘트): profile 라우팅 규칙으로 해당 섹션 승격. 마커 문법·키워드 매핑은 **profile 소관**(엔진 순수성 — 특정 문법 하드코딩 금지). 미분류 마커는 초안에 노출(silent drop 금지), 외부 산출물엔 raw 마커 미포함.

## 4. Per-category deliverables

- **카테고리 판별이 먼저** — 채널 혼동이 가장 잦은 실수.
- config의 `categories` 매트릭스 적용 (output-templates.md): 카테고리별 산출물 형식/구조 결정.
- 각 카테고리 템플릿으로 본문 → 산출물 렌더.

## 5. Share routing

- **선행 조건: phase 6 정본 MD 저장 + 사용자 승인** (위 MD-first 게이트). 승인 전엔 이 phase 미실행.
- phase 4 카테고리 결과로 채널 분기: 카테고리별 `share_md` / `canvas` / `gmail`.
- canvas는 **1회만** 생성(연타 시 `canvas_creation_failed` rate limit). 채널 canvas는 `canvases.edit` 미지원 → 재공유 필요 시 새 canvas + 정본 frontmatter의 canvas id 갱신.
- 도구 없으면 파일 fallback (tooling.md):
  - slack 없음 → canvas 본문을 `.md`로 저장 + "수동 게시" 메모.
  - gmail 없음 → 제목+수신/참조+본문을 `.md`(또는 `.eml`)로 저장.
- 어떤 분기든 에러로 중단하지 않음.

## 6. Canonical save

- 정본 저장소는 config — `{{vault_path}}`(노트 vault·문서 폴더·위키 등 조직마다 다름). 특정 도구 가정 없음.
- 정본 경로: `{{vault_path}}/{{vault_meetings_subpath}}/<YYYY-MM-DD> <category> <슬러그>.md`.
  - 슬러그는 `{{project_slug}}` 기반 안건 식별자.
- config의 `vault_frontmatter` 스키마로 frontmatter 작성 (date·category·participants·source 등). 저장소가 frontmatter 미지원이면 본문만.
- (선택) 검색 인덱서(qmd 등) 가용 시 인덱싱. 없으면 "indexing skipped" 출력 후 통과.

## 7. Knowledge-graph update (선택)

- **선택 add-on** — 도구 없으면 통째로 생략(유효한 실행에 필수 아님).
- 결정사항·관계(누가 무엇을 언제 결정/약속)를 ontology 스킬 인터페이스로 기록.
  - **스킬 인터페이스만 사용** — 라이브러리(pyoxigraph 등) 직접 호출 금지.
