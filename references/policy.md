# Authority, routing, quota fallback (from v2.1 sections 00, 0, 1, 1b)
## 00. Operating mode (v2, 2026-10-29)
Owner says WHAT; the coordinator decides HOW. One confirmation point, then autonomous inside the authorized scope.
1. Decide first whether to dispatch at all: a single small edit, or design work needing large shared context, is done directly. Dispatch only when parallel/independent tasks or an independent reviewer pay for the overhead.
2. Confirm the plan/spec ONCE (tasks, scope, authorization level, what stays unauthorized). Same version is never asked again. After that, split, pre-flight, dispatch, review, fix and verify without asking.
3. The dispatch runner is authorized to create its task branch, push only that branch, and create a draft PR as specified in SKILL.md. It never marks a PR ready or merges. The standing self-merge rule governs merge; repository rules win. Come back to the Owner for external or paid provider egress, review not converged in 3 rounds, or a decision only the Owner can make. Collect open questions into one message.
4. Roles (from Pilotfish, policy only, no installs): scout = read-only recon; executor = bounded implementation; verifier = fresh-context reviewer that never saw the author's reasoning. Match model to risk: cheap model for mechanical work, stronger model for judgment/safety, never the author as its own verifier.
5. Evidence over reports (from LoopAgentTeams): verify delivered commits/files from git and re-run the acceptance commands on the delivered version. Final result states are PASS / FAIL / UNPROVEN / NOT_EXECUTED; a required check that was not run is NOT_EXECUTED, never PASS.
6. Per-project verification (from pstack): when a project has its own verification skill/SOP, dispatch prompts must name it and acceptance must exercise the real product flow. If a project lacks one and the work is repeatable, propose creating it (do not create it unasked).
7. Not adopted: a second scheduler, a central governance layer, T3 Code as a required host (optional execution host only), full pilotfish/pstack/LAT installs. Projects keep their own SOP and permissions.

Owner-named assignments win over the routing and role defaults in this file: `dispatch.py ask` needs no verifier, `--reviewer none` is allowed when the Owner asks for it and is reported as unreviewed, and a named worker is never swapped for another. Data rules in section 0 still apply.

## 0. Authority and preconditions
- Apply the MOST RESTRICTIVE applicable rule. Repo rules may narrow permissions; they never loosen the user's global rules or explicit boundaries.
- Authorization is per action and never inferred from another. Within the dispatch flow, dispatch.py alone stages, commits, pushes its created task branch, and opens a draft PR; workers have no Git/GitHub credentials. It does not push the default branch or merge. Other remote writes and project-specific gates (platform calls, submissions, ledger writes, quota) keep their own explicit approval.
- Work only on tasks the user selected this session. An open issue is not a TODO queue; obey its authorization block. If not authorized: stop writing, ask once (with all other open questions).
- Before dispatch validate: repo identity, branch, base SHA, worktree ownership, other agents' active work (`git fetch`, `git status`, `git worktree list`), and the repo's test command/forbidden areas (copy them into every prompt).
- Egress is scoped per pool: OpenCode receives only an isolated copy of `--allowed` files and the task prompt, never the repository. A secret or policy match blocks that free-pool attempt. Codex runs under its workspace-write sandbox. Paid or unconfigured providers require separate authorization. The older one-size-fits-all egress wording is superseded by this pool-specific boundary.
- Pre-flight: model exists, auth works, cwd correct (OpenCode >= 1.18 for the free tier). A time-boxed author failure falls through to the next eligible pool in the order in SKILL.md; it is not retried on the same pool.

## 1. Split
- Classify each task: Implement, Review, Diagnose (read-only), Benchmark. Only Implement normally needs a branch/PR; Diagnose/Benchmark may just produce a report.
- Order by dependency; do not start a task whose prerequisite has not actually passed.
- Route: low lane authors OpenCode -> Codex; high lane uses Codex directly. The free advisory pre-screen runs only with `--prescreen` (v4.2: its output fed no decision). Codex uses the newest `*-luna` at medium effort, and another Codex model only when the Owner names it (`--model codex=<slug>`, Allen 2026-11-07); max is reserved for the final review of security- or data-related changes (Allen, 2026-11-04). Claude sub-agents default to Haiku; Sonnet is used only under the existing Codex-unavailable rule. Claude coordinates, checks evidence and applies the final gate.

