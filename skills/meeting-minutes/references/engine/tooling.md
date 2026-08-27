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
| materials handler (configured but not installed) | Fall to the next entry in that ext's chain; if the chain is exhausted, extract with the built-in structured library (Materials comprehension floor). Never drop the material — say which handler ran in the closing summary |
| no handler for an ext | Read the file directly if it is text-like; otherwise list it as `skipped_unsupported` in the closing summary (surfaced, never silent) |
| `materials.deep_read: off` / user declines | Deterministic extract only; flag in the digest which units carry layout-borne meaning that was not read (e.g. "slide 7 도식 미판독") |

Note: Gmail/Slack MCP are soft-required — if present, use them; if absent, fall back to file output (mechanism above). Availability varies by environment; never treat their absence as a failure.

## Tool mechanics (when available)

- **Slack Canvas**: MCP `create_canvas` / `read_canvas` / `update_canvas`.
  - **Current `create_canvas` is title+content only.** `dm_user_id` is gone. Do not rediscover the schema each run. Pass `content` from a disk file (`Path.read_text`) — never retype Korean into the tool JSON.
  - **Owner = the user, not the bot.** Dest share-check (`destination` = user, not bot DM, not empty, not `user_ids`-only) Exit 8 **before** `create_canvas`. After create, the user (`config.channels.slack_user_id`) MUST be able to open the URL. Permission denied after a successful create is not a recrate — stop and say so.
  - **Never use `{{slack_bot_dm_id}}` as the destination.** That conversation is the Slack app's DM; canvases created there are invisible to the user.
  - **`user_ids` is record-only** (share-check / `mm_run record --user-ids {{slack_user_id}}`). It is not a create_canvas argument.
  - Do NOT create with `channel_id` unless the user explicitly asks to auto-post: `channel_id` mode auto-posts a bot link message that a regular member cannot delete.
  - Flow: dest share-check 0 → write canvas `.md` → snapshot Path `create_canvas` **once** (title+content; dest unbound; Path.read_text still wraps tool JSON; do not patch canvas.ts) → post-create `canvas_id` only → **then URL** → **then vault**. Ban recrate after approve. **Canvas is a DERIVED artifact — never auto-back-sync canvas edits into the vault canonical.**
- **Gmail**: Create draft only. **Auto-send is prohibited** — user reviews and sends.
  - **Confirm the draft landed.** After create, read the draft back by id (or list drafts and match). No draft id = not created → write subject/to/cc/body as `.eml` in the work folder and say the MCP did not land. Never report "임시보관함에 넣었다" without an id.
  - If `gmail_mcp` is not callable, skip the API and write the `.eml` immediately.
  - **Harness (required at share time):** dump destination + ids to JSON and run `python scripts/mm_run.py share-check --plan share-plan.json --config config.yaml` (same as `python scripts/share_guard.py --plan share-plan.json --config config.yaml`). Exit 8 codes: `canvas.bot_dm`, `canvas.missing_dest`, `canvas.missing_user_share`, `gmail.unconfirmed_inbox_claim`. Empty dest + `user_ids` stuffed is `missing_dest` (not a pass). `mm_run record --artifact canvas --dest … --user-ids {{slack_user_id}}` also refuses `--dest {{slack_bot_dm_id}}` when config has Slack ids.
  - **Reading a prior thread to mirror the last sent mail** (recipients/format): fetch cheap-first. Use `search_threads` snippets to pick the message, then the lightest `messageFormat` (`METADATA_ONLY`/`MINIMAL`) and `messages[-1]` only. Do not open with `FULL_CONTENT` unless you need that one historical body.

## Known failures / fallback

- **Canvas parallel update prohibited** — calling `update_canvas` on multiple `section_id`s in parallel causes mapping conflicts and body loss.
  - Large edits: use `action=replace` + omit `section_id` = single atomic full-replace. Back up with `read_canvas` beforehand.
  - Small edits: call sequentially.
- **`update_canvas` failure (`missing_scope`)** → do **not** create a new canvas after approve. Stop, keep the existing id, tell the user. Silent replacement is prohibited.
- **`canvas_tab_creation_failed`** (1 canvas per conversation limit) → fallback: file `.md` + "manual paste". Do not Recreate. `user_ids` is record-only, not a second create.
- **Canvas exists but user cannot view (permission / 권한 없음)** → dest was bot DM or dest-check was skipped. Do **not** Recreate. Exit 8 / stop. Dest-check before create exists so this never happens after approve.
- **`canvas_creation_failed: Unsupported block type (BlockQuote) within block quote`** → even a single `>>` nested blockquote in the body causes total creation failure. Canvas markdown allows only single `>` blockquotes → replace all `>>`→`>` before creation. (The error message includes the line number.)
- **Gmail attachment unsupported** → include instructions in the body + ask user to attach the file manually.
- **PPTX markitdown Korean garble** → parse directly with python-pptx (`sys.stdout.reconfigure(encoding='utf-8')`).
- **Python Korean output garble** → use `PYTHONUTF8=1` or `sys.stdout.reconfigure(encoding='utf-8')`.
- **Linter mutates `.md`** (`-`→`*`, `[ ]` escaping) → preserve original format, keep `.md` (`.txt` prohibited).
- **qmd not working / stale** → explore source/Vault directly with Glob/Read (recent meeting index lag is common).
