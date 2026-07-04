# Domain Glossary (profile: example-acme)

> 예시(가상) 프로필. 실데이터 아님 — 새 프로필 작성 시 형태 참고용.
>
> 회의 도메인의 고유 용어·인명·책임 소재·약어. 엔진은 이 파일을 교차검증에만 쓴다.
> 채우고 `config.project.profile`을 이 디렉터리로 가리키면 적용. 비우면(profile=null) 교차검증 생략.

## 인명 STT 오인식 매핑
<!-- 녹취에서 자주 틀리는 이름 → 정확한 이름. 예: 잘못표기 → 정확이름(소속) -->
- 박상우 → 박상호 (Acme PM)
- 김다은 → 김단아 (Acme Platform 백엔드)
- 이정훈 → 이종훈 (Acme Devices HW)
- 최서연 → 최세린 (Acme QA)
- 한가람 → 한가람 (혼동 없음 — 풀네임 유지)

## 책임 소재 매트릭스
<!-- 영역 → 담당 팀(단일 조직 Acme 내부 팀). 예: HW → Devices / 서버 → Platform -->
- 센서/단말 하드웨어 → Acme Devices
- 단말 펌웨어 / OTA 업데이트 → Acme Devices
- 클라우드 서버 / API / 대시보드 → Acme Platform
- 결제·정산 로직 → Acme Platform
- 현장 설치/유지보수 → Acme Devices
- 데이터 적재·집계 파이프라인 → Acme Platform

## 시장·제도 용어
<!-- 혼동 주의 용어. 예: 용어A ≠ 용어B (차이 설명) -->
- 점유율 ≠ 가동률 (점유율=주차면 점유 시간 비율 / 가동률=센서 정상 동작 시간 비율)
- 무정차 ≠ 무인 (무정차=차단기 미정차 통과 / 무인=현장 인력 부재)
- 정기권 ≠ 구독 (정기권=월 단위 선결제 면 배정 / 구독=B2C 앱 자동 갱신 요금제)
- 오인식 ≠ 미인식 (오인식=차량번호 잘못 읽음 / 미인식=아예 못 읽음)

## 약어
<!-- 약어 = 정식 명칭 -->
- SPP = Smart Parking Pilot (스마트 주차 시범사업)
- LPR = License Plate Recognition (차량번호 인식)
- OTA = Over-The-Air (무선 펌웨어 업데이트)
- SLA = Service Level Agreement (서비스 수준 협약)
- MAU = Monthly Active Users (월간 활성 사용자)
- POC = Proof of Concept (개념 검증)

## 세그먼트 (B2B / B2C)
<!-- 개별 사이트/지점명 대신 쓸 비즈니스 세그먼트. 예: B2B / B2C -->
- B2B = 빌딩·상가 주차장 운영사 대상 (정기권·정산 연동)
- B2C = 개인 운전자 앱 사용자 대상 (구독·간편결제)
