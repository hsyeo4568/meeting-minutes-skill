# Meeting Transcript Toolkit

회의 **녹취 → 오타 교정 → 회의록**을 자동화하는 Claude 스킬 모음.

```
녹취 .txt ──▶ [stt-transcript-fix] ──▶ 교정된 녹취 ──▶ [meeting-minutes] ──▶ 회의록 (팀챗/Canvas/메일)
              오타·문맥 교정                              카테고리별 산출물
              + (*...) 코멘트 자동 마킹                    + 맥락 연계·Action Items
```

| 스킬 | 역할 |
|------|------|
| [`skills/stt-transcript-fix/`](skills/stt-transcript-fix/) | STT 녹취 오타·문맥 교정 (원본 fidelity 유지) + 인사이트/to-do `(*...)` 자동 마킹 |
| [`skills/meeting-minutes/`](skills/meeting-minutes/) | 회의록 자동화 엔진 — 회의 종류별 산출물, 이전 회의 연계, 조직별 Action Items |

두 스킬은 **profile**(우리 팀의 용어사전·인명·회의 구조)을 공유한다. 엔진은 범용, 팀 데이터는 profile에만.

---

## 시작하기 — 내 상황에 맞는 경로 선택

### 경로 A: Claude Code가 처음인 경우 (설치부터)

1. **Claude Code 설치** (Pro/Max 요금제 또는 API 키 필요):
   ```
   # Windows (PowerShell) / macOS / Linux 공통 — Node.js 18+ 필요
   npm install -g @anthropic-ai/claude-code
   ```
   터미널에서 `claude` 실행 → 로그인. 상세: https://docs.anthropic.com/claude-code
2. 아래 **경로 B**로 계속.

### 경로 B: Claude Code 사용자 (스킬 설치)

1. 이 저장소를 받아 스킬 폴더로 복사:
   ```bash
   git clone https://github.com/hsyeo4568/meeting-minutes-skill.git
   cp -r meeting-minutes-skill/skills/meeting-minutes ~/.claude/skills/
   cp -r meeting-minutes-skill/skills/stt-transcript-fix ~/.claude/skills/
   ```
   (Windows PowerShell: `Copy-Item -Recurse` 동일 구조. 개인 스킬 폴더 = `~/.claude/skills/`)
2. Claude Code에서 회의 녹취를 주고 "회의록 만들어줘"라고 하면 —
   **config가 없으면 온보딩 인터뷰가 자동 시작**된다 (내 이름·조직·회의 종류·용어를 묻고 profile 생성). 상세: [`skills/meeting-minutes/SETUP.md`](skills/meeting-minutes/SETUP.md)
3. 녹취 교정: "이 녹취 파일 오타 교정해줘" → stt-transcript-fix가 처리.

### 경로 C: 무료 요금제 / Claude Code 없이 (복붙만)

파일·설치 전혀 필요 없음. **claude.ai 웹 채팅(무료)** 에서:

1. 회의록: [`skills/meeting-minutes/PROMPT-ONLY.md`](skills/meeting-minutes/PROMPT-ONLY.md) 전문 복사 → 채팅에 붙여넣기 → 맨 아래 「입력」에 녹취 넣고 전송.
2. 녹취 교정: [`skills/stt-transcript-fix/PROMPT-ONLY.md`](skills/stt-transcript-fix/PROMPT-ONLY.md) 동일 방식.

자동화(파일 수정·이전 회의 연계·자동 공유)는 없지만 작성 규칙·교정 규칙은 동일하게 적용된다.

---

## Profile — 우리 팀 데이터는 어디에?

- 엔진(이 저장소)에는 **팀·회사 데이터가 없다.** 전부 placeholder / 가상 예시(`example-acme`).
- 온보딩 인터뷰가 `profiles/<우리팀>/`을 만들어 준다: 용어사전(`domain-glossary.md`) · 인명(`contacts.md`) · 회의 구조(`structure.md`) · 표기 규칙(`conventions.md`).
- 빈 틀에서 직접 시작하려면 [`profiles/_template/`](skills/meeting-minutes/profiles/_template/) 복사, 채워진 모습을 보려면 [`profiles/example-acme/`](skills/meeting-minutes/profiles/example-acme/) 참고.

## ⚠️ 보안 — 반드시 읽기

- **자기 profile(실제 인명·고객·사내 정보)을 public 저장소에 커밋하지 말 것.** 이 저장소의 `.gitignore`가 `config.yaml`과 개인 profile을 차단하지만, 포크/재배포 시 직접 확인해야 한다.
- 검증 스크립트: `bash skills/meeting-minutes/verify.sh` — 엔진 순수성(고유명사 누출)·placeholder 정합성 게이트.
- 녹취 원문에는 개인정보가 들어 있다 — 녹취 파일 자체를 저장소에 올리지 말 것.

## 구성 요소

```
skills/meeting-minutes/
├── SKILL.md              # 엔진 본체 (Claude Code가 읽는 지침)
├── ONBOARDING.md         # 첫 실행 인터뷰 스크립트
├── SETUP.md              # 수동 설정 가이드
├── PROMPT-ONLY.md        # 무료판 복붙 프롬프트
├── config.example.yaml   # 설정 템플릿
├── profiles/             # _template(빈 틀) + example-acme(가상 예시)
├── references/engine/    # 파이프라인·작성원칙·산출물 템플릿·도구 연동
└── scripts/ + verify.sh  # 빌드·검증

skills/stt-transcript-fix/
├── SKILL.md              # 교정 엔진 (Tier-A/B, 괄호 4종, 자동 마킹)
└── PROMPT-ONLY.md        # 무료판 복붙 프롬프트

sync-public.py            # (메인테이너용) 로컬 작업본 → 이 repo 동기화 + 누출 게이트.
                          # 경로·비공개 denylist는 sync-config.local.json(gitignored)에.
```

## 라이선스 / 문의

사내 세미나 공유용. 이슈·개선 제안은 GitHub Issues로.
