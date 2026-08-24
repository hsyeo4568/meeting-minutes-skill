# meeting-minutes — 설치 (follow-along)

> 요약 — **필수 구성은 최소**. Claude Code + Python + PyYAML만 있으면 동작. Slack·Gmail·검색은 선택이며 미설치 시 `.md` 파일 fallback을 사용한다. ontology는 `required: false` (또는 `ontology` key 없음)일 때만 선택이다. `required: true`인데 runner/capability가 없으면 TTL 후보와 reason·path·provenance를 보존하되 `manual_required`로 남아 `close=7`이다. hash-bound authenticated `mm-ontology-validator-receipt/1` from `turtle-parse/1`가 있어야 validated deferred-load TTL로 완료할 수 있으며, 단순 skip은 허용하지 않는다. 위에서 아래로 순서대로 진행

---

## 유료판 vs 무료판 (선택 먼저)

| | 유료판 (Claude Code) | 무료판 (`PROMPT-ONLY.md`) |
|---|---|---|
| 대상 | Pro/Max/API 사용자 | **무료 포함 전체** (웹/Desktop 채팅) |
| 동작 | 녹취→산출물 **자동**(파일 읽기·python·MCP) | 프롬프트 붙여넣기 → 회의록 텍스트 **수동 복사** |
| 설치 | 아래 §0~4 | **설치 불필요** — `PROMPT-ONLY.md` 통째 복사 후 채팅에 붙여넣기 |
| 자동화 | 직전회의 연계·xlsx 교차검증·자동 공유 O | 없음 (작성 규칙만 적용) |

- **무료 사용자 → 여기까지**: `PROMPT-ONLY.md` 전체 복사 → Claude 채팅에 붙여넣기 → 맨 아래 「입력」에 녹취 입력 후 전송
- `PROMPT-ONLY.md`는 엔진에서 **자동 생성**(`python scripts/build_prompt.py`) → 엔진 수정 후 재실행 시 무료판 자동 동기화, 두 버전 불일치 없음. 개인 실값 반영본은 `--config config.yaml` 사용(커밋 금지)
- 유료 사용자 → 아래 계속

---

## 0. 스킬 설치 위치

- zip 해제 또는 복사 후 **본인** skills 디렉터리에 배치
  - 전역: `~/.claude/skills/meeting-minutes/` (대부분 여기)
  - 프로젝트별: `<project>/.claude/skills/meeting-minutes/`
- Claude Code CLI 자체는 실행 경로 무관 → 스킬 폴더만 위 경로에 있으면 `/meeting-minutes`로 인식

---

## 1. 필수 (이 구성만으로 동작 — 산출물은 .md 파일)

| 항목 | 확인 | 설치 |
|---|---|---|
| Claude Code | `claude --version` | https://claude.com/claude-code |
| Python ≥3.9 | `python --version` | python.org / brew / winget |
| Python 패키지 | 아래 preflight | `pip install -r requirements.txt` |
| bash ≥4 (verify.sh용) | `bash --version` | Windows=Git Bash / macOS=`brew install bash`(기본 3.2라 교체 필요) |

```bash
cd ~/.claude/skills/meeting-minutes
pip install -r requirements.txt        # pyyaml + python-pptx + openpyxl
python scripts/preflight.py            # 환경 진단 → READY 출력 필요
```

- `preflight.py`가 미충족 항목 + 설치 명령을 항목별로 안내 → REQUIRED만 충족하면 충분

---

## 2. 설정 (config + profile)

```bash
cp config.example.yaml config.yaml     # 이후 <...> 값 전부 실제 값으로 교체
cp -r profiles/_template profiles/<본인>   # domain-glossary·contacts·conventions 작성
# config.yaml 의 project.profile 을 "profiles/<본인>" 로 지정
python scripts/dry_run.py              # config·profile 검증 → PASS 출력 필요
```

- `profiles/example-acme/` = 채워진 가상 예시 → 형태 참고용
- `config.yaml` + 개인 profile = 개인정보 → `.gitignore` 대상(공유 안 됨)
- 여기까지면 `/meeting-minutes` 동작. Slack/Gmail 미보유 시 Canvas·메일 본문을 `.md`로 출력 → 수동 게시

---

## 3. 선택 통합 (보유 시 자동화 향상, 미보유 시 파일 fallback)

- 스킬이 시작 시 자동 감지 → 보유분만 사용. 전부 미설치여도 무방

| 통합 | 효과 | 비고 |
|---|---|---|
| **Gmail** | 정기회의 메일 *초안 자동 생성* | claude.ai Gmail 커넥터(누구나 가능). 미보유 시 메일 본문 `.md` 출력 |
| **Slack Canvas** | Canvas 자동 생성·공유 | **작성자 bespoke 로컬 MCP** — 팀원 대부분 미보유. 미보유 시 Canvas 본문 `.md` 출력 |
| **qmd (검색 인덱싱)** | 회의록 검색 인덱싱 | bespoke 로컬 도구. 미보유 시 인덱싱 생략 |
| **ontology (지식그래프)** | 결정사항 그래프 기록 | `required: false` (또는 `ontology` key 없음)면 phase 7 생략. `required: true`인데 runner/capability가 없으면 TTL 후보를 reason·path·provenance와 함께 `manual_required`로 보존해 `close=7`. hash-bound authenticated `mm-ontology-validator-receipt/1` from `turtle-parse/1`가 있어야 validated deferred-load TTL로 완료 |
| **Whisper (오디오 STT)** | 녹음파일 → 텍스트 | `pip install openai-whisper`(torch 포함이라 용량 큼). 텍스트/PDF만 사용 시 불필요 |

> 팀원 기본 경로 = Slack/qmd 없이 `.md` 산출물 수동 공유. ontology는 `required: false` (또는 `ontology` key 없음)일 때만 생략 가능하다. `required: true`에서 runner/capability가 없으면 TTL 후보를 보존하지만 `manual_required`로 `close=7`이다. hash-bound authenticated `mm-ontology-validator-receipt/1` from `turtle-parse/1`만 deferred-load TTL 검증을 증명한다. `config.tools`에서 `off` 지정 가능

---

## 4. 검증 체크리스트 (첫 실행 전)

```bash
python scripts/preflight.py     # 1) 머신 준비 여부 → READY
python scripts/dry_run.py       # 2) config 작성 상태 → PASS
bash verify.sh                  # 3) (스킬 수정 시) engine purity 게이트 → PASS
```

- 3개 통과 시 완료 → `/meeting-minutes [녹취파일]` 실행

---

## 트러블슈팅

- `FAIL: PyYAML not installed` → `pip install pyyaml`
- `mapfile: command not found` (verify.sh, macOS) → 기본 bash 3.2 문제. `brew install bash` 후 `/opt/homebrew/bin/bash verify.sh`
- Python 한글 깨짐(Windows) → `set PYTHONUTF8=1` 후 실행 (스크립트 자체는 reconfigure 처리 완료)
- Slack/Gmail 도구 호출 실패 → 정상 동작. 스킬이 `.md` fallback으로 전환
