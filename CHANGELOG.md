# 변경 이력

- 날짜 = 이 저장소 반영일 기준
- 버전은 배포 단위 표기이며 패키지 버전 아님 → 설치는 최신 상태 복사로 충분

---

## [1.1.2] — 2026-08-27

**요약** — 공유 전에 목적지를 확인하고, 캔버스는 한 번만 만든 뒤 사용자가 열 수 있을 때 URL을 내고, 그다음 볼트에 저장한다

### 추가

- 공유 전 목적지 확인 (`share-check`). 목적지가 비어 있으면 Exit 8로 막음
- `tests/test_share_guard.py` — 목적지 가드 회귀

### 변경

- **공유 순서** — 목적지 확인 → Path로 캔버스 1회 생성 → 열림 확인 후 URL → 그다음 볼트
- 승인 후 캔버스를 다시 만들지 않음

### 고침

- 목적지 없는 공유를 성공으로 치던 경로를 Exit 8로 차단

### 설치 · 업데이트

- 재설치 금지. 엔진만 교체:

  ```bash
  python skills/meeting-minutes/scripts/update_install.py --target ~/.claude/skills/meeting-minutes --apply
  ```

---

## [1.1.1] — 2026-08-27

**요약** — ① 부트 라우터가 vault·ontology/phase 7을 항상 읽지 않음, ② canvas/gmail/vault 공유는 승인 스냅샷만 (녹취 재읽기 없음), ③ register-gate 예시에서 머신 경로 제거

### 추가

- `tests/test_skill_router.py` — 부트 라우터가 writing-principles / pipeline / vault / glossary / ontology를 항상 로드하지 않는지 고정
- `tests/test_share_remap.py` — 공유 본문이 승인 스냅샷에서만 오는지 고정

### 변경

- **부트 라우터** — SKILL.md가 설정·카테고리만 읽고 멈춤. vault·glossary·ontology·phase 7은 해당 단계가 아니면 로드하지 않음. phase 7 default OFF
- **스냅샷 공유 (phase 5)** — canvas/gmail/vault는 승인 스냅샷 remap. 녹취·glossary·writing-principles를 다시 읽지 않음. `share-check` Exit 8 유지

### 고침

- register-gate 예시가 머신 절대 경로를 담고 있어 공개 배포 leak scan에 걸리던 문제. 지금은 `python prose_lint.py "<path>" --register "<id>" --json`

### 설치 · 업데이트

- 재설치 금지. 엔진만 교체:

  ```bash
  python skills/meeting-minutes/scripts/update_install.py --target ~/.claude/skills/meeting-minutes --apply
  ```

---

## [1.1.0] — 2026-08-06

**요약** — ① 긴 회의를 논점별로 묶는 본문 모드, ② 첨부자료 선(先)이해 단계, ③ 공유 결과를 확인으로 남기는 게시 절차

### 추가

**1. 본문 구성 방식 `body_mode`**

- 회의 종류별로 `config.categories.<종류>.body_mode`에 지정
- `chronological` (기본) — 안건 발생 순 나열
  - 데일리처럼 짧고 잦은 운영 회의에 적합 ("오늘 뭐가 있었나"가 곧 구조)
  - 이런 회의에 논점축 강제 불필요
- `axis` — 녹취 순서는 입력으로만 사용, 본문은 논점별 재편
  - 논점 1개 = `## N.` 1개, 하위는 `1) 2) 3)`으로 배경·전제 → 주체별 입장 → 쟁점 → 결론
  - 논점마다 결정 / 미합의 / 보류 중 하나로 착지, 어디에도 안 붙는 내용은 맨 뒤 `## N. 기타`에 1줄씩
  - 대상: 외부 회의·워크샵 등 같은 쟁점이 반복 등장하는 회의 → 발생 순 나열 시 쟁점이 묻히는 문제 해소
- 규칙 전문: `references/engine/writing-principles.md` §11
- 오타값(`axes` 등)은 `python scripts/dry_run.py`가 FAIL 처리 (이전에는 무시됨)

