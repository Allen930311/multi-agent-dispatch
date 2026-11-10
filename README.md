# multi-agent-dispatch

**Let Claude Code be the tech lead, not the only engineer.**

You talk to Claude Code the way you'd talk to a lead: *"Haiku writes it, Codex reviews it."*
Claude turns that into one command. A Python runner then hands the task to the worker you named, runs your tests, gets a separate model to review the diff, and opens a **draft** PR. Nothing is merged without you.

```
 you ──"Haiku writes, Codex reviews"──▶ Claude Code (coordinator)
                                            │  dispatch.py run …
                                            ▼
   ┌──────────── isolated git worktree ─────────────────────────────┐
   │  author  ──▶  your --accept command  ──▶  independent reviewer │
   │  (claude-haiku)    (e.g. pytest)            (codex, read-only) │
   │       ▲________ failing tests / findings sent back ______│     │
   └────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
                           draft PR + one-line JSON result
```

---

## The three doors

Before dispatching anything, the skill makes Claude pick the cheapest door that fits. **Dispatching has a cost:** you write the brief, wait, and check the result. A cheap worker whose work has to be redone is not cheap.

| Door | When | What happens |
|---|---|---|
| 🚪 **Do it yourself** | Writing the brief takes longer than doing the job | No dispatch. Claude just does it. |
| 💬 **`ask`** | You only need an answer or some text | One worker reads a *copy* of the files and writes `result.md`. No branch, no commit, no PR. |
| 🔧 **`run`** | The repository must change | Author → tests → review → draft PR, inside a locked worktree slot. |

---

## A day with it

### 1. Get a quick summary from a cheap model (`ask`)

> **You:** Ask Haiku to summarise what `src/billing/` does. I just need a short brief.

Claude writes a prompt file and runs:

```bash
python ~/.claude/skills/multi-agent-dispatch/dispatch.py ask billing-brief \
  --pool claude-haiku --prompt brief.md --read src/billing
```

```json
{"state": "PASS", "pool": "claude-haiku", "seconds": 7.4, "result": ".../billing-brief/result.md"}
```

The worker never touched your repository. It saw a copy of `src/billing`, and content that looks like a secret was refused before it left your machine.

### 2. Make a change with an author and a reviewer (`run`)

> **You:** Fix the rounding bug in `invoice.py`. Codex writes it, Sonnet reviews it, and `pytest tests/billing` must pass.

```bash
python ~/.claude/skills/multi-agent-dispatch/dispatch.py run fix-rounding \
  --wt auto --lane high \
  --author codex --reviewer claude-sonnet \
  --prompt fix-rounding.md \
  --allowed src/billing/invoice.py --may-touch tests/billing \
  --accept "pytest tests/billing -q" \
  --title "fix: round invoice totals half-up"
```

```json
{"state": "PASS", "author": "codex", "rounds": 1, "tokens": 48210, "open_findings": 0, "task_id": "fix-rounding", "slot": ".../worktrees/myapp/claude-work-1"}
```

What happened in between:

1. **Slot.** `--wt auto` locked the first free `claude-work-1|2` worktree, so two runs never share a folder.
2. **Branch.** It created `dispatch/fix-rounding` from the remote's default branch.
3. **Author.** Codex edited the code. A change to any file outside `--allowed` / `--may-touch` is caught.
4. **Tests.** Your `--accept` command ran. On a failure, the output tail goes back to the author, up to two times.
5. **Review.** Sonnet reviewed the exact committed diff, from the diff only, with no tools.
6. **PR.** Only the runner holds Git credentials. It pushed that one branch and opened a **draft** PR.

### 3. When it doesn't PASS

| State | Meaning | What to do |
|---|---|---|
| `PASS_UNREVIEWED` | You asked for `--reviewer none` | Treat it as unreviewed |
| `BLOCKED` | The reviewer found real problems, or findings stopped converging | Sharpen the prompt or pick a stronger author |
| `NEEDS_SCOPE_DECISION` | The author touched files outside scope. The patch is kept | Rerun with `--may-touch` + `--seed-patch`, or drop those files |
| `ENVIRONMENT_ERROR` | A tool is missing, quota ran out, or no slot is free | Fix the machine, then `--seed-patch <recover_patch>` |

Kept work is never lost. Every partial run leaves a full patch from the base, and you can resume from it.

---

## Who can do what

| Worker | Good for | Can author | Can review |
|---|---|:-:|:-:|
| `opencode` (free models) | Quick digests, docs, copy | ✅ (sees only a copy of `--allowed`) | ❌ |
| `claude-haiku` | Fast reads, small scoped edits | ✅ (file tools only, no shell) | ✅ |
| `claude-sonnet` | Harder writing; review when Codex is out | ✅ | ✅ (diff only) |
| `codex` | Logic, data, security; the default reviewer | ✅ (workspace-write sandbox) | ✅ (read-only) |

When you name a worker, that exact worker is used. There is no silent fallback; if it fails, you are told.

---

## Install

```bash
# 1. Put the skill where Claude Code finds it
git clone https://github.com/Allen930311/multi-agent-dispatch ~/.claude/skills/multi-agent-dispatch

# 2. Give each repo you dispatch on one or two worktree slots
#    layout: ~/worktrees/<repo-name>/claude-work-1|2
cd ~/code/myapp
git worktree add --detach ~/worktrees/myapp/claude-work-1 origin/main
git worktree add --detach ~/worktrees/myapp/claude-work-2 origin/main
```

Requirements: Python 3.10+, `git`, `gh` (for PRs), and whichever worker CLIs you want to use: `codex`, `claude`, `opencode`.

Then, in Claude Code, simply say "dispatch this", or name the workers: *"Haiku writes, Codex reviews"*.

## Configure

**`repos.json`**, next to `dispatch.py`. Per-repository policy, keyed by remote:

```json
{
  "*": { "trailer": "Co-Authored-By: ...", "pr_trailer": "..." },
  "github.com/you/private-repo": {
    "no_free_pools": true,
    "free_pool_deny": ["data/", "secrets/"]
  }
}
```

**Environment variables:** `DISPATCH_WORKTREES_ROOT` (default `~/worktrees`), `DISPATCH_TMP_ROOT` (default `~/worktrees/_tmp`), `DISPATCH_REPOS_FILE`, `DISPATCH_SLOT_AGENT` (default `claude`), `DISPATCH_CODEX`.

## Safety model, in one breath

Workers never get Git or GitHub credentials. Free workers get an isolated copy of the files, never the repository. Secret-like content blocks the attempt. Only the runner commits, and only to its own branch. The result is always a **draft** PR. The runner never marks a PR ready and never merges.

> **Not supported: Antigravity CLI (`agy`).** Its terms (section 6) treat third-party tools driving the service as a breach, and accounts have been banned for it. `dispatch.py` refuses it on purpose.

## Tests

```bash
python -m unittest test_dispatch     # 136 tests, all with fake CLIs; no network or quota used
```

## Status

This was extracted from a personal setup that is used daily. `SKILL.md` and `references/` are written as instructions for Claude, so they are terse. It is developed on Windows; macOS/Linux should work but are less exercised. Issues and PRs are welcome.

MIT © Allen
