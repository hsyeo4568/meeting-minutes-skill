# Tooling & Graceful Degradation (engine)

> 전제: **대부분의 도구는 부재** 상태로 가정한다. 도구가 없다고 실패하지 말 것 —
> 언제나 `.md` 파일 출력으로 폴백한다. 파이프라인 단계명은 CONTRACT.md 정본을 따른다.

## Tool detection

시작 시 `config.tools`의 각 키(slack_mcp / gmail_mcp / qmd / ontology)는 `auto|on|off`.
- `auto` → 런타임 감지(호출 가능 여부 확인).
- 가용한 산출물만 생성한다. 없는 도구 때문에 파이프라인을 중단하지 않는다.

## Degradation matrix

| 도구 부재 | 동작 (영향 단계) |
|---|---|
| slack_mcp | Canvas/공유 게시 안 함 → Canvas 본문을 `.md` 파일로 출력 + "수동 붙여넣기" 안내 (Share routing) |
| gmail_mcp | Gmail 초안 안 만듦 → 제목+수신/참조+본문을 `.md`(또는 `.eml`)로 출력, 사용자 수동 발송 (Share routing) |
| qmd | embed(인덱싱) 생략, "검색 인덱싱 생략됨" 표기 (Canonical save) |
| ontology | Knowledge-graph update 단계 생략 (phase 7, 선택 add-on) |
| profile=null | 도메인 용어/연락처 교차검증 생략 → placeholder 또는 사용자 확인으로 진행 (Context-link) |

주: 일부 환경은 Gmail/Slack MCP가 향후 배포 예정 → soft-required로 취급. 있으면 쓰고, 없으면 파일 fallback.

## Tool mechanics (가용 시)

- **Slack Canvas**: MCP `create_canvas` / `read_canvas` / `update_canvas`.
  - 사용자 검토용은 DM(`dm_user_id: {{slack_user_id}}`), 채널 게시는 `channel_id: {{slack_channel_id}}`.
  - 흐름: 생성 → URL 공유 → 사용자 수정 → `read_canvas`로 최종본 회수 → Vault canonical save에 반영.
- **Gmail**: 초안(draft)만 생성한다. **자동 발송 금지** — 사용자 검토 후 발송.

## Known failures / fallback

- **Canvas 병렬 update 금지** — `update_canvas`를 여러 `section_id`에 병렬 호출 시 매핑 충돌로 본문 소실.
  - 대규모 수정: `action=replace` + `section_id` 생략 = 전체 full-replace 1회(원자적). 사전 `read_canvas`로 백업.
  - 소규모 수정: 순차 호출.
- **`update_canvas` 실패(`missing_scope`)** → 수정 대신 새 canvas 생성.
- **`canvas_tab_creation_failed`** (대화당 1개 한계) → standalone canvas + `user_ids` 공유 fallback (채널ID 아닌 `user_ids` 필수).
- **`canvas_creation_failed: Unsupported block type (BlockQuote) within block quote`** → 본문 `>>` 중첩 인용 1개도 전체 생성 실패. canvas markdown은 `>` 단일 blockquote만 허용 → 작성 시 `>>`→`>` 치환 후 생성. (에러 메시지에 줄번호 명시됨)
- **Gmail 첨부 미지원** → 본문에 안내 문구 + 사용자에게 파일 직접 첨부 요청.
- **PPTX markitdown 한글 깨짐** → python-pptx 직접 파싱(`sys.stdout.reconfigure(encoding='utf-8')`).
- **Python 한글 출력 깨짐** → `PYTHONUTF8=1` 또는 `sys.stdout.reconfigure(encoding='utf-8')`.
- **린터가 `.md` 변형** (`-`→`*`, `[ ]` 이스케이프) → 원본 형식 유지, `.md` 고수(`.txt` 금지).
- **qmd 미작동/stale** → Glob/Read로 source/Vault 직접 탐색 (최신 회의 인덱스 지연 잦음).
