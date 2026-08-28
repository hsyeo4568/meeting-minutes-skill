# Meeting Transcript Toolkit

- 녹취 교정 후 회의록 작성용 Claude 스킬 모음

```
녹취 .txt ──▶ [stt-transcript-fix] ──▶ 교정된 녹취 ──▶ [meeting-minutes] ──▶ 회의록 (.md, 공유는 설정)
              오타·문맥 교정                              카테고리별 산출물
              + (*...) 코멘트 자동 마킹                    + 직전 회의 연계·Action Items
```

[`skills/stt-transcript-fix/`](skills/stt-transcript-fix/)
- 원문 녹취 근거, 교정 범위 최소
- 화자 이름·번호 추측 금지
- meeting-minutes profile 용어사전 있으면 가장 잘 동작
- 없으면 → 사용자 괄호 교정 + 명백한 문맥 교정만
- 새 파일 → 용어사전 전체 미개방, 해당 녹취에 실제 나온 표기만 후보
- 인사이트·to-do → `(*...)` 마킹

[`skills/meeting-minutes/`](skills/meeting-minutes/)
- 회의 종류별 산출물
- Action Items 묶음 → profile 결정 (조직별 / 사람별 / 없음)
- 가상 예시 `example-acme` → design-review에서만 사람별

- 두 스킬 → 같은 profile 공유 (용어사전, 인명, 회의 구조)
- 엔진 = 범용, 팀 데이터 = profile에만

---

## 회의록이 만들어지는 방식

- 입력 → 파일 하나 또는 폴더
- 폴더 → 덱·시트 포함 읽기, 분량 한도 초과 시 질문

- 작업 폴더 첫 회의록 → 파일 하나
- 세션 에이전트 → profile 표기 규칙 + writing-principles로 1회 작성
- 초안 후 재작성 단계 없음
- 형제 재작성 파일 없음

- 직전 회의 연계 → 바로 이전 회의록의 `## 이전 회의 연계` + `## Action Items`만
- 상한 = 회의 종류별 개수, 달력 아님

- 공유 → 사용자가 초안 MD 확인 후만
- 순서: 승인 → 목적지 확인 → 캔버스 최대 1회 → URL → vault
- 초안 작성과 공유 같은 턴 혼합 금지

- 공유 목적지 → `config.categories`
- `config.example.yaml` 기준
  - 데일리 → md 공유 (캔버스 끔, 메일 선택)
  - 정기 → 캔버스 + 메일
  - 워크샵 → 캔버스 (메일 선택)
- Slack·Gmail 없으면 → 동일 내용 `.md` 저장, 없는 도구로 실패하지 않음

---

## 설치

### 처음 설치할 때

- Claude Code 대화창에 아래 한 줄 붙여넣기

```
https://github.com/hsyeo4568/meeting-minutes-skill 의 INSTALL.md를 읽고 내 환경에 맞게 설치해줘
```

- Claude → [`INSTALL.md`](INSTALL.md) 읽고 OS·설치 경로·기존 설치 여부 판정 후 복사, 의존성 설치, 검증
- 첫 `/meeting-minutes` 실행 → 온보딩 (이름, 조직, 회의 종류, 용어) → config·profile 생성
- 직접 설치 → 경로 B, 설치 없이 사용 → 경로 C

### 이미 설치한 경우

- 재설치 금지
- clone 후 meeting-minutes 엔진만 교체
- `--apply` 없음 → 변경 계획만 출력
- `--apply` → 적용 + 백업
- `config.yaml`·개인 profile 유지

```bash
python skills/meeting-minutes/scripts/update_install.py --target ~/.claude/skills/meeting-minutes          # 변경 계획만 출력
python skills/meeting-minutes/scripts/update_install.py --target ~/.claude/skills/meeting-minutes --apply  # 적용 (백업 자동)
```

- 이 스크립트 → meeting-minutes만 갱신, stt-transcript-fix 미수정
- STT → 개인 데이터 없음 → 같은 clone에서 해당 폴더 덮어쓰기

```bash
cp -r skills/stt-transcript-fix ~/.claude/skills/
```

```powershell
Copy-Item -Recurse skills\stt-transcript-fix "$HOME\.claude\skills\"
```

- Claude 위임 → 같은 INSTALL.md 한 줄, 기존 설치는 이 경로로 분기
- 변경 내역 → [`CHANGELOG.md`](CHANGELOG.md)

---

## 시작하기

### 경로 A: Claude Code를 처음 쓰는 경우

1. Claude Code 설치. Pro/Max 요금제 또는 API 키 필요
   ```
   # Windows (PowerShell) / macOS / Linux 공통 → Node.js 18+ 필요
   npm install -g @anthropic-ai/claude-code
   ```
2. 터미널에서 `claude` 실행 후 로그인. 상세: https://docs.anthropic.com/claude-code
3. 이어서 경로 B

### 경로 B: Claude Code에 스킬을 설치하는 경우

