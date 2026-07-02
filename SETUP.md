# meeting-minutes — 설치 (follow-along)

> 한 줄 요약: **필수는 작다.** Claude Code + Python + PyYAML만 있으면 돈다. 나머지 통합(Slack·Gmail·검색·지식그래프)은 *전부 선택* — 없으면 결과를 `.md` 파일로 떨군다(실패 아님). 위에서 아래로 쭉 따라가면 됨.

---

## 유료판 vs 무료판 (먼저 고르기)

| | 유료판 (Claude Code) | 무료판 (`PROMPT-ONLY.md`) |
|---|---|---|
| 대상 | Pro/Max/API 사용자 | **무료 포함 누구나** (웹/Desktop 채팅) |
| 동작 | 녹취→산출물 **자동**(파일 읽기·python·MCP) | 프롬프트 붙여넣기 → 회의록 텍스트 **수동 복사** |
| 설치 | 아래 §0~4 | **설치 0** — `PROMPT-ONLY.md` 통째 복사해 채팅에 붙여넣기 |
| 자동화 | 직전회의 연계·xlsx 교차검증·자동 공유 O | 없음 (작성 규칙만) |

- **무료 사용자 → 여기서 끝:** `PROMPT-ONLY.md` 열어 전체 복사 → Claude 채팅에 붙여넣기 → 맨 아래 「입력」에 녹취 넣고 전송.
- `PROMPT-ONLY.md`는 엔진에서 **자동 생성**됨(`python scripts/build_prompt.py`). 엔진 수정 후 재실행하면 무료판 자동 동기화 → 두 버전 안 어긋남. 개인 실값 채운 버전은 `--config config.yaml`(커밋 금지).
- 유료 사용자는 아래 계속.

---

## 0. 스킬 설치 위치

zip을 풀거나 복사해서 **자기** skills 디렉터리에:
- 전역: `~/.claude/skills/meeting-minutes/`  (대부분 여기)
- 프로젝트별: `<project>/.claude/skills/meeting-minutes/`

Claude Code CLI 자체는 아무 경로에서 실행해도 됨. 스킬 폴더만 위 경로에 있으면 `/meeting-minutes`로 인식.

---

## 1. 필수 (이것만 있어도 동작 — 산출물은 .md 파일)

| 항목 | 확인 | 설치 |
|---|---|---|
| Claude Code | `claude --version` | https://claude.com/claude-code |
| Python ≥3.9 | `python --version` | python.org / brew / winget |
| Python 패키지 | 아래 preflight | `pip install -r requirements.txt` |
| bash ≥4 (verify.sh용) | `bash --version` | Windows=Git Bash / macOS=`brew install bash`(기본 3.2라 교체) |

```bash
cd ~/.claude/skills/meeting-minutes
pip install -r requirements.txt        # pyyaml + python-pptx + openpyxl
python scripts/preflight.py            # 환경 진단 → READY 떠야 함
```

`preflight.py`가 빠진 것 + 설치 명령을 항목별로 알려줌. REQUIRED만 채우면 됨.

---

## 2. 설정 (config + profile)

```bash
cp config.example.yaml config.yaml     # 그리고 <...> 값 전부 실제 값으로
cp -r profiles/_template profiles/<당신>   # domain-glossary·contacts·conventions 채우기
# config.yaml 의 project.profile 을 "profiles/<당신>" 로
python scripts/dry_run.py              # config·profile 검증 → PASS 떠야 함
```

- `profiles/example-acme/` = 채워진 가짜 예시 → 형태 참고.
- `config.yaml` + 자기 profile = 개인정보 → `.gitignore` 됨(공유 안 됨).

여기까지면 `/meeting-minutes` 돌아감. Slack/Gmail 없으면 Canvas·메일 본문을 `.md`로 떨굼 → 수동 게시.

---

## 3. 선택 통합 (있으면 자동화 ↑, 없으면 파일 fallback)

스킬이 시작 시 자동 감지 → 있는 것만 사용. 아무것도 안 깔아도 됨.

| 통합 | 효과 | 비고 |
|---|---|---|
| **Gmail** | 정기회의 메일 *초안 자동 생성* | claude.ai Gmail 커넥터(누구나 가능). 없으면 메일본문 `.md` 출력 |
| **Slack Canvas** | Canvas 자동 생성·공유 | **작성자 bespoke 로컬 MCP** — 팀원 보통 없음. 없으면 Canvas본문 `.md` 출력 |
| **qmd (검색 인덱싱)** | 회의록 검색 인덱싱 | bespoke 로컬 도구. 없으면 인덱싱 생략 |
| **ontology (지식그래프)** | 결정사항 그래프 기록 | bespoke 로컬 도구. 없으면 phase 7 통째 생략 |
| **Whisper (오디오 STT)** | 녹음파일 → 텍스트 | `pip install openai-whisper`(torch라 큼). 텍스트/PDF만 쓰면 불필요 |

> Slack/qmd/ontology는 작성자 환경 전용 커스텀 서버다. 팀원 배포 시 **그대로 옮겨오기 어려움** → 그냥 없이 쓰고 `.md` 산출물을 수동 공유하는 게 기본 경로. config.tools에서 `off`로 둬도 됨.

---

## 4. 검증 체크리스트 (첫 실행 전)

```bash
python scripts/preflight.py     # 1) 머신 준비됐나 → READY
python scripts/dry_run.py       # 2) config 제대로 채웠나 → PASS
bash verify.sh                  # 3) (스킬 수정 시) engine purity 게이트 → PASS
```

3개 다 통과면 끝. `/meeting-minutes [녹취파일]` 실행.

---

## 트러블슈팅

- `FAIL: PyYAML not installed` → `pip install pyyaml`.
- `mapfile: command not found` (verify.sh, macOS) → 기본 bash 3.2. `brew install bash` 후 `/opt/homebrew/bin/bash verify.sh`.
- Python 한글 깨짐(Windows) → `set PYTHONUTF8=1` 후 실행(스크립트는 이미 reconfigure 처리).
- Slack/Gmail 도구 호출 실패 → 정상. 스킬이 `.md` fallback으로 전환됨.
