# AGENT_CONTEXT

Entry point for AI agents working in this repository.

- **What this is:** `multi-agent-dispatch`, a Claude Code skill and Python runner that dispatches tasks to Codex, Claude and OpenCode workers (see `README.md`).
- **Current Truth:** code and tests in this repository; `VERSION` is the release number. Nothing is mirrored elsewhere.
- **If documents disagree:** `dispatch.py` behavior and `test_dispatch.py` win over `SKILL.md`, which wins over `README.md` and `references/`.
- **Remote vs local:** the `main` branch on GitHub is the shared state. Local worktrees and unpushed commits are not.
- **Planning-only agents:** may read and propose; do not edit, push or open PRs.
- **Making a change:** branch from `origin/main`, run `python -m unittest test_dispatch`, open a PR. Never add support for driving Antigravity CLI (`agy`): its terms forbid it.
