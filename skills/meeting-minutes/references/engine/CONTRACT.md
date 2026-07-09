# Engine Contract (the interface every engine/*.md obeys)

> Engine = generic meeting-minutes methodology. **ZERO proper nouns.** No org names, no
> personal names, no project codes, no paths, no Slack IDs, no workspace URLs. Examples use
> placeholders or neutral fakes (`Org A`, `vehicle X`). All specifics live in config.yaml + profiles/.

## Purity rule (gate #1 — scripted in ../../verify.sh)

`references/engine/` must contain 0 hits for: real org/person/project tokens, absolute paths
(`C:/Users/...`), Slack workspace/channel/user IDs (`T…`,`C…`,`U…`,`D…`), workspace hostnames
(`*.slack.com` with a real subdomain), VINs, plate numbers. If you need a concrete example,
write `{{placeholder}}` or a neutral fake.

## Placeholder vocabulary (gate #3 — every token used MUST exist in config.example.yaml)

| Token | Source key | Meaning |
|---|---|---|
| `{{me}}` | identity.me | the "I" speaker label |
| `{{org}}` | identity.org | my org short name |
| `{{project_name}}` | project.name | display name |
| `{{project_slug}}` | project.slug | filename/path slug |
| `{{vault_path}}` | paths.vault | vault root (abs) |
| `{{work_folder}}` | paths.work_folder | raw source dir (abs) |
| `{{vault_meetings_subpath}}` | paths.vault_meetings_subpath | meetings subdir |
| `{{slack_workspace_id}}` | channels.slack_workspace_id | T-id |
| `{{slack_channel_id}}` | channels.slack_channel_id | C-id |
| `{{slack_user_id}}` | channels.slack_user_id | U-id (DM review target) |
| `{{slack_url_base}}` | channels.slack_url_base | workspace URL |
| `{{language}}` | locale.language | output language |
| `{{business_style}}` | locale.business_style | prose style id |

Profile-supplied (engine references them but does NOT hardcode values; profile fills):
`{{segments}}` (e.g. B2B/B2C), `{{orgs}}` (participating orgs), domain glossary, contacts.

## Canonical pipeline phases (tooling.md + pipeline.md MUST use these exact names)

1. Preprocess — text/PDF/audio(Whisper); read attached slides first (python-pptx).
2. Speaker ID + clean — map speakers, strip fillers. `{{me}}` is the "I".
3. Context-link + draft body — read prior 1-2 weeks of minutes, link each agenda to its source meeting, cross-check identifiers vs source-of-truth sheet.
4. Per-category deliverables — apply `categories` matrix (output-templates.md).
5. Share routing — per category: share_md / canvas / gmail. Missing tool -> file fallback.
6. Canonical save — write the authoritative copy to the configured store (config.paths.vault — a notes vault / docs folder / wiki; org-dependent) with config.vault_frontmatter. Optional: index (qmd) if available.
6.5. Topic sync — optional; only if config.paths.topics_moc is set: append meeting evidence lines to matching topic notes (append-only). Skip entirely if the key is absent.
7. Knowledge-graph update — record decisions/relations if tools.ontology available; else skip entirely (optional add-on, not required for a valid run).

## Degradation principle (gate #2 — checklist, read-through of SKILL.md)

Every tool branch has a no-tool fallback that emits a `.md` file + manual-step note, and NEVER
errors out. profile=null -> skip domain/contact cross-checks, proceed with placeholders.

| tool absent | behavior |
|---|---|
| slack_mcp | don't post; write canvas body to `.md` + "paste manually" note |
| gmail_mcp | don't draft; write subject+to/cc+body to `.md` (or `.eml`) for manual send |
| qmd | skip embed; print "indexing skipped" |
| ontology | skip phase 7 |
| profile=null | skip cross-checks; use placeholders / ask user |
