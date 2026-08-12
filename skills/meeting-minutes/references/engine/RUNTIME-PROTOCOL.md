# Runtime protocol — the publish gate as commands, not prose

The MD-first approval rules used to be three paragraphs the agent had to recall correctly on
every run. They are now enforced by `scripts/mm_run.py`: **`gate` is the only source of an
artifact body, and only `verify` can call an artifact done.** Exit codes are the enforcement
surface — a non-zero exit is a stop, not a warning.

Degraded mode (no Python / no PyYAML) is at the bottom: the prose gate still applies, and a
missing runner is never a reason to fail the run.

## Invariants

| # | Invariant | Enforced by |
|---|---|---|
| I1 | The work MD is the only canonical input; every other output is a derivative. | `gate` emits a body path only from the approved snapshot |
| I2 | Run state lives beside the work MD, never in the canonical store. | state dir `{{work_folder}}/<meeting>/.mm/`; the runner has zero canonical-store write paths, and `approve` **refuses** (exit 2) a `--doc` under `paths.vault` |
| I3 | No external artifact without a hash check in the same step. | `gate` opens a single-use token; `record` re-checks the hash before accepting |
| I4 | "Created" is not "done". | `record` cannot reach verified; only `verify` (read-back) can |
| I5 | A retry prefers read-back over create. | `gate` returns `action: readback` once an id exists |
| I6 | A source edit invalidates every derivative of the old hash. | run → `superseded`, artifacts → `stale`, blocking manual items minted |
| I7 | Two agents cannot publish the same doc at once. | lease + compare-and-swap on the doc index |
| I8 | Every failure is logged; only qualifying failures reach the canonical store. | `runs.jsonl` always; `promote-check` gates promotion |

Fail-closed: any state the runner cannot prove is **not done**, and the resolution is
"stop and ask", never "create it again".

## Command sequence (mandatory order)

Run from the skill root. `--config config.yaml` is needed only by `approve` (it freezes the
category plan into the manifest; a later config edit cannot retarget an in-flight run).

```
mm_run approve --doc <work_md> --config config.yaml --category <cat> [--preapproved]
      -> {doc_id, run_id, lease, plan}          # snapshot taken here; keep the lease

  for each artifact in plan:
    mm_run gate   --doc <work_md> --lease <L> --artifact <A>
      -> {action, snapshot_path, idem_key, external_id}
         action=create   -> build the body ONLY from snapshot_path,
                            append the footer line  > mm:<idem_key>
         action=readback -> do NOT create a second one; read the existing artifact
    mm_run record --doc <work_md> --lease <L> --artifact <A> --id <external-id> \
                  --body-file <exact body sent> [--url <permalink>]
    mm_run verify --doc <work_md> --lease <L> --artifact <A> \
                  --readback-file <exact bytes read back from the tool>
      -- or, only when that channel cannot put its response on disk --
    mm_run verify --doc <work_md> --lease <L> --artifact <A> \
                  --readback-unavailable "<why>"   # holds it open, never verifies

mm_run close  --doc <work_md> --lease <L>
```

Out-of-band commands:

| Command | Use |
|---|---|
| `status --doc P` | read-only; no lease needed. Run it first on any resume — it prints the next allowed action. A work MD with no frontmatter carries no `mm_*` mirror (it is shared verbatim), so lookup falls back to the path; `status` reports `orphan_runs` when a registered doc has vanished from disk, which is what a rename looks like |
| `fail --doc P --artifact A --class <transient\|contract\|external\|user> --key <slug> --detail "…"` | log a failure. **No lease required** — it must work when the lease is lost |
| `manual --doc P --lease L --add "…" \| --done <id> \| --waive <id> --reason "…"` | blocking human checklist (orphan cleanup after a supersede) |
| `abort --doc P --lease L --reason "…"` | user cancelled |
| `promote-check --doc P` | decides whether a failure deserves a knowledge note; prints a ready-to-paste stub |
| `gc [--days N] [--dry-run]` | prune payloads of terminal runs |

## Exit codes

