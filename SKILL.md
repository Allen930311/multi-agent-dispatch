---
name: multi-agent-dispatch
description: Coordinate multi-agent work in any repo - the Owner may name who does what. dispatch.py ask sends one worker to read or write text with no branch or review; dispatch.py run does author, review and draft PR with any named author and reviewer among OpenCode free models, Codex and headless Claude Haiku/Sonnet. Use when the user says "dispatch", names a worker for a job (e.g. "Haiku writes, Codex reviews"), or asks to run several tasks in parallel.
---

# Multi-agent dispatch

Version 4.6.0 (2026-11-10). The same number is in `VERSION` and `dispatch.py --version`; every copy of this skill must match it.

**Antigravity CLI (`agy`) is not supported.** Its terms (section 6) treat third-party tools driving the service as a breach, and users have been banned for it. dispatch.py refuses `agy` everywhere; do not add it.

## Decide first

Total cost is dispatch + execution + checking + redo; a cheap worker that needs redoing is not cheap. Take the first step that fits:

1. Cheaper to do it yourself than to write the brief and check the answer: do it. No dispatch.
2. Only needs an answer or text: `ask`. No branch, commit, review or PR. For a simple read, Claude may use a native Haiku sub-agent instead.
3. Changes a repository: `run`. Only dispatch.py commits and pushes.

**Who.** Roles are not tied to workers. When the Owner names a worker, reviewer or model, use exactly that: no substitution or fallback; report a failure instead. Otherwise you choose from the table, may switch after a failure, and report who did it and why. There is no `auto` flag: decide, then pass explicit names.

**Models.** Each pool has one default and dispatch.py applies it; never pick another model on your own. Codex is always the newest `*-luna`. Claude pools are haiku / sonnet, OpenCode stays on its approved `-free` list. Only when the Owner names a model, pass `--model <pool>=<model>` (`run`, repeatable, every role of that pool) or `--model <model>` (`ask`). A named Codex model that `codex debug models` does not list ends as ENVIRONMENT_ERROR. Codex effort is medium; max only via `--final-max` for security- or data-related changes. Codex stage timeouts scale with effort: 900 s for medium/high, 1200 s for xhigh, and 1800 s for max.

**Review in auto mode.** Logic, data and security changes always get an independent reviewer. Other code may skip review only when the acceptance command really exercises it, the risk is low and the author is not a free model. Free-model output is always checked by something stronger. `ask` text you will rely on is checked by you against its source. When the Owner says no review, use `--reviewer none` and say it is unreviewed.

| Worker | Good for | Limits seen in real runs (2026-11-05) |
|---|---|---|
| `opencode` | Quick free digests and copy | 6-29s. Weakest, always checked. Cannot review. Launch several at least 30s apart |
| `claude-haiku` | Fast simple reads, small scoped edits | 4-10s. Claude quota. File tools only |
| `claude-sonnet` | Review when Codex is out, harder writing | Reviews from the diff only |
| `codex` | Logic, data, security; default reviewer | 11-24s for an answer, stdin up to 400000 chars. Limited quota |

## Ask

```powershell
python ~/.claude/skills/multi-agent-dispatch/dispatch.py ask <task-id> --pool <pool> --prompt <file> [--read <file-or-folder>]... [--model <model>]
```

The answer is in `<out>/<task-id>/result.md`; the one-line JSON gives the path. Workers see a copy or embedded UTF-8 text, never the repository. Secret-like content, sensitive names and links are refused (so a file that itself contains secret-detection patterns must be excerpted). Split a job refused as too large. A failed id can be retried; a PASS is never overwritten.

## Run

```powershell
python ~/.claude/skills/multi-agent-dispatch/dispatch.py run <task-id> --wt auto --prompt <file> --lane low|high --accept "<command>" --allowed <path> --title "<PR title>"
```

Confirm task, allowed paths, acceptance command and authorization with the Owner once. `low`: docs, tests, small mechanical changes, default authors OpenCode → Codex. `high`: logic, data, security, Codex only. `--wt auto` takes the first free `claude-work-1|2` slot of the repository in the current directory (or of `--repo <checkout path or folder name>`) and reports it as `slot` in the result line; a slot can still be named explicitly as `--wt <root>/<repo>/<agent>-work-1|2`; the slot name does not pick the author; a slot is locked for the whole run, so two runs never share one, and when no slot is free the run ends with "environment unavailable: no free slot" and the reason per slot. A task id that was already used gets `-2` … `-9` appended automatically; always read `task_id` from the result line. The runner registers the task, so don't pre-register it.

| Flag | Use |
|---|---|
| `--author <pool>` (repeat for order) | Only these authors run |
| `--reviewer <pool>` | `codex`, `claude-haiku`, `claude-sonnet` or `none` (state `PASS_UNREVIEWED` in summary.json; never merge it as reviewed). Its failure is BLOCKED. OpenCode cannot review |
| `--model <pool>=<model>` | Owner-named model only, see **Models** |
| `--may-touch <path>` | Adjacent files the change may need (tests, ledger, interface); listed as `scope_expanded` |
| `--seed-patch <patch>` | Resume from kept work; no author runs, still scope/secret/review checked |
| `--body-file`, `--trailer-file`, `--pr-trailer-file` | Optional; the PR body defaults to the task id plus the first 3000 characters of the prompt, and the commit / PR attribution lines default to `trailer` / `pr_trailer` of the `"*"` entry (or the repository's entry) in `repos.json` |
| `--prescreen` | Advisory free pre-screen (OpenCode). Off by default: its findings feed no decision |
| `--final-max` | Codex reviewer at max effort for the last round |
| `--base`, `--no-pr`, `--no-trailer` | Other base; repo without GitHub; deliberately no attribution |

`repos.json` per repository can refuse free pools (`no_free_pools`) or deny paths to free pools (`free_pool_deny`, now applied to OpenCode); never put unpublished data in `--allowed` on the low lane. The `"*"` entry holds defaults for every repository and a repository's own entry overrides it. Workers never get Git or GitHub credentials. The result is a draft PR, never marked ready or merged by the runner.

**When it does not PASS.** A failed acceptance command is handed back to the author up to twice before review (with the output tail); `accept_log` in summary.json points to the failing log; a failed temp-folder cleanup is reported as `cleanup_failed` and no longer changes the result. `NEEDS_SCOPE_DECISION`: you decide, not the Owner; rerun with `--may-touch` and `--seed-patch`, or drop the extra files. `ENVIRONMENT_ERROR`: fix the machine, rerun with `--seed-patch <recover_patch>`. Kept patches (`partial_*`, `recover_patch`) are always the full change from the run's base. Review round 1 is a full review; later rounds only verify the earlier findings and the fix, and a new finding blocks only with a concrete failing scenario. When a round does not have fewer blocking findings than the round before, the run stops as BLOCKED with "review findings are not converging" instead of using all three rounds: rerun with a sharper prompt or a stronger author rather than repeating. Details in [review.md](references/review.md).

## Finish

Run the runner with `run_in_background` and keep the session open; its exit is the only wake-up, so don't Monitor, poll or call pools.py around it. After a resumed session check `pools.py status`. Read the one-line result; open `summary.json` only when it is not PASS, and check `scope_expanded` before merge. Reproduce every finding before accepting a fix. Missing evidence is BLOCKED or ENVIRONMENT_ERROR, never PASS. On any non-PASS and before merge read [review.md](references/review.md); before worktree cleanup read [worktrees.md](references/worktrees.md). Routing internals, quota and egress rules: [policy.md](references/policy.md); manual fallback: [tasks.md](references/tasks.md).
