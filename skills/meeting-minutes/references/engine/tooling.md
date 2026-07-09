# Tooling & Graceful Degradation (engine)

> Premise: **most tools are assumed absent** by default. Do not fail because a tool is missing —
> always fall back to `.md` file output. Pipeline stage names follow the CONTRACT.md canonical spec.

## Tool detection

At startup, each key in `config.tools` (slack_mcp / gmail_mcp / qmd / ontology) is `auto|on|off`.
- `auto` → runtime detection (check whether the tool is callable).
- Only generate outputs for available tools. Do not abort the pipeline because a tool is missing.

## Degradation matrix

| Missing tool | Behavior (affected stage) |
|---|---|
| slack_mcp | Skip Canvas/shared posting → output Canvas body as `.md` file + "manual paste" instructions (Share routing) |
| gmail_mcp | Skip Gmail draft creation → output subject + to/cc + body as `.md` (or `.eml`), user sends manually (Share routing) |
| qmd | Skip embed (indexing), note "search indexing skipped" (Canonical save) |
| ontology | Skip knowledge-graph update stage (phase 7, optional add-on) |
| profile=null | Skip domain term/contact cross-validation → proceed with placeholder or user confirmation (Context-link) |

Note: some environments have Gmail/Slack MCP planned for future deployment → treat as soft-required. Use if present, fall back to file if not.

## Tool mechanics (when available)

- **Slack Canvas**: MCP `create_canvas` / `read_canvas` / `update_canvas`.
  - For user review: DM (`dm_user_id: {{slack_user_id}}`); for channel posting: `channel_id: {{slack_channel_id}}`.
  - Flow: create → share URL → user edits → retrieve final version with `read_canvas` → apply to Vault canonical save.
- **Gmail**: Create draft only. **Auto-send is prohibited** — user reviews and sends.

## Known failures / fallback

- **Canvas parallel update prohibited** — calling `update_canvas` on multiple `section_id`s in parallel causes mapping conflicts and body loss.
  - Large edits: use `action=replace` + omit `section_id` = single atomic full-replace. Back up with `read_canvas` beforehand.
  - Small edits: call sequentially.
- **`update_canvas` failure (`missing_scope`)** → create a new canvas instead of editing. **Required follow-up**: immediately update the canonical frontmatter canvas id + notify user the old canvas is stale (no delete tool → instruct user to delete manually). Silent replacement is prohibited — channel members will keep seeing the old canvas.
- **`canvas_tab_creation_failed`** (1 canvas per conversation limit) → fallback: standalone canvas + share via `user_ids` (must use `user_ids`, not channel ID).
- **`canvas_creation_failed: Unsupported block type (BlockQuote) within block quote`** → even a single `>>` nested blockquote in the body causes total creation failure. Canvas markdown allows only single `>` blockquotes → replace all `>>`→`>` before creation. (The error message includes the line number.)
- **Gmail attachment unsupported** → include instructions in the body + ask user to attach the file manually.
- **PPTX markitdown Korean garble** → parse directly with python-pptx (`sys.stdout.reconfigure(encoding='utf-8')`).
- **Python Korean output garble** → use `PYTHONUTF8=1` or `sys.stdout.reconfigure(encoding='utf-8')`.
- **Linter mutates `.md`** (`-`→`*`, `[ ]` escaping) → preserve original format, keep `.md` (`.txt` prohibited).
- **qmd not working / stale** → explore source/Vault directly with Glob/Read (recent meeting index lag is common).