| Code | Meaning | Correct response |
|---|---|---|
| 0 | ok | continue |
| 2 | usage / config | fix the invocation; do not improvise around it |
| 3 | **source hash mismatch** | BLOCKING. The work MD changed after approval. Show the printed diff, get re-approval (`approve` again), and re-derive artifacts already built from the stale content |
| 4 | read-back mismatch | the artifact is not synced. Report what differs; do not create a second one |
| 5 | lock held by another owner | another session is publishing this doc. Stop; `status` still works. **Exception — the lease may be your own**: a source edit mid-run forces a re-`approve`, and the still-live run from the same session holds the lock. Check `status`; if the holder is this session's run and nothing was published yet, `abort --lease <yours>` first, then `approve`. Do not wait out the TTL and do not touch the doc index by hand |
| 6 | illegal transition | the step is out of order (e.g. `record` without a `gate`) |
| 7 | completeness check failed | `close` found unverified artifacts or open blocking manual items |

## Rules for the agent

1. **Never publish text you did not read from `gate`'s `snapshot_path`.** Not the draft in your
   context, not the file you re-read yourself. The snapshot is immutable; your context is not.
2. **Created is not done.** Report an artifact as complete only after `verify` returns 0.
   **`--readback-file` must hold the bytes the tool gave back** — fetch the artifact (`list_drafts`,
   `read_canvas`, re-read the file) and feed *that*. Deriving the read-back from the body you sent
   makes `verify` compare the sent text with a copy of itself: it passes every time and proves
   nothing. Measured 2026-07-29 — two gmail `verify`s passed on a reconstruction of the sent body,
   so the gate gave no delivery assurance at all. If a channel's response cannot be written to disk
   mechanically, **run `verify --readback-unavailable "<why>"`** — the artifact stops at
   `manual_required`, a blocking manual item is opened, and `close` stays shut until a human
   confirms it by eye; a later genuine read-back still clears it. Say so in the closing summary too.
   A named gap beats a green light that means nothing. **Mail-draft channels are the usual case:** if the draft API returns the body only as an inline tool response with no on-disk artifact, that is not a mechanical read-back — reading it and then re-emitting the sent bytes proves nothing. Inspect the response, then run `verify --readback-unavailable` and let a human confirm. (Prose alone lost twice — gmail 2026-07-29,
   canvas 2026-08-07 — which is why the escape hatch is now a command, not an instruction.)
3. **Never retry by re-creating.** After any tool error, log it with `fail`, then run `gate`
   again — it returns `action: readback` when an id was already recorded.
4. **A blocking exit is a stop.** Do not run later phases (canonical save, index, topic sync,
   knowledge graph) on top of a blocked state.
5. **The runner never writes to the canonical store.** `promote-check` hands you a stub; you or
   the user decide whether it becomes a note.

## Hash domain (the part that breaks silently if ignored)

`source_sha256 = sha256(canon(strip_mm_keys(text)))`

- `canon` strips the BOM, normalises CRLF/CR to LF and trailing blank lines, so an editor
  rewriting line endings is not mistaken for a content edit.
- `strip_mm_keys` removes top-level frontmatter keys matching `mm_*` (a reserved namespace)
  line-by-line — never by re-serialising YAML, which would reorder and requote the user's own
  frontmatter. This is what lets the runner refresh its human-readable mirror in the work MD
  without invalidating its own approval.
- Read-back is compared against what was **sent** (`rendered_sha256`), not against the source —
  the idempotency footer means the published body legitimately differs from the source.

## Read-back modes

A byte hash proves delivery only on channels that store what they are given. Measured against a
live canvas: `-` bullets come back as `*`, dates come back wrapped in an embed, and blank lines
appear between blocks. Byte comparison there fails on every run, and a gate that always fails
gets switched off — worse than no gate. So `config.channels.<ch>.readback` declares the
comparison:

| Mode | Rule | Use for |
|---|---|---|
| `exact` (default) | byte-faithful after `canon()` | files, the canonical store — anything we write ourselves |
| `semantic` | every **sent line must be present** in the read-back once both sides are stripped of the renderer's own formatting (list markers, checkboxes, heading marks, emphasis, `![](type:value)` embeds) and the read-back is flattened to one line | canvas, mail bodies |

Flattening matters: a mail body comes back hard-wrapped near 78 columns, so a sent line arrives
split in two. Line-to-line comparison would call every mail a loss. Each match is consumed from
the flattened text, so losing one of two identical items is still reported.

