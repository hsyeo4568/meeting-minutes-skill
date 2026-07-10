# Evals — stt-transcript-fix

합성(synthetic) 평가 스위트. 실명·실조직·PII 없음 (Acme SPP 가상 도메인).
실데이터 회귀셋은 별도: `fixtures/FIXTURE-260703.md` (로컬 전용, 마킹 pass 전용).

## 구성
| Eval | 검증 대상 | Fixture |
|---|---|---|
| eval-01-basic-correction | Tier-A 교정 9종 + 보호(숫자/화자헤더/기존마커) + 신규 변형 반환 | transcript-01.txt + glossary-01.md |
| eval-02-tier-protection | Tier-C 홀드 4트랩 (무근거 인명 / 병기 명확화 / 수치 정규화 vs 값 변경 / 값 모순) | transcript-02.txt + glossary-01.md |
| eval-03-marking | 자동 마킹 3후보 + 과마킹 억제 (스몰토크/수긍/클러스터 dedup) | transcript-03.txt + glossary-01.md |

## 실행 방법
1. **새 세션**(컨텍스트 오염 방지)에서 `SKILL.md` 로드.
2. eval JSON의 `query`를 그대로 프롬프트로 투입 (`files` 경로는 스킬 루트 기준 상대경로).
3. 실행이 끝나면 산출물(교정 사본 + 보고서)을 `expected_behavior` 항목별로 대조.
4. **fixtures 원본 무결성 확인**: `git status evals/fixtures/` clean 이어야 함 (수정됐으면 해당 run 전체 실격 + `git checkout`으로 복원).

## 채점 rubric
- 항목 단위 **pass/fail** — 부분점수 없음. 각 항목은 diff/파일/보고서에서 기계적으로 확인 가능.
- **Recall** = (적용된 seeded 교정 수) / (seeded 교정 총수) — eval-01: 9종(오티에이 2곳 포함 10곳).
- **Precision** = (정당한 변경 수) / (전체 변경 수) — 보호 대상(숫자·화자헤더·마커 내부·트랩)을 건드리면 분모만 증가.
- **보호 항목은 게이트**: 숫자 변경 / 화자 헤더 편집 / `(*...)` 마커 훼손 / fixtures 원본 수정 중 1건이라도 발생하면 해당 eval **FAIL** (recall과 무관).
- eval-03: recall = 3후보 중 검출 수, precision = 정당 마커 / 전체 삽입 마커. 목표 recall ≥ 90%, precision ≥ 85% (FIXTURE-260703 기준과 동일).
- Eval 점수 = pass 항목 수 / 전체 expected_behavior 항목 수.

## Baseline (template — 측정 후 기입)
| model | date | eval | score |
|---|---|---|---|
| haiku | 2026-07-10 | eval-01 | **11/16 + 게이트 2위반 → FAIL** (화자헤더 편집 의심, 미등재 변형 '임피던슨'→'임피던수' 오적용·미반환; 파크뷰 공백변형·에스피피 recall 미스; 마킹 cap 산식 오계산 max(15,2)→2) |
| haiku | — | eval-02 / 03 | pending |
| sonnet | 2026-07-10 | eval-01 | **16/16 PASS** (마커 내부 보호·화자헤더 홀드+오귀속 보고·신규 변형 반환 전부 정확) |
| sonnet | — | eval-02 / 03 | pending |
| opus | — | eval-01 / 02 / 03 | pending |

### 관찰 (2026-07-10, iteration 대상)
- **Haiku 계열 갭**: SKILL.md "Standard model tier is enough"는 Sonnet 기준 — Haiku는 ① 화자 헤더 vs 본문 인명 구분 ② 미등재 변형=Tier-B(반환) 규칙 ③ 마킹 cap 산식을 놓침. Haiku 위임 시 이 3규칙을 프롬프트에 명시 재강조 필요 (또는 Haiku 위임 비권장을 SKILL.md에 명문화).

## Iteration loop (Claude A/B 패턴)
1. 위 3개 eval 실행 → 실패 항목 관찰 (어느 규칙이 무시/오해됐는지 기록).
2. `SKILL.md`의 해당 규칙 문구를 외과적으로 수정 (규칙 추가보다 기존 문구 명확화 우선).
3. **새 세션에서 재실행** → 점수 전후 비교 (A/B). 다른 eval 점수가 떨어지면 회귀 — 수정 롤백 또는 재조정.
4. 통과 후 실데이터 회귀셋(FIXTURE-260703)으로 blind 재검증.
5. baseline 표에 model/date/score 기록 후 커밋.

주의: eval fixture 자체를 스킬에 맞춰 고치지 말 것 — fixture는 정답셋(불변), 움직이는 쪽은 SKILL.md.
