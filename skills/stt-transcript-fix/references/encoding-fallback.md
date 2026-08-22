# Encoding and recovery fallback

기본 경로는 `fix_template.py`다. 이 스크립트는 UTF-16 BOM을 감지하고 원래 인코딩과 BOM을 보존하며, backup·count 검증·mask 복원·atomic replace를 수행한다.

## 기본 실행 전 확인

- 읽은 원문이 깨져 보이면 UTF-16 가능성을 먼저 확인한다. 임의로 UTF-8 전체 쓰기를 하지 않는다.
- Python 보조 스크립트는 `PYTHONUTF8=1`로 실행해 cp949 환경의 한국어 손상을 피한다.
- 부분 읽기·중간 실패·mask violation 상태에서는 쓰지 않는다.

## MSYS 경로와 임시 파일

- MSYS bash의 `/c/...` 경로를 Windows python에 그대로 넘기지 않는다. `cygpath -m`으로 `C:/...` 형식으로 바꿔 전달하고, Windows 경로를 bash에서 다룰 때는 `cygpath -u`로 되돌린다. 경로가 안 맞으면 스크립트는 "파일 없음"으로 조용히 끝난다.
- 후보 manifest와 중간 산출물은 `mktemp`로 만들고 `trap 'rm -f "$manifest"' EXIT`로 종료 시 지운다. manifest에는 실제 발화가 들어가므로 `$LOCALAPPDATA/Temp` 밖에 남기지 않는다.
- 콘솔이 CP949일 때 한국어가 깨져 보이면 출력 인코딩 문제지 원문 손상이 아니다. `PYTHONUTF8=1`로 다시 실행해 구분한 뒤 판단한다. 이 구분 없이 "원문이 깨졌다"고 보고 재인코딩하면 멀쩡한 원문을 망친다.

## fallback 사용 조건

`fix_template.py`가 없거나 실행 자체가 막힌 경우에만 fallback을 사용한다. fallback은 다음 순서를 모두 지켜야 한다.

1. 원문을 byte 단위 backup으로 복사하고 원래 인코딩/BOM을 기록한다.
2. 계획한 변형을 한 번의 alternation 검색으로 수집하고, mask된 span 밖의 정확한 occurrence 수를 검증한다.
3. substring 충돌은 경계 정규식으로 처리하며, 원문 기준 count가 맞지 않으면 적용하지 않는다.
4. 쓰기 뒤 원본과 결과의 **line-count parity**를 확인한다. 줄 수가 달라지거나 decode/encode 오류가 나면 즉시 **restore**하고 실패로 보고한다.
5. 복구 이후에는 수정본을 재시도하지 않는다. 원인·backup 경로·보류 항목을 Tier-C로 반환한다.

## 금지 사항

- 원문 인코딩을 추정으로 변경하지 않는다.
- shell `diff` 출력만으로 동일성을 판단하지 않는다. Python에서 원본/결과를 같은 인코딩으로 읽어 줄 수와 계획한 변경만 비교한다.
- 숫자·단위·화자 라벨을 fallback으로 우회 수정하지 않는다.

성공한 apply 또는 확인된 무변경 처리 뒤에만 `fixstamp.py write`를 한 번 실행한다. pending receipt hash가 현재 원문과 다르면 stamp하지 않고 보류한다.
