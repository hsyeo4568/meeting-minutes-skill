#!/usr/bin/env python3
"""Generate the FREE-tier paste-in prompt (PROMPT-ONLY.md) FROM the engine references.
Single source of truth: engine writing-principles + output-templates. Re-run after engine
edits so free + paid versions never drift.

Usage:
  python scripts/build_prompt.py                 # generic (placeholders as 「...」) -> PROMPT-ONLY.md
  python scripts/build_prompt.py --config config.yaml   # fill real values (personal, do NOT commit)
  python scripts/build_prompt.py -o -            # print to stdout
"""
import sys, re, argparse, pathlib
sys.stdout.reconfigure(encoding="utf-8")
ROOT = pathlib.Path(__file__).resolve().parent.parent
ENG = ROOT / "references" / "engine"

# token -> human-fillable bracket (no-config mode). Engine/path/ID tokens collapse to manual notes.
GENERIC = {
    "me": "「내 이름」", "org": "「내 소속」", "project_name": "「프로젝트명」",
    "project_slug": "「슬러그」", "segments": "「세그먼트(예: B2B/B2C)」", "orgs": "「참여 조직들」",
    "language": "ko", "business_style": "korean-gaejosik",
    # automation-only tokens — irrelevant in manual mode
    "vault_path": "(수동 저장)", "work_folder": "(수동)", "vault_meetings_subpath": "(수동)",
    "slack_workspace_id": "(해당없음)", "slack_channel_id": "(해당없음)",
    "slack_user_id": "(해당없음)", "slack_url_base": "(해당없음)",
}

def dig(cfg, *keys):
    """Nested-get: dig(cfg, 'identity', 'me') -> cfg['identity']['me']."""
    for k in keys:
        cfg = cfg[k]
    return cfg

def load_config(path):
    import yaml
    c = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))
    g = lambda *k: dig(c, *k)
    table = {
        "me": g("identity","me"), "org": g("identity","org"),
        "project_name": g("project","name"), "project_slug": g("project","slug"),
        "language": g("locale","language"), "business_style": g("locale","business_style"),
        "segments": "「세그먼트」", "orgs": "「참여 조직들」",  # these live in profile, not config
        **{k: "(자동화 전용)" for k in
           ["vault_path","work_folder","vault_meetings_subpath","slack_workspace_id",
            "slack_channel_id","slack_user_id","slack_url_base"]},
    }
    try:
        headers = dig(c, "locale", "headers") or {}   # optional i18n override map
    except (KeyError, TypeError):
        headers = {}
    return table, headers

def fill(text, table):
    return re.sub(r"\{\{([a-z_]+)\}\}", lambda m: table.get(m.group(1), m.group(0)), text)

def apply_headers(text, headers):
    """config locale.headers i18n override — plain string replace, longest-first."""
    for k in sorted(headers, key=len, reverse=True):
        text = text.replace(k, str(headers[k]))
    return text

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("-o", "--out", default=str(ROOT / "PROMPT-ONLY.md"))
    a = ap.parse_args()
    table, headers = load_config(a.config) if a.config else (GENERIC, {})

    rules = (ENG / "writing-principles.md").read_text(encoding="utf-8")
    templ = (ENG / "output-templates.md").read_text(encoding="utf-8")
    # Free-tier makes ONE share MD (no tools) — drop automation-only surfaces
    # (canvas/gmail/vault). Keeps share_md + detail_md; the rest is Claude Code-only.
    _cut = templ.find("\n## canvas")
    if _cut != -1:
        templ = templ[:_cut].rstrip() + (
            "\n\n> canvas·gmail·vault 산출은 **Claude Code 전용** — 무료판은 위 공유 MD 1종만 생성.\n")

    out = f"""# 회의록 작성 프롬프트 (무료판 — 어떤 Claude 채팅에도 붙여넣기)

> 사용법: 이 파일 전체를 복사 → Claude(무료 포함)에 붙여넣기 → 맨 아래 「입력」에
> 회의 녹취/노트를 넣고 전송 → 회의록을 받아 수동 복사. 파일·도구·설정 불필요.
> ⚠️ 전송 전 3가지: ① `「내 이름」`·`「내 소속」`을 본인 값으로 치환 ② 이전 회의록이
> 있으면 「입력」에 함께 붙여넣기(연계 맥락용 — 없으면 생략) ③ 녹취를 「입력」 아래에.
> 자동화(직전 회의 연계·식별자 xlsx 교차검증·자동 공유)는 유료 Claude Code 스킬에서만.

**무료판 실행 규칙 (Claude에게):** 여기는 파일·도구가 없는 웹 채팅이다. 아래 규칙 중
파일 읽기(직전 회의록 Read)·시트 대조·canvas/gmail/vault 산출은 **Claude Code 전용** —
붙여넣어진 자료가 있으면 그것만 쓰고, 없으면 생략하되 불확실 식별자는 본문에
`(확인필요)` 표시. **산출물은 공유용 마크다운 회의록 1종만** 생성한다.

당신은 회의록 작성 전문가다. **먼저 「입력」 녹취를 보고 이 회의의 유형과 알맞은 섹션 구조를
한 줄로 제안**하라 ("이 회의는 X로 보여 섹션을 A→B→C로 잡겠습니다 — 조정할까요?"). 사용자가
확인/수정하면 그 구조로 작성한다. 섹션 B는 **하나의 예시**일 뿐 — 회의 성격에 안 맞으면 따르지 말 것.
작성 규칙(섹션 A)은 회의 종류와 무관하게 적용한다.

본인=`{table.get('me')}` / 소속=`{table.get('org')}` / 문체=`{table.get('business_style')}`.
(값이 「...」면 사용자가 직접 치환할 자리.)

---

## A. 작성 규칙

{fill(rules, table)}

---

## B. 출력 구조 (예시 — 회의 성격에 맞게 조정 가능)

{fill(templ, table)}

---

## 입력 (회의 녹취 / 노트)

[여기에 회의 녹취나 노트를 붙여넣으세요. 위 규칙/구조대로 회의록을 작성하라.]
"""
    if headers:
        out = apply_headers(out, headers)
    if a.out == "-":
        sys.stdout.write(out)
    else:
        pathlib.Path(a.out).write_text(out, encoding="utf-8")
        print(f"wrote {a.out}  ({len(out)} chars)")

if __name__ == "__main__":
    main()
