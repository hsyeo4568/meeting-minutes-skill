# Batch mode and manifest handling

이 문서는 사용자가 폴더를 지정했거나 대상이 3개 이상일 때만 적용한다. 단일 파일과 2개 파일은 메인 스레드에서 처리한다.

## 대상과 분할

1. 지정 폴더에서 `.txt`만 한 번 열거한다. 상위 회의 폴더를 재귀 탐색하지 않는다.
2. 고객·명단·로스터·연락처·참여자·인적처럼 개인정보를 암시하는 이름은 열지 않는다. 파일명만으로 분류·보고하며 `check`·`write`·`scan`·sidecar 생성을 모두 금지한다.
3. 3개 이상이면 파일당 한 작업자, 동시에 **max 3**만 실행한다. 한 작업자에게 폴더 전체를 넘기지 않는다.
4. 작업자에게는 미리 추출한 glossary §1·§7·§8만 전달한다. glossary는 **read-only**이며 작업자는 어떤 경우에도 수정하지 않는다.

## 명령 진입점과 lock

- 폴더 전체 훑기는 `fixstamp.py batch <folder> <glossary>`가 진입점이다. 민감 이름을 열지 않고 SKIP으로 집계하며 요약에 `n sensitive`를 남긴다.
- 파일 단위 명령(`check`·`write`·`scan`·`quick-scan`)에 폴더를 넘기면 `exit 4`로 거부된다. 반대로 `batch`에 파일을 넘기면 `ERROR: not a directory`다. 어느 쪽도 traceback으로 죽지 않는다.
- 각 원문은 `<transcript>.lock`(소유 PID 기록, 10분 초과 시 stale 정리)으로 직렬화된다. `fix_template.py`는 원문을 읽기 **전에** lock을 잡으므로 같은 파일에 작업자를 둘 붙이면 뒤쪽이 대기하거나 실패한다.
- lock 획득 실패는 **fail-closed**다. 건너뛰고 보고하며, lock 없이 우회 적용하지 않는다.
- `check`가 `unchanged`로 SKIP한 파일은 재적용 대상이 아니다. 다시 돌리려면 원문이 실제로 바뀌었거나 `SKILL_VERSION`이 올라가야 한다.

## Stamp와 manifest

- 민감 이름이 아닌 각 파일에만 `fixstamp.py check <target> <glossary>`를 먼저 실행한다. `0`은 원문을 읽지 않고 SKIP으로 보고한다.
- 새 파일(`1`)은 전체를 읽고, 변경/버전 변경(`2`/`3`)은 `scan`부터 시작한다. `review`가 비어 있고 마킹 요청도 없으면 scan 결과만 적용할 수 있다.
- Bash에서 후보 manifest는 반드시 `$LOCALAPPDATA/Temp`에 둔다. skill 폴더에는 실제 문장·이름이 담긴 JSON을 만들지 않는다.
  ```bash
  manifest="$LOCALAPPDATA/Temp/scanN.json"
  python "<skill root>/scripts/fixstamp.py" scan "$target" "$glossary" > "$manifest"
  python "<skill root>/scripts/fix_template.py" --json "$manifest" "$target"
  ```
- `fix_template.py`가 만든 `<transcript>.fixstamp.pending`은 post-apply hash 영수증이다. `fixstamp.py write`가 현재 원문 hash와 대조하고 성공 시에만 영수증을 삭제한다. 내용이 달라졌다면 stamp하지 않고 중단한다.

## Glossary 보호

병렬 작업 전에 메인 스레드는 기존 읽기 전용 상태를 기록한 뒤에만 보호 속성을 설정하고, 완료·중단 모두에서 **원래 상태로만** 되돌린다. 일괄적으로 보호를 해제하면 다른 작업의 보호까지 제거할 수 있으므로 금지한다. 새 변형은 작업자 보고에만 남기며, 메인 스레드가 사용자 확인 규칙에 따라 병합한다.

## 완료 보고

파일별로 `SKIP/처리/보류`, 적용 수, Tier-B/Tier-C 수, stamp 결과를 표로 반환한다. 전체 실행 후에도 각 원문·backup·pending receipt가 남았는지 확인하고, 오류 파일은 재시도 전에 원인을 분리한다.