**2. 자료 이해 단계 (phase 1.5)**

- `/meeting-minutes <폴더>`로 폴더 전달 시 녹취 외 폴더 내 파일 전체를 목록화
- 확장자별 핸들러로 덱·시트·리포트 요약 → **초안 작성 전** 반영
- 핸들러는 `config.materials.handlers`에 선언, 미설치 항목은 건너뛰고 다음 핸들러가 수신, 최종적으로 기본 핸들러 `scripts/materials_digest.py`가 처리
- 덱이 폴더에 있는데 파일명만 보고 안건 작성하는 것은 실패한 run으로 간주

**3. 게시 절차 강제 (publish gate)**

- `scripts/mm_run.py` — `approve → gate → record → verify → close`
- 승인 시점 MD를 스냅샷으로 고정 → 공유 본문은 `gate`가 반환한 `snapshot_path`에서만 생성
- 종료 코드별 차단 사유
  - `3` = 승인 후 MD 변경 (재승인 필요)
  - `4` = 게시본과 재확인본 불일치
  - `5` = 다른 세션이 lease 보유
  - `7` = 미검증 산출물을 남긴 채 종료 시도
- 전문: `references/engine/RUNTIME-PROTOCOL.md`
- Python·PyYAML 미설치 환경은 이 절차 생략하고 진행 (실패 아님)

### 변경

- **게시 후 재확인(read-back) 방식을 채널별로 분리**
  - 기존 전체 바이트 비교는 Slack Canvas가 `-` 불릿을 `*`로 치환하고 날짜를 임베드로 감싸는 순간 매번 불일치 처리됨
  - Canvas → 장식 제거 후 줄 단위 누락만 확인 / Gmail 평문 → 78열 하드랩은 손실로 미집계
  - 실제 누락 줄은 종전대로 검출
- 엔진 문서(`references/engine/*`) 영어로 정리 — 산출물 언어와 무관, 모델이 읽는 계약 문서만 해당

### 고침

- 본문 대조 시 `1)`을 목록 번호로 인식 → `axis` 모드 하위 항목이 본문 텍스트로 오인되던 문제 해소
- 승인 후 작업 MD 파일명 변경 시 해당 run이 조용히 고아가 되던 현상 표면화
- 회의 종류 판별 기준·마커 처리 설명 보강
- phase 6.5(주제 동기화)는 해당 줄의 실제 반영 위치를 재확인하도록 요구

### 설치 · 업데이트

- **`INSTALL.md` 추가** — 저장소 주소만 전달하면 Claude가 그대로 따라가는 설치 런북
  - 사람이 직접 설치할 경우 `skills/meeting-minutes/SETUP.md`가 정본
- **`scripts/update_install.py` 추가** — 1.0.0 기설치자용, 재설치 아닌 엔진 교체
  - `config.yaml` · 사용자 profile · `verify-denylist.local` · `.mm/` 미접근 (읽기·삭제 모두 없음)
  - `--apply` 전 스킬 폴더 통째 백업
  - `--apply` 없이 실행 시 변경 계획만 출력, 파일 미기록
  - 완료 후 신규 설정 키 안내 (`body_mode`, `materials`, `runtime.*` — 미설정이어도 동작)

  ```bash
  python skills/meeting-minutes/scripts/update_install.py --target ~/.claude/skills/meeting-minutes --apply
  ```

---

## [1.0.0] — 2026-07-27

최초 공개 (사내 세미나 공유용)

- `skills/meeting-minutes` — 회의 종류별 산출물(팀챗 MD / Canvas / 메일), 이전 회의 연계, 조직별 Action Items, config + profile 구동
- `skills/stt-transcript-fix` — STT 녹취 오타·문맥 교정, `(*...)` 코멘트 자동 마킹
- 설치 없이 사용하는 `PROMPT-ONLY.md`, `profiles/_template` · `profiles/example-acme` 동봉
