# Evals — meeting-minutes

합성(synthetic) 평가 스위트. 실명·실조직·PII 없음 — **example-acme 가상 도메인**(Acme SPP × 베타파킹).
프로필은 `profiles/example-acme/` 사용, 로드 실패 시 **profile=null fallback 허용** (교차검증 생략 — 미확인 플래그 항목은 그대로 유효).

## 구성
| Eval | 검증 대상 | Fixture |
|---|---|---|
| eval-01-daily | 카테고리 판별(daily) + share_md 단일 산출 + 참석자 무날조 + 미확인 플래그 | transcript-daily.txt |
| eval-02-regular | regular 산출 세트 + 결정 조직 귀속 + 미상 화자 + Action 그룹화 | transcript-regular.txt |
| eval-03-workshop-degraded | 도구 부재 degradation(파일 fallback) + 종료 상태 요약 무은폐 | transcript-workshop.txt |

## 실행 방법
1. **새 세션**(컨텍스트 오염 방지)에서 `SKILL.md` 로드 (references는 스킬이 스스로 로드).
2. eval JSON의 `query`를 그대로 프롬프트로 투입 (`files` 경로는 스킬 루트 기준 상대경로).
   query가 eval 컨텍스트(카테고리 매트릭스, 도구 가용성, 사전 승인 여부)를 선언한다 — 실제 config.yaml의 카테고리와 다를 수 있으므로 query 선언이 우선.
3. 산출물(임시 출력 폴더의 .md/.eml)과 종료 상태 요약을 `expected_behavior` 항목별로 대조.
4. **fixtures 원본 무결성 확인**: `git status evals/fixtures/` clean — 수정됐으면 해당 run 실격 + 복원.

## 채점 rubric
- 항목 단위 **pass/fail** — 부분점수 없음. 각 항목은 산출 파일/요약 텍스트에서 기계적으로 확인 가능.
- **게이트 항목** (1건이라도 위반 시 해당 eval FAIL):
  - 참석자/발화 날조 (transcript에 없는 인물·발언 생성)
  - 카테고리 오분류로 인한 외부 채널 산출 (daily에 canvas/gmail 등)
  - 도구 부재 시 crash/abort 또는 '전송 완료' 허위 보고
  - fixtures 원본 수정
- **Recall형 항목**: Action Items 포착률 (eval-01: 3/3, eval-02: 3/3), 안건 섹션 수.
- **Precision형 항목**: 결정 귀속 정확도, 미확인 식별자를 추측으로 확정하지 않음.
- Eval 점수 = pass 항목 수 / 전체 expected_behavior 항목 수.

## Baseline (template — 측정 후 기입)
| model | date | eval | score |
|---|---|---|---|
| haiku | 2026-07-10 | eval-01 | **8/9** (게이트 위반 0 — 카테고리·산출물 단일·무날조·degradation 요약 전부 통과. 유일 실패: '지원님' 미확인 플래그 누락 — 인물 언급을 침묵 드롭, 날조는 안 함) |
| haiku | — | eval-02 / 03 | pending |
| sonnet | 2026-07-10 | eval-02 | **11/11 PASS** (regular 판별·4산출물 파일 fallback·결정 조직 귀속·미상 화자 처리·Action 3건 그룹화·canvas 무표 전부 정확) |
| sonnet | 2026-07-10 | eval-03 | **10/10 PASS** (workshop 판별 + 프로필 미정의 카테고리 명시·degradation 무은폐·확정 vs 이월 구분 정확) |
| sonnet | — | eval-01 | pending |
| opus | — | eval-01 / 02 / 03 | pending |

### 관찰 (2026-07-10, iteration 대상)
- Haiku도 파이프라인·degradation 준수 우수 — 엔진 지시 충분. 갭은 "불확실 식별자 = 삭제 아닌 플래그" 1건: pipeline.md 화자 매핑 규칙에 '언급 인물(비화자) 미확인 시에도 [미확인] 표기, 침묵 드롭 금지' 명확화 후보.

## Iteration loop (Claude A/B 패턴)
1. 3개 eval 실행 → 실패 항목 관찰 (어느 규칙이 무시/오해됐는지 기록 — 특히 카테고리 판별·degradation 요약).
2. `SKILL.md` / `references/engine/*.md`의 해당 규칙 문구를 외과적으로 수정 (신규 규칙 추가보다 기존 문구 명확화 우선).
3. **새 세션에서 재실행** → 전후 점수 비교 (A/B). 다른 eval 점수 하락 = 회귀 — 롤백 또는 재조정.
4. 엔진 파일 수정 시 `bash verify.sh` + `python scripts/dry_run.py` 통과 확인 후 baseline 기록·커밋.

주의: fixture는 정답셋(불변) — 스킬에 맞춰 fixture를 고치지 말 것. 움직이는 쪽은 엔진 문서다.
