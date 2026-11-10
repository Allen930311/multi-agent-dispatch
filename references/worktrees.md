# Worktree handling

`dispatch.py ask` needs no worktree. For `run`, use a free, clean linked worktree below the configured worktree root. Never use the primary checkout, a OneDrive path, or a worktree with another task's changes. The dispatcher creates a task branch from the remote's resolved default branch and leaves that branch and draft PR for review. `--wt auto` picks the first free `claude-work-1|2` slot (agent name from `DISPATCH_SLOT_AGENT`) and holds a lock file under `<temp root>/dispatch-locks` until the run ends; a lock older than 6 hours is taken over.

Before cleanup, confirm workers and tests stopped, inspect tracked, staged, untracked, and ignored files, and preserve commits, patches, reports, and PR status. Do not remove a worktree or branch while its work is unmerged or unpushed. Remove only the task's own branch/worktree after its PR is merged or closed under the standing self-merge and cleanup rules. Never force-delete unharvested work. Remote branch deletion remains limited to branches this session pushed and requires the PR to be merged or closed.

Use a temporary directory under `~/worktrees/_tmp`; Codex gets only the fresh per-run subdirectory. The runner deletes only the directory it created and records cleanup failure. Python 3.13 may create owner-only temporary directories; their creator must remove them.
