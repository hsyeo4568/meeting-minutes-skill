# INSTALL — Claude에게 시키는 설치

> **사용법:** Claude Code 대화창에 아래 한 줄을 붙여넣으면 된다.
>
> ```
> https://github.com/hsyeo4568/meeting-minutes-skill 의 INSTALL.md를 읽고 내 환경에 맞게 설치해줘
> ```
>
> 사람이 직접 손으로 설치하려면 이 문서 말고 [`skills/meeting-minutes/SETUP.md`](skills/meeting-minutes/SETUP.md)를 보면 된다(선택 통합·트러블슈팅 포함).

---

## Claude에게: 이 순서대로 실행할 것

각 단계는 **확인 → 실행 → 검증**이다. 검증이 실패하면 다음 단계로 넘어가지 말고 사용자에게 무엇이 막혔는지 말할 것.

### 0. 갈림길 판정 (질문하지 말고 관찰로 결정)

- `claude --version`이 도는 환경(=지금 이 대화가 Claude Code)이면 → **1단계로**.
- Claude Code가 아닌 웹/데스크톱 채팅이면 → 설치할 것이 없다. 사용자에게
  [`skills/meeting-minutes/PROMPT-ONLY.md`](skills/meeting-minutes/PROMPT-ONLY.md) 전문을 복사해 채팅에 붙여넣으라고 안내하고 **여기서 끝낸다.**

### 1. 설치 위치 결정

| 상황 | 위치 |
|---|---|
| 기본 (모든 프로젝트에서 쓰기) | `~/.claude/skills/` (Windows: `%USERPROFILE%\.claude\skills\`) |
| 특정 저장소에서만 쓰기 | `<프로젝트>/.claude/skills/` |

사용자가 따로 말하지 않았으면 **전역**을 쓴다. 결정한 경로를 이후 `SKILLS_DIR`로 부른다.

**이미 설치돼 있는지 먼저 본다** — `$SKILLS_DIR/meeting-minutes/`가 있으면 신규 설치가 아니라 **업그레이드**다. 3단계에서 분기.

### 2. 소스 받기

임시 폴더에 clone한다(작업 폴더를 어지럽히지 말 것).

```bash
git clone --depth 1 https://github.com/hsyeo4568/meeting-minutes-skill.git /tmp/mm-skill
```

Windows PowerShell:

```powershell
git clone --depth 1 https://github.com/hsyeo4568/meeting-minutes-skill.git "$env:TEMP\mm-skill"
```

`git`이 없으면 GitHub의 zip 다운로드로 대체한다.

### 3. 복사 — 신규 vs 업그레이드

**신규 설치** (대상 폴더 없음): 두 스킬 폴더를 통째로 복사.

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

**업그레이드** (대상 폴더 있음): **손으로 복사하지 말 것.** 전용 스크립트가 있다. 사용자가 온보딩으로 채운 `config.yaml`과 자기 profile을 되돌려버리면 업데이트 안 하느니만 못하다.

```bash
# 1) 무엇이 바뀌는지 먼저 본다 (아무것도 안 씀)
python /tmp/mm-skill/skills/meeting-minutes/scripts/update_install.py \
    --target ~/.claude/skills/meeting-minutes

# 2) 적용
python /tmp/mm-skill/skills/meeting-minutes/scripts/update_install.py \
    --target ~/.claude/skills/meeting-minutes --apply
```

PowerShell이면 경로만 `"$env:TEMP\mm-skill\..."`, `"$HOME\.claude\skills\meeting-minutes"`로 바꾼다. `stt-transcript-fix`는 사용자 데이터가 없으므로 폴더째 덮어써도 된다.

스크립트가 보장하는 것:

- 사용자 profile(`_template`·`example-acme`가 아닌 모든 디렉터리), `verify-denylist.local`, `.mm/`, 로컬 `fixtures/`(실제 녹취가 들어 있는 곳)는 **쓰지도 지우지도 않는다.** `config.yaml`도 마찬가지로 수정하지 않으며, 복사가 끝난 뒤 새로 생긴 설정 키를 알려주기 위해 읽기만 한다.
- 엔진 파일만 교체하고, 상위에서 없어진 엔진 파일은 여기서도 지운다.
- `--apply` 시 `<스킬폴더>.backup.<날짜-시각>`으로 통째 백업을 먼저 뜬다.
- 끝나고 `config.example.yaml`에 새로 생긴 키를 알려준다(이번 릴리스: `body_mode`, `materials`, `runtime.*` — 없어도 그대로 동작한다).

스크립트가 없는 아주 오래된 설치라면, clone 쪽 스크립트를 그대로 쓰면 된다(위 명령이 이미 clone 경로를 가리킨다).

복사가 끝나면 임시 clone을 지운다.

### 4. 의존성

```bash
cd ~/.claude/skills/meeting-minutes
pip install -r requirements.txt      # pyyaml + python-pptx + openpyxl
python scripts/preflight.py          # → READY 가 떠야 함
```

- 시스템 Python이 외부 패키지 설치를 막으면(PEP 668 등) venv나 `--user`로 우회한다. 사용자에게 무엇을 골랐는지 알린다.
- `preflight.py`가 REQUIRED를 하나라도 빨간색으로 표시하면 **여기서 멈추고** 그 항목의 설치 명령을 사용자에게 준다. OPTIONAL(Slack·Gmail·검색·지식그래프)은 없어도 정상 — 없으면 결과를 `.md` 파일로 떨어뜨린다.

### 5. 설정 — 묻지 말고 인터뷰에 맡긴다

`config.yaml`이 없으면 **직접 만들지 말 것.** 스킬 자체에 온보딩 인터뷰(`ONBOARDING.md`)가 들어 있어서, 사용자가 처음 `/meeting-minutes`를 부르면 이름·조직·회의 종류·용어를 묻고 `config.yaml` + `profiles/<팀>/`을 만들어 준다. 그게 "각자 환경에 맞게" 적용되는 경로다.

업그레이드라 `config.yaml`이 이미 있으면 그대로 두고 검증만 돌린다:

```bash
python scripts/dry_run.py            # → PASS
```

`dry_run.py`가 `body_mode` 값으로 FAIL하면 오타다(`chronological` 또는 `axis`만 유효).

### 6. 마무리 보고

사용자에게 **다음 4가지만** 짧게 보고한다.

1. 설치 경로(신규/업그레이드 중 무엇이었는지)
2. `preflight.py` 결과 — READY 여부, OPTIONAL 중 빠진 것 목록
3. 다음 행동: `/meeting-minutes <녹취파일>` — config가 없으면 온보딩 인터뷰가 먼저 뜬다는 것
4. 업그레이드였다면 백업 폴더 경로

### 하지 말 것

- 사용자의 `config.yaml`이나 개인 profile을 **어떤 저장소에도 커밋하지 않는다.** 실명·고객명·연락처가 들어 있다.
- 녹취 원문(`.txt`)을 저장소에 넣지 않는다.
- 기존 설치를 백업 없이 덮지 않는다.
- `verify.sh`는 **스킬을 수정할 때** 도는 게이트다. 설치만 하는 경우 실패해도 설치 실패가 아니다(macOS 기본 bash 3.2에서는 `mapfile: command not found`로 넘어간다 — `brew install bash`).
