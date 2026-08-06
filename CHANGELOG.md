# 변경 이력

이 저장소에 반영된 날짜 기준. 버전은 배포 단위이지 패키지 버전이 아니다 —
설치는 언제나 `main`(master) 최신 상태를 복사하면 된다.

---

## [1.1.0] — 2026-08-06

deep-dive 회의를 **논점축으로 재편**하는 모드, 첨부자료를 실제로 읽는 단계,
그리고 "공유했다"를 말이 아니라 **검증으로** 만드는 게시 게이트.

### 추가

- **본문 구성 방식 `body_mode`** (`chronological` | `axis`) — `config.categories.<카테고리>.body_mode`로 선언.
  - `chronological`(기본) — 안건이 나온 순서대로. 짧고 잦은 운영 회의(데일리·정기)는 "오늘 뭐가 있었나"가 곧 구조라 이게 맞다.
  - `axis` — **녹취 순서를 입력으로만 쓰고 출력은 논점축으로 재편**. 축 하나당 `## N.`, 그 아래 `1) 2) 3)`으로 배경·전제 → 주체별 입장 → 쟁점 → 결론. 축마다 **결정 / 미합의 / 보류** 중 하나로 착지하고, 어디에도 안 붙는 건 맨 뒤 `## N. 기타` 한 줄씩. 한 시간 동안 같은 질문이 세 번 되돌아오는 외부·워크샵 회의에서 평평한 목록이 논쟁을 파묻는 문제를 겨냥.
  - 규칙 전문: `references/engine/writing-principles.md` §11. 오타난 값(`axes` 등)은 예전엔 조용히 무시됐으나 이제 `python scripts/dry_run.py`가 FAIL로 잡는다.
- **자료 이해 단계 (phase 1.5)** — `/meeting-minutes <폴더>`로 폴더를 주면 녹취뿐 아니라 **폴더 안 모든 파일**을 매니페스트로 잡고, 확장자별 핸들러 체인으로 덱·시트·리포트를 요약해 **작성 전에** 읽는다. 핸들러는 `config.materials.handlers`에서 선언하고 없으면 다음 것으로 양보, 마지막엔 내장 `scripts/materials_digest.py`가 받는다. 덱이 폴더에 그대로 있는데 파일명만 보고 안건을 쓰는 건 지름길이 아니라 실패한 run으로 취급.
- **게시 게이트 런타임 프로토콜** — `scripts/mm_run.py` (`approve` → `gate` → `record` → `verify` → `close`). MD 승인 시점의 스냅샷을 고정하고, 본문은 오직 `gate`가 돌려준 `snapshot_path`에서만 만든다. 차단 exit: `3`=승인 후 MD 변경(재승인 필요), `4`=읽기-되돌림 불일치, `5`=다른 세션이 lease 보유, `7`=미검증 아티팩트를 둔 채 종료. 계약 전문 `references/engine/RUNTIME-PROTOCOL.md`. **Python/PyYAML이 없으면** 산문 fallback으로 내려갈 뿐 실패하지 않는다.

### 변경

- **읽기-되돌림(read-back) 검증이 채널별로** 갈라진다. 전역 바이트 해시 비교는 Slack Canvas가 `-` 불릿을 `*`로 고쳐 쓰고 날짜를 임베드로 감싸는 순간 매번 실패했다. 이제 canvas는 의미 비교(장식 제거 후 줄 단위 누락만 검사), Gmail 평문은 78열 하드랩을 손실로 보지 않으며, 그래도 **진짜 누락은 여전히 잡힌다**.
- 엔진 문서(`references/engine/*`)를 영어로 정리 — 산출물 언어(한국어)와는 무관, LLM이 읽는 계약 문서만.

### 고침

- 본문 평탄화에서 `1)`을 목록 번호로 인식 — `axis` 모드 sub-item이 읽기-되돌림에서 본문 텍스트로 오인되던 문제.
- 승인 후 작업 MD 이름이 바뀐 run이 조용히 고아가 되던 것 → 표면화.
- 카테고리 판별자·마커 라우팅 문서 보강, phase 6.5(topic sync)는 "줄이 어디에 떨어졌는지" 재읽기로 확인하도록 요구.

### 설치

- **`INSTALL.md` 추가** — Claude에게 저장소 주소만 주면 스스로 따라갈 수 있는 설치 런북. 사람이 직접 설치하려면 기존 `skills/meeting-minutes/SETUP.md`가 여전히 정본.

---

## [1.0.0] — 2026-07-27

최초 공개(세미나 배포).

- `skills/meeting-minutes` — 카테고리별 산출물(팀챗 MD / Canvas / 메일), 이전 회의 연계, 조직별 Action Items, config + profile 구동.
- `skills/stt-transcript-fix` — STT 녹취 오타·문맥 교정, `(*...)` 코멘트 자동 마킹.
- `PROMPT-ONLY.md` 무료판(설치 없이 복붙), `profiles/_template` + `profiles/example-acme`.
