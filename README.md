# multi-agent-dispatch

A Claude Code skill (plus a Python runner) that coordinates several coding agents on one repository: it hands a task to an author (Codex, headless Claude Haiku/Sonnet, or a free OpenCode model), runs your acceptance command, gets an independent read-only review, and opens a **draft** PR. It never marks a PR ready and never merges.

- `dispatch.py ask` — one worker reads or writes text; no branch, review or PR.
- `dispatch.py run` — author → acceptance → review → draft PR, in an isolated worktree.
- `pools.py` — pool status and cooldown tracking (writes a local `pools.json`).
- `SKILL.md` — the instructions Claude Code loads; copy this folder to `~/.claude/skills/multi-agent-dispatch/`.

## Safety model
- Workers never receive Git or GitHub credentials; only the runner commits and pushes its own task branch.
- Free (OpenCode) workers get only an isolated copy of the files in `--allowed`, never the repository. A secret-pattern or policy match blocks that attempt.
- `repos.json` per repository: `no_free_pools`, `free_pool_deny` paths, commit/PR trailers.
- Antigravity CLI (`agy`) is deliberately refused: its terms forbid third-party tools driving the service.

## Requirements
Python 3.10+, `git`, and whichever of `codex`, `claude`, `opencode`, `gh` you want to dispatch to.

## Configuration (environment variables)
`DISPATCH_WORKTREES_ROOT` (default `~/worktrees`), `DISPATCH_TMP_ROOT` (default `~/worktrees/_tmp`), `DISPATCH_REPOS_FILE`, `DISPATCH_CODEX`.

## Tests
```
python -m unittest test_dispatch -v
```

## Status
Extracted from a personal setup; the docs under `references/` still read as maintainer notes. Issues and PRs welcome. MIT licensed.