1. 저장소 clone 후 두 스킬 폴더 복사

   macOS/Linux/Git Bash:
   ```bash
   git clone https://github.com/hsyeo4568/meeting-minutes-skill.git
   cp -r meeting-minutes-skill/skills/meeting-minutes ~/.claude/skills/
   cp -r meeting-minutes-skill/skills/stt-transcript-fix ~/.claude/skills/
   ```
   Windows PowerShell (개인 스킬 폴더 = `C:\Users\<내계정>\.claude\skills\`):
   ```powershell
   git clone https://github.com/hsyeo4568/meeting-minutes-skill.git
   New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
   Copy-Item -Recurse meeting-minutes-skill\skills\meeting-minutes "$HOME\.claude\skills\"
   Copy-Item -Recurse meeting-minutes-skill\skills\stt-transcript-fix "$HOME\.claude\skills\"
   ```
2. 복사만으로 부족. Python 3.9+ 필요. 스킬 폴더에서 패키지 설치 후 preflight READY 필요. 시스템 Python이 패키지 설치를 막는 경우(PEP 668) → venv 또는 `--user`. 순서 상세 → [`skills/meeting-minutes/SETUP.md`](skills/meeting-minutes/SETUP.md), [`INSTALL.md`](INSTALL.md)

   ```bash
   cd ~/.claude/skills/meeting-minutes
   pip install -r requirements.txt        # pyyaml + python-pptx + openpyxl
   python scripts/preflight.py            # 환경 진단 → READY 출력 필요
   ```
3. Claude Code에 녹취 전달 + "회의록 만들어줘". config 없으면 온보딩 (이름, 조직, 회의 종류, 용어) → profile 생성. 온보딩에서 회의 종류 추가 가능
4. 녹취 교정 → "이 녹취 파일 오타 교정해줘" → stt-transcript-fix 처리

### 경로 C: 설치 없이 claude.ai에서 쓰는 경우

- 파일·설치 없이 claude.ai 웹 채팅(무료)에서 사용 가능
- [`PROMPT-ONLY.md`](skills/meeting-minutes/PROMPT-ONLY.md)만
- 작업 폴더 파일 없음
- 전송 전 `내 이름`·`내 소속`을 본인 값으로 치환 필요
- 이전 회의록 → 선택 붙여넣기
- 결과 → 회의록 마크다운 하나
- 자동 공유·vault·이전 파일 조회 없음
- 직전 회의 사용 → 채팅에 붙여넣기 필요

1. 회의록: [`skills/meeting-minutes/PROMPT-ONLY.md`](skills/meeting-minutes/PROMPT-ONLY.md) 전문 복사 → 채팅 붙여넣기 → 맨 아래 「입력」에 녹취 넣고 전송
2. 녹취 교정: [`skills/stt-transcript-fix/PROMPT-ONLY.md`](skills/stt-transcript-fix/PROMPT-ONLY.md) 동일 방식

---

## Profile

- 이 저장소 엔진 → 실제 팀 데이터 없음
- placeholder + 가상 예시 `example-acme`만
- `config.example.yaml` 기본 profile 경로 → `profiles/_template`

- 온보딩 → `profiles/<우리팀>/`에 `structure.md`, `contacts.md`, `domain-glossary.md`, `conventions.md` 생성
- `conventions-draft.md` 생성 안 함
- 그 파일 위치 → [`profiles/example-acme/`](skills/meeting-minutes/profiles/example-acme/)
- [`profiles/_template/`](skills/meeting-minutes/profiles/_template/) → `conventions.md`만

- 시계열 `body_mode`(데일리, 정기, 팀이 넣은 경우 리포트) → `conventions-draft.md` 있으면 그것만, 없으면 `conventions.md`. 둘 다 읽지 않음
- 축(워크샵, 외부, 내부) → `conventions.md` 전문
- `config.example.yaml` → 데일리·정기 = 시계열, 워크샵 = 축
- 회의 종류 추가 → 온보딩

- 빈 틀 시작 → `_template` 복사
- 채워진 형태 → `example-acme` 참고

## 보안

- 개인 profile, `config.yaml`, 녹취 원문 → 공개 저장소 커밋 금지
- 개인 데이터 = 실명, 고객, 사내 사실
- 이 저장소 `.gitignore` → `config.yaml`·개인 profile 차단. 포크·재배포는 직접 확인 필요

- `bash skills/meeting-minutes/verify.sh` → 스킬 수정 시 엔진 고유명사 혼입·placeholder 적합성 검사
- 설치 차단 아님
- macOS 기본 bash 3.2 → `mapfile` 실패 가능, 설치 실패 아님

## 구성

```
skills/meeting-minutes/
├── SKILL.md              # Claude Code가 읽는 엔진 지침
├── ONBOARDING.md         # 첫 실행 인터뷰
├── SETUP.md              # 수동 설치
├── PROMPT-ONLY.md        # 설치 없이 붙여 넣는 프롬프트
├── config.example.yaml   # 설정 템플릿. 기본 profile은 profiles/_template
├── profiles/             # _template(빈 틀, conventions.md만)과 example-acme(채워진 예시, conventions-draft.md 포함)
├── references/engine/    # 파이프라인, 작성 원칙, 산출물 템플릿, 도구 연동
├── scripts/              # update_install.py, preflight.py 등
├── tests/
├── evals/
├── requirements.txt
└── verify.sh             # 스킬을 고칠 때 쓰는 순수성 검사. 설치 필수 아님

skills/stt-transcript-fix/
├── SKILL.md
├── PROMPT-ONLY.md
├── scripts/
├── references/
├── tests/
└── evals/

sync-public.py            # 메인테이너 전용. 로컬 작업본을 이 저장소에 맞추고 누출 검사
```

## 라이선스 / 문의

- 사내 세미나 공유용
- 이슈·개선 제안 → GitHub Issues
- 현재 배포 v2.0.1 (2026-08-28)
- 변경 내역 [`CHANGELOG.md`](CHANGELOG.md)
- 태그 https://github.com/hsyeo4568/meeting-minutes-skill/releases/tag/v2.0.1
