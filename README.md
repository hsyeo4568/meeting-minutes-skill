# Meeting Transcript Toolkit

회의 **녹취 → 오타 교정 → 회의록** 자동화 Claude 스킬 모음

```
녹취 .txt ──▶ [stt-transcript-fix] ──▶ 교정된 녹취 ──▶ [meeting-minutes] ──▶ 회의록 (팀챗/Canvas/메일)
              오타·문맥 교정                              카테고리별 산출물
              + (*...) 코멘트 자동 마킹                    + 맥락 연계·Action Items
```

| 스킬 | 역할 |
|------|------|
| [`skills/stt-transcript-fix/`](skills/stt-transcript-fix/) | STT 녹취 오타·문맥 교정(원본 fidelity 유지) + 인사이트/to-do `(*...)` 자동 마킹. **meeting-minutes profile 용어사전과 병행 시 효과 최대** — 단독 설치 시 사용자 괄호교정·명백한 문맥 교정만 동작 |
| [`skills/meeting-minutes/`](skills/meeting-minutes/) | 회의록 자동화 엔진 — 회의 종류별 산출물, 이전 회의 연계, 조직별 Action Items |

- 두 스킬은 **profile**(팀 용어사전·인명·회의 구조) 공유
- 엔진은 범용, 팀 데이터는 profile에만 위치

---

## 설치 — Claude에게 위임

### 신규 설치

- Claude Code 대화창에 아래 한 줄 전달

  ```
  https://github.com/hsyeo4568/meeting-minutes-skill 의 INSTALL.md를 읽고 내 환경에 맞게 설치해줘
  ```

- Claude가 [`INSTALL.md`](INSTALL.md) 런북대로 OS·설치 경로·기존 설치 여부 판정 → 복사 → 의존성 설치 → 검증까지 수행
- 최초 `/meeting-minutes` 실행 시 온보딩 인터뷰가 이름·조직·회의 종류·용어를 질의 → config·profile 자동 생성
- 수동 설치는 아래 **경로 B**, 설치 없이 사용은 **경로 C** 참조

### 기존 버전 사용 중이면 재설치 금지 → 업데이트

- 개인 `config.yaml`·profile은 유지하고 엔진만 교체하는 스크립트 사용 (clone 후 실행)

  ```bash
  python skills/meeting-minutes/scripts/update_install.py --target ~/.claude/skills/meeting-minutes          # 변경 계획만 출력
  python skills/meeting-minutes/scripts/update_install.py --target ~/.claude/skills/meeting-minutes --apply  # 적용 (백업 자동)
  ```

- Claude에게 위임 시에도 위 한 줄이면 충분 — `INSTALL.md`가 기존 설치를 인식해 이 경로로 분기
- 변경 내역: [`CHANGELOG.md`](CHANGELOG.md)

---

## 시작하기 — 상황별 경로

### 경로 A: Claude Code 최초 사용자 (설치부터)

1. **Claude Code 설치** (Pro/Max 요금제 또는 API 키 필요)
   ```
   # Windows (PowerShell) / macOS / Linux 공통 — Node.js 18+ 필요
   npm install -g @anthropic-ai/claude-code
   ```
2. 터미널에서 `claude` 실행 → 로그인. 상세: https://docs.anthropic.com/claude-code
3. 이후 **경로 B**로 진행

### 경로 B: Claude Code 사용자 (스킬 설치)

1. 저장소 clone 후 스킬 폴더로 복사

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
2. Claude Code에 녹취 전달 + "회의록 만들어줘" → **config 부재 시 온보딩 인터뷰 자동 시작**(이름·조직·회의 종류·용어 질의 후 profile 생성). 상세: [`skills/meeting-minutes/SETUP.md`](skills/meeting-minutes/SETUP.md)
3. 녹취 교정: "이 녹취 파일 오타 교정해줘" → stt-transcript-fix가 처리

### 경로 C: 무료 요금제 / Claude Code 미사용 (복붙만)

- 파일·설치 불필요. **claude.ai 웹 채팅(무료)** 에서 사용
1. 회의록: [`skills/meeting-minutes/PROMPT-ONLY.md`](skills/meeting-minutes/PROMPT-ONLY.md) 전문 복사 → 채팅에 붙여넣기 → 맨 아래 「입력」에 녹취 입력 후 전송
2. 녹취 교정: [`skills/stt-transcript-fix/PROMPT-ONLY.md`](skills/stt-transcript-fix/PROMPT-ONLY.md) 동일 방식
- 자동화(파일 수정·이전 회의 연계·자동 공유)는 미지원, 작성 규칙·교정 규칙은 동일 적용

---

## Profile — 팀 데이터 위치

- 엔진(이 저장소)에 **팀·회사 데이터 없음** → 전부 placeholder / 가상 예시(`example-acme`)
- 온보딩 인터뷰가 `profiles/<우리팀>/` 생성: 용어사전(`domain-glossary.md`) · 인명(`contacts.md`) · 회의 구조(`structure.md`) · 표기 규칙(`conventions.md`)
- 빈 틀에서 시작 → [`profiles/_template/`](skills/meeting-minutes/profiles/_template/) 복사
- 채워진 예시 확인 → [`profiles/example-acme/`](skills/meeting-minutes/profiles/example-acme/) 참조

## ⚠️ 보안 — 필독

- **개인 profile(실명·고객·사내 정보)의 public 저장소 커밋 금지** — 이 저장소 `.gitignore`가 `config.yaml`·개인 profile을 차단하나, 포크·재배포 시 직접 확인 필요
- 검증 스크립트: `bash skills/meeting-minutes/verify.sh` — 엔진 순수성(고유명사 누출)·placeholder 정합성 게이트
- 녹취 원문에는 개인정보 포함 → 녹취 파일 자체의 저장소 업로드 금지

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
└── scripts/ + verify.sh  # 빌드·검증 (update_install.py = 기존 설치 갱신)

skills/stt-transcript-fix/
├── SKILL.md              # 교정 엔진 (Tier-A/B, 괄호 4종, 자동 마킹)
└── PROMPT-ONLY.md        # 무료판 복붙 프롬프트

sync-public.py            # (메인테이너용) 로컬 작업본 → 이 repo 동기화 + 누출 게이트
                          # 경로·비공개 denylist는 sync-config.local.json(gitignored)에 위치
```

## 라이선스 / 문의

- 사내 세미나 공유용
- 이슈·개선 제안은 GitHub Issues로
