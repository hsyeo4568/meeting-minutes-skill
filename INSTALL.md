# INSTALL — Claude에게 위임하는 설치

> **사용법** — Claude Code 대화창에 아래 한 줄 전달
>
> ```
> https://github.com/hsyeo4568/meeting-minutes-skill 의 INSTALL.md를 읽고 내 환경에 맞게 설치해줘
> ```
>
> 직접 설치할 경우 이 문서 대신 [`skills/meeting-minutes/SETUP.md`](skills/meeting-minutes/SETUP.md) 참조 (선택 통합·트러블슈팅 포함)

---

## Claude 실행 지침 — 아래 순서 준수

- 각 단계 = **확인 → 실행 → 검증**
- 검증 실패 시 다음 단계 진행 금지 → 막힌 지점을 사용자에게 보고

### 0. 갈림길 판정 (질의 금지, 관찰로 결정)

- `claude --version` 동작 환경(= 현재 대화가 Claude Code) → **1단계 진행**
- 웹/데스크톱 채팅 → 설치 대상 없음
  - [`skills/meeting-minutes/PROMPT-ONLY.md`](skills/meeting-minutes/PROMPT-ONLY.md) 전문 복사 후 채팅에 붙여넣도록 안내 → **여기서 종료**

### 1. 설치 위치 결정

| 상황 | 위치 |
|---|---|
| 기본 (모든 프로젝트에서 사용) | `~/.claude/skills/` (Windows: `%USERPROFILE%\.claude\skills\`) |
| 특정 저장소에서만 사용 | `<프로젝트>/.claude/skills/` |

- 사용자 지정이 없으면 **전역** 사용 → 결정된 경로를 이후 `SKILLS_DIR`로 지칭
- **기존 설치 여부 우선 확인** — `$SKILLS_DIR/meeting-minutes/` 존재 시 신규 아닌 **업그레이드** → 3단계에서 분기

### 2. 소스 확보

- 임시 폴더에 clone (작업 폴더 오염 금지)

  ```bash
  git clone --depth 1 https://github.com/hsyeo4568/meeting-minutes-skill.git /tmp/mm-skill
  ```

  Windows PowerShell:

  ```powershell
  git clone --depth 1 https://github.com/hsyeo4568/meeting-minutes-skill.git "$env:TEMP\mm-skill"
  ```

- `git` 부재 시 GitHub zip 다운로드로 대체

### 3. 복사 — 신규 vs 업그레이드

**신규 설치** (대상 폴더 없음) — 두 스킬 폴더 통째 복사

```bash
mkdir -p ~/.claude/skills
cp -r /tmp/mm-skill/skills/meeting-minutes    ~/.claude/skills/
cp -r /tmp/mm-skill/skills/stt-transcript-fix ~/.claude/skills/
```

```powershell
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
Copy-Item -Recurse "$env:TEMP\mm-skill\skills\meeting-minutes"    "$HOME\.claude\skills\"
Copy-Item -Recurse "$env:TEMP\mm-skill\skills\stt-transcript-fix" "$HOME\.claude\skills\"
```

**업그레이드** (대상 폴더 존재) — **수동 복사 금지**, 전용 스크립트 사용

- 사유: 온보딩으로 채운 `config.yaml`·개인 profile이 초기값으로 복원되면 업데이트 안 하느니만 못함

```bash
# 1) 변경 계획 확인 (파일 미기록)
python /tmp/mm-skill/skills/meeting-minutes/scripts/update_install.py \
    --target ~/.claude/skills/meeting-minutes

# 2) 적용
python /tmp/mm-skill/skills/meeting-minutes/scripts/update_install.py \
    --target ~/.claude/skills/meeting-minutes --apply
```

- PowerShell은 경로만 `"$env:TEMP\mm-skill\..."` · `"$HOME\.claude\skills\meeting-minutes"`로 치환
- `stt-transcript-fix`는 사용자 데이터 없음 → 폴더째 덮어쓰기 가능

스크립트 보장 사항

- 개인 profile(`_template`·`example-acme` 외 전 디렉터리) · `verify-denylist.local` · `.mm/` · 로컬 `fixtures/`(실제 녹취 보관처) → **기록·삭제 모두 없음**
- `config.yaml` → 수정 없음. 복사 완료 후 신규 설정 키 안내 목적의 읽기만 수행
- 엔진 파일만 교체, 상위에서 제거된 엔진 파일은 여기서도 삭제
- `--apply` 시 `<스킬폴더>.backup.<날짜-시각>` 통째 백업 선행
- 완료 후 `config.example.yaml` 신규 키 안내 (이번 릴리스: `body_mode` · `materials` · `runtime.*` — 미설정이어도 동작)

- 스크립트가 없는 구버전 설치 → clone 쪽 스크립트 그대로 사용 (위 명령이 이미 clone 경로 지정)
- 복사 완료 후 임시 clone 삭제

### 4. 의존성

```bash
cd ~/.claude/skills/meeting-minutes
pip install -r requirements.txt      # pyyaml + python-pptx + openpyxl
python scripts/preflight.py          # → READY 출력 필요
```

- 시스템 Python이 외부 패키지 설치를 차단하는 경우(PEP 668 등) → venv 또는 `--user`로 우회, 선택한 방식을 사용자에게 보고
- `preflight.py` REQUIRED 항목 미충족 시 **즉시 중단** → 해당 항목 설치 명령 안내
- OPTIONAL(Slack·Gmail·검색·지식그래프) 미설치는 정상 → 산출물을 `.md` 파일로 대체 출력

### 5. 설정 — 질의 금지, 온보딩 인터뷰에 위임

- `config.yaml` 부재 시 **직접 생성 금지**
- 스킬 내장 온보딩 인터뷰(`ONBOARDING.md`)가 최초 `/meeting-minutes` 호출 시 이름·조직·회의 종류·용어를 질의 → `config.yaml` + `profiles/<팀>/` 생성
- 이것이 "각자 환경에 맞게" 적용되는 정식 경로
- 업그레이드로 `config.yaml`이 이미 있으면 그대로 두고 검증만 수행

  ```bash
  python scripts/dry_run.py            # → PASS
  ```

- `dry_run.py`가 `body_mode`로 FAIL → 오타 (`chronological` 또는 `axis`만 유효)

### 6. 마무리 보고

아래 4가지만 간결히 보고

1. 설치 경로 (신규 / 업그레이드 구분)
2. `preflight.py` 결과 — READY 여부, OPTIONAL 미충족 목록
3. 다음 행동 — `/meeting-minutes <녹취파일>`, config 부재 시 온보딩 인터뷰 선행
4. 업그레이드였을 경우 백업 폴더 경로

### 금지 사항

- 사용자 `config.yaml`·개인 profile을 **어떤 저장소에도 커밋 금지** (실명·고객명·연락처 포함)
- 녹취 원문(`.txt`) 저장소 반입 금지
- 기존 설치를 백업 없이 덮어쓰기 금지
- `verify.sh`는 **스킬 수정 시** 게이트 → 설치 목적 실행에서 실패해도 설치 실패 아님 (macOS 기본 bash 3.2는 `mapfile: command not found`로 종료 → `brew install bash`)
