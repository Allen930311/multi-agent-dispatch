# Manual task contract and pool notes

For manual fallback, define the goal, base SHA, allowed paths, forbidden actions, provider/data scope, acceptance command and required report. Work only in the worktree. Do not commit, push, merge or delete. Keep UTF-8 and use short temporary paths on Windows. Report changed files, tests, exact commands, counts and not-verified items.

For manual OpenCode fallback, use the `free-worker` agent in a new isolated directory containing only allowed file copies and the prompt; do not give it the repo or `.git`. Keep worker output in files. Do not launch two OpenCode jobs within 30 seconds; watch its log for `Free usage limit reached` and kill the process tree immediately.

Routing when the Owner names nobody: low lane authors OpenCode -> Codex; high lane uses Codex directly. A named `--author` or `--reviewer` replaces this. Free pools may provide a one-turn read-only pre-screen. The runner performs the acceptance command and fresh Codex review loop. Codex effort is medium; max is reserved for the final review of security- or data-related changes. agy is disabled; use the manual hand-off in agy.md. See [policy.md](policy.md), [agy.md](agy.md) and [review.md](review.md).

Prompts do not enforce permissions. Scan for reparse points before and after free authors, and fail closed on egress matches. Never use `--dangerously-skip-permissions` or `--yolo`.

A worktree is collaboration isolation, not a security boundary. Free write-enabled workers require a verified restricted profile with shell/tool execution denied and a link-free worktree; otherwise use them only read-only or skip them. Codex authors use its workspace-write sandbox; Codex reviewers use read-only. Do not let a worker run tests or acceptance commands. The coordinator runs only the explicitly authorized `--accept` command after the required review gate.