`semantic` still catches what read-back exists to catch — truncation, a dropped section, an empty
body, the wrong document — and reports the missing lines. It does not flag reformatting, which on
those channels is not a defect. Duplicate lines count with multiplicity, so losing one of two
identical items is still a loss.

The mode is **frozen into the manifest at approve time**, alongside the plan: `verify` takes
`--config` optionally, and a config-less invocation must not silently downgrade a rendering
channel back to byte comparison.

## Supersede semantics

When any command sees `current != approved`:

1. run → `superseded`, every non-terminal artifact → `stale`;
2. for each already-published artifact on a **non-editable** channel
   (`config.channels.<ch>.editable: false`), a blocking manual item is minted:
   *supersede `<type> <old-id>` → `<new link>`*;
3. the next `approve` records `supersedes` / `superseded_by` on both runs;
4. `close` stays blocked (exit 7) until those items are `--done` or `--waive`d with a reason.

Editable channels (mail drafts, files) are updated in place — same id, no orphan. That
asymmetry is config-declared, never hardcoded.

## Where failures are recorded

| Layer | What | Where |
|---|---|---|
| run state | hash, lease, artifact ids, manual items | `.mm/runs/<run>/manifest.json` |
| every failure event | tool error, fallback, retry, mismatch, lock denial | `.mm/runs.jsonl` (append-only) |
| operational incident | wrong external share, data loss, manual recovery | canonical store incident note |
| recurrence-proof knowledge | an invariant or a new gate is needed | skill workflow note |

`promote-check` returns `promote: true` only for: an event with real impact
(external share error, data loss, manual recovery); the same `root_cause_key` in **two or more
runs**; a `contract`-class failure (only a skill/config change prevents it); or a waived manual
item (the next operator must know the recovery). Everything else stays in the JSONL — writing
every failure to the canonical store poisons its search index and turns one-off exceptions into
apparent standard procedure.

A failure logged **without** `impact` and `root_cause_key` matches no rule, so `promote-check`
reports it under `needs_triage` instead of scoring it `promote: false` in silence. Classify those
events (or accept them as noise) before trusting the verdict — an unclassified real incident that
scores "no promotion needed" is exactly the fail-open this policy exists to prevent.

## Degraded mode (runner unavailable)

If Python or PyYAML is missing, do **not** fail the run — fall back to the prose gate and say so
in the closing summary:

1. draft the MD into the work folder only → user review and direct edits → explicit approval;
2. on approval, re-read the draft from disk and record its sha256 as `approved_hash` (the
   approved snapshot). Derive every artifact from that content — never from the draft in context;
3. before each artifact, re-check the current sha256 against `approved_hash`. Mismatch is
   BLOCKING: show the diff, get re-approval, and re-derive anything already built;
4. track progress in the work MD frontmatter (`mm_state: drafted → approved:<hash8> →
   canonical_saved → canvas_created:<id> → gmail_drafted:<id> → synced`), recording external
   ids as they are created, so an interrupted run verifies instead of re-creating;
5. non-editable channels are created **exactly once** — re-sharing means a new artifact plus a
   manual pointer update, so it needs the user's decision, not a silent retry.

An explicit pre-approval in the request ("just do it, no approval needed") collapses the gate
into that turn — that message *is* the approval step — but the snapshot and hash checks still
happen. Mail stays draft-only regardless; auto-send is prohibited.

## Adding an optional artifact mid-run

`plan` is frozen at `approve`. Gating an artifact outside it fails with exit 2
(`'gmail' is not in this run's frozen plan`), and the fix is **not** to re-`approve` on top of the
live run: a non-terminal prior run gets `supersede()`d, which marks the already-verified
non-editable artifacts `stale` and mints blocking manual items for them — you end up owing an
orphan-cleanup for a canvas that was never actually wrong.

Correct sequence: `close` the current run (it is complete), then `approve --include-optional`,
which sees a terminal prior and only records `supersedes` without staling anything. In the new run
the already-published artifacts gate as `create`; do **not** re-create them — `record --id <existing
id>` with the same body file and `verify` with the same read-back. `idem_key` is derived from
content, so it is identical across runs and the footer already in the published artifact still
matches. Measured 2026-07-29 adding `gmail` to a completed `vault`+`canvas` run.