- Codex unavailable (usage limit, auth, outage): in auto mode pick another author from the SKILL.md table and use `--reviewer claude-sonnet` where an independent review is required (standing substitution). Whether a review is required at all follows "Review in auto mode" in SKILL.md; there is no fixed Codex gate. Say in the report who reviewed, and offer a Codex pass when it returns for logic/safety changes. Check Codex availability from its stderr log (usage-limit text), not only from output files, before waiting on a Codex job.

## 1b. Quota-aware parallel dispatch
Goal: maximize VERIFIED work completed across all available CLI capacity. Codex, Claude Haiku/Sonnet and free OpenCode models are complementary execution pools, not substitutes.
1. Before dispatching, check quota/reset windows, active jobs, model availability, and provider permissions.
2. When Codex has subscription quota: give it more eligible implementation tasks and independent deep reviews; reserve capacity for critical verification. Do NOT restrict Codex to reviewing free agents.
3. When free OpenCode capacity exists: dispatch suitable low-risk tasks in parallel, preferring models with proven task-specific quality. Use it even if Codex has quota. Never send unsuitable work just to use quota.
4. Keep separate implementation and review queues. Free-model results wait in the review queue; Codex reviews at a sensible node of its own work, so Codex does not become a review-only bottleneck.
5. Schedule only authorized, dependency-ready tasks; respect worktree isolation, concurrency caps, provider limits, and data-egress rules (section 0).
6. Optimize for verified tasks completed, quality/review effort, elapsed time, quota utilization, and out-of-pocket cost. No fixed percentage split. Do not create low-value work to burn quota.
7. Rebalance when jobs finish or quota changes. Never silently activate paid models/APIs. Quota raises eligible concurrency; it never overrides quality or authorization gates.
Track per dispatch round: remaining quota, running jobs (any idle agent?), authorized ready tasks, review-queue size, per-model acceptance rate.

## 2. Runner details (moved out of SKILL.md in v4.2)
- Time: an author gets 10 minutes. A laptop sleeping mid-job stretches wall-clock time. Before adding a worker to the SKILL.md table, test it for real.
- `ask`: `repos.json` policy is enforced for OpenCode. Codex gets material embedded (up to 400000 characters). Answers are unverified until someone checks them.
- Roles: `no_free_pools` refuses OpenCode; `free_pool_deny` now refuses free pools when `--allowed` overlaps it. A Claude author has file tools only, inside the worktree, no shell. A Claude reviewer has no tools and sees only the diff. Explicit `--author`/`--reviewer` skip the lane defaults, the pre-screen and the docs shortcut.
- Parallel: several `ask` jobs may run at once, each with its own id; each `run` needs its own worktree slot. Slot path `<root>/<repo>/<agent>-work-1|2`: `<repo>` is the remote name or checkout folder name, `<agent>` is opencode, agy (legacy slot name only), codex or claude.
- Scope: `--allowed` is the change itself; `--may-touch` paths get every safety check `--allowed` gets. The acceptance command runs in a private temp folder.
- Ledger: the runner registers the task as RUNNING and closes it on exit.
- Run flow: resolve and fetch the remote default branch, create `dispatch/<task-id>`, author, commit only explicit scoped files, review, accept, draft PR. Existing ledger ids are refused; a run that fails before its branch exists does not use up its id. An extra slot needs `--allow-extra-worktree` and a report to the Owner first. Private repositories get the draft PR before review; public or unknown visibility is pushed only after a clean review. Merge follows the standing self-merge rule, subject to repository rules and required checks.
- Isolation: OpenCode sees only an isolated copy of the allowed files and the prompt. Codex authoring gets a fresh per-run temp directory. Egress scans run before any free-pool request.
- Review routing: a fresh read-only Codex review of the exact commit by default; docs-only from a free author gets a Codex review; Codex-authored docs need no second review. Fixes are new trusted commits with a fresh review, up to three rounds. `--accept` runs credential-free; any tracked-file change fails. The default branch is checked again before PASS.
- Free pools suit time-boxed surveys, digests, explicit-file-list tests and docs; avoid broad multi-step edits, long tasks and live platform actions. Start a new conversation for each batch.
