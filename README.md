# Meeting Transcript Toolkit

녹취를 교정한 다음 회의록으로 만드는 Claude 스킬 모음입니다.

```
녹취 .txt ──▶ [stt-transcript-fix] ──▶ 교정된 녹취 ──▶ [meeting-minutes] ──▶ 회의록 (.md, 공유는 설정)
              오타·문맥 교정                              카테고리별 산출물
              + (*...) 코멘트 자동 마킹                    + 직전 회의 연계·Action Items
```

[`skills/stt-transcript-fix/`](skills/stt-transcript-fix/)는 원문 녹취를 근거로, 고치는 범위를 최소로 잡습니다. 화자 이름과 번호는 추측하지 않습니다. meeting-minutes profile의 용어사전이 있으면 가장 잘 동작하고, 없으면 사용자가 단 괄호 교정과 명백한 문맥 교정만 합니다. 새 파일에서는 용어사전 전체를 열지 않고, 그 녹취에 실제로 나온 표기만 후보로 삼습니다. 인사이트와 to-do는 `(*...)`로 표시합니다.

[`skills/meeting-minutes/`](skills/meeting-minutes/)는 회의 종류별로 산출물을 만듭니다. Action Items를 조직별·사람별·없음 중 어떻게 묶을지는 profile이 정합니다. 가상 예시 `example-acme`는 design-review에서만 사람별로 묶습니다.

두 스킬은 같은 profile(용어사전, 인명, 회의 구조)을 공유합니다. 엔진은 범용이고, 팀 데이터는 profile에만 있습니다.

---

## 회의록이 만들어지는 방식

입력은 파일 하나이거나 폴더입니다. 폴더를 주면 덱과 시트도 읽고, 분량이 한도를 넘으면 물어봅니다.

작업 폴더의 첫 회의록은 파일 하나입니다. Hemingway 작성기가 있으면 그 본문이 곧 그 파일이고, 없으면 같은 표기 규칙을 읽어 그 파일 하나를 씁니다. 엔진이 초안을 만든 뒤 고치는 단계와 `.hemingway.md` 형제 파일은 없습니다.

직전 회의에서 가져오는 것은 바로 이전 회의록의 `## 이전 회의 연계`와 `## Action Items`뿐입니다. 달력이 아니라 회의 종류마다 개수 상한이 있습니다.

초안 MD를 사용자가 확인한 뒤에만 공유합니다. 승인, 목적지 확인, 캔버스는 최대 한 번, URL, 그다음 vault 순서입니다. 초안 작성과 공유를 한 턴에 섞지 마세요.

어디로 올릴지는 `config.categories`가 정합니다. `config.example.yaml` 기준으로 데일리는 md 공유(캔버스 끔, 메일 선택), 정기는 캔버스와 메일, 워크샵은 캔버스(메일 선택)입니다. Slack이나 Gmail이 없으면 같은 내용을 `.md`로 남기며, 없는 도구 때문에 실패하지 않습니다.

---

## 설치

### 처음 설치할 때

Claude Code 대화창에 아래 한 줄을 붙여 넣으세요.

```
https://github.com/hsyeo4568/meeting-minutes-skill 의 INSTALL.md를 읽고 내 환경에 맞게 설치해줘
```

Claude가 [`INSTALL.md`](INSTALL.md)를 읽고 OS, 설치 경로, 기존 설치 여부를 판정한 뒤 복사, 의존성 설치, 검증까지 진행합니다. 처음 `/meeting-minutes`를 실행하면 온보딩이 이름, 조직, 회의 종류, 용어를 묻고 config와 profile을 만듭니다. 직접 설치하려면 경로 B를, 설치 없이 쓰려면 경로 C를 보세요.

### 이미 설치한 경우

다시 설치하지 마세요. clone한 뒤 meeting-minutes 엔진만 교체합니다. `--apply`가 없으면 변경 계획만 출력하고, `--apply`를 주면 적용하며 백업을 남깁니다. `config.yaml`과 개인 profile은 유지됩니다.

```bash
python skills/meeting-minutes/scripts/update_install.py --target ~/.claude/skills/meeting-minutes          # 변경 계획만 출력
python skills/meeting-minutes/scripts/update_install.py --target ~/.claude/skills/meeting-minutes --apply  # 적용 (백업 자동)
```

이 스크립트는 meeting-minutes만 갱신합니다. stt-transcript-fix는 건드리지 않습니다. STT에는 개인 데이터가 없으니, 같은 clone에서 그 폴더를 덮어쓰세요.

```bash
cp -r skills/stt-transcript-fix ~/.claude/skills/
```

```powershell
Copy-Item -Recurse skills\stt-transcript-fix "$HOME\.claude\skills\"
```

Claude에게 맡겨도 같은 INSTALL.md 한 줄이면 됩니다. 기존 설치는 이 경로로 분기합니다. 변경 내역은 [`CHANGELOG.md`](CHANGELOG.md)에 있습니다.

---

## 시작하기

### 경로 A: Claude Code를 처음 쓰는 경우

1. Claude Code를 설치합니다. Pro/Max 요금제 또는 API 키가 필요합니다.
   ```
   # Windows (PowerShell) / macOS / Linux 공통 — Node.js 18+ 필요
   npm install -g @anthropic-ai/claude-code
   ```
2. 터미널에서 `claude`를 실행하고 로그인합니다. 상세: https://docs.anthropic.com/claude-code
3. 이어서 경로 B로 갑니다.

### 경로 B: Claude Code에 스킬을 설치하는 경우

1. 저장소를 clone한 뒤 두 스킬 폴더를 복사합니다.

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
2. 복사만으로는 부족합니다. Python 3.9 이상이 필요하고, 스킬 폴더에서 패키지를 설치한 뒤 preflight가 READY를 내야 합니다. 시스템 Python이 패키지 설치를 막는 경우(PEP 668)는 venv 또는 `--user`를 쓰세요. 순서의 상세는 [`skills/meeting-minutes/SETUP.md`](skills/meeting-minutes/SETUP.md)와 [`INSTALL.md`](INSTALL.md)에 있습니다.

   ```bash
   cd ~/.claude/skills/meeting-minutes
   pip install -r requirements.txt        # pyyaml + python-pptx + openpyxl
   python scripts/preflight.py            # 환경 진단 → READY 출력 필요
   ```
3. Claude Code에 녹취를 주고 "회의록 만들어줘"라고 하면 됩니다. config가 없으면 온보딩이 이름, 조직, 회의 종류, 용어를 물은 뒤 profile을 만듭니다. 온보딩에서 회의 종류를 더 넣을 수 있습니다.
4. 녹취 교정은 "이 녹취 파일 오타 교정해줘"라고 하면 stt-transcript-fix가 처리합니다.

### 경로 C: 설치 없이 claude.ai에서 쓰는 경우

파일이나 설치 없이 claude.ai 웹 채팅(무료)에서 쓸 수 있습니다. Hemingway도 없고, 작업 폴더 파일도 없습니다. [`PROMPT-ONLY.md`](skills/meeting-minutes/PROMPT-ONLY.md)의 작성 규칙만 적용됩니다.

전송 전에 `내 이름`과 `내 소속`을 본인 값으로 바꾸세요. 이전 회의록은 선택적으로 붙여 넣을 수 있습니다. 결과는 회의록 마크다운 하나입니다. 자동 공유, vault, 이전 파일 조회는 없습니다. 직전 회의를 쓰려면 채팅에 붙여 넣어야 합니다.

1. 회의록: [`skills/meeting-minutes/PROMPT-ONLY.md`](skills/meeting-minutes/PROMPT-ONLY.md) 전문을 복사해 채팅에 붙여 넣고, 맨 아래 「입력」에 녹취를 넣은 뒤 전송합니다.
2. 녹취 교정: [`skills/stt-transcript-fix/PROMPT-ONLY.md`](skills/stt-transcript-fix/PROMPT-ONLY.md)도 같은 방식입니다.

---

## Profile

이 저장소 엔진에는 실제 팀 데이터가 없습니다. placeholder와 가상 예시 `example-acme`만 있습니다. `config.example.yaml`의 기본 profile 경로는 `profiles/_template`입니다.

온보딩은 `profiles/<우리팀>/`에 `structure.md`, `contacts.md`, `domain-glossary.md`, `conventions.md`를 만듭니다. `conventions-draft.md`는 만들지 않습니다. 그 파일은 [`profiles/example-acme/`](skills/meeting-minutes/profiles/example-acme/)에 있고, [`profiles/_template/`](skills/meeting-minutes/profiles/_template/)에는 `conventions.md`만 있습니다.

시계열 `body_mode`(데일리, 정기, 그리고 팀이 넣은 경우 리포트)에서 Hemingway는 `conventions-draft.md`만 읽습니다. 축(워크샵, 외부, 내부)은 `conventions.md` 전문을 읽습니다. `config.example.yaml`은 데일리와 정기를 시계열, 워크샵을 축으로 넣습니다. 회의 종류는 온보딩에서 추가합니다.

빈 틀로 시작하려면 `_template`를 복사하고, 채워진 형태는 `example-acme`를 보면 됩니다.

## 보안

개인 profile, `config.yaml`, 녹취 원문은 공개 저장소에 커밋하지 마세요. 개인 데이터는 실명, 고객, 사내 사실입니다. 이 저장소 `.gitignore`가 `config.yaml`과 개인 profile을 막지만, 포크나 재배포에서는 직접 확인해야 합니다.

`bash skills/meeting-minutes/verify.sh`는 스킬을 고칠 때 엔진에 고유명사가 섞였는지, placeholder가 맞는지 보는 검사입니다. 설치를 막지는 않습니다. macOS 기본 bash 3.2는 `mapfile`에서 실패할 수 있고, 그것은 설치 실패가 아닙니다.

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

sync-public.py            # 메인테이너 전용. 로컬 작업본을 이 저장소에 맞추고 누출을 검사합니다.
```

## 라이선스 / 문의

사내 세미나 공유용입니다. 이슈와 개선 제안은 GitHub Issues로 올려 주세요. 현재 배포는 v2.0.0 (2026-08-28)입니다. 변경 내역은 [`CHANGELOG.md`](CHANGELOG.md), 태그는 https://github.com/hsyeo4568/meeting-minutes-skill/releases/tag/v2.0.0 입니다.
