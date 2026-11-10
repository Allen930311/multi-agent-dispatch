# Review and acceptance

The runner reviews the exact committed diff with a fresh read-only reviewer: Codex by default, or the one named with `--reviewer`. Classify every finding as confirmed, false positive with evidence, Owner-accepted risk, deferred Low with written reason, or unclassified. Confirmed findings return to the author pool; each successful fix is a new runner-owned commit and gets a fresh review. A failed fix stage cannot be followed by PASS. Severity has fixed meanings given to the reviewer: high means wrong results, data loss, a security hole or a broken required behaviour; medium means a real defect with a concrete failing scenario that is not high; low means style, naming or optional hardening, never blocking. Round 1 reviews the whole diff exhaustively. Rounds 2 and 3 are verify rounds: the reviewer gets the earlier blocking findings and the diff of the fix, marks each finding `unfixed`, `fix` (introduced by the fix) or `new`, and may add a new finding only with a concrete failing scenario; stage records carry `mode` `full` or `verify`. The run stops as BLOCKED after three rounds, or earlier with "review findings are not converging" when a round has no fewer blocking findings than the previous one (measured on 24 runs: later rounds never repeated an earlier finding and only 3 runs passed after reaching round 3). With `DISPATCH_CODEX_RESUME=1` a Codex fix stage resumes the author's Codex session instead of starting a new one (stage record `resumed`; on failure a `RESUME_FAILED` stage is recorded and a fresh session is used). It is off by default until measured. Low findings remain in the summary.

Private repositories receive a draft PR before review; public or unknown visibility is pushed only after clean review. The runner never marks a PR ready or merges it. `--accept` runs credential-free at the specified point in the workflow; a nonzero result or tracked-file mutation fails. Scope violations, secret-like diffs, missing evidence, unparseable review output, a changed default branch, or summary-write failure cannot PASS.

For implementation, verify the required tests ran, not only that output contains a pass message. Check regressions and edge cases; for behavior defects, capture fail-before on the correct base and pass-after. Review tasks confirm the reviewed source version and reproduce findings. Diagnosis separates evidence from hypotheses. Benchmarks use fixed inputs and environment with repeated measurements. Passing regressions never excuse an open finding or an unrun required suite.

Set `PYTHONUTF8=1` for Windows tools. Never use `git add -A`; stage explicit scoped files. Free reviewers are advisory only and see an empty isolated folder and diff text. Re-scan secrets before each free-pool request.

## Recovery without re-authoring (v4.1)

`NEEDS_SCOPE_DECISION`: an author changed files outside `--allowed`/`--may-touch`. The slot is reset, the patch is kept (`out_of_scope[].patch` in summary.json). Every kept patch (`partial_author_*`, `partial_fix_*`, `recover_patch`) is the full change from the run's base, so any of them can be passed to `--seed-patch` as-is. The coordinator decides without asking the Owner: when the extra files are tests, interfaces, docs or ledgers the change genuinely needs and repository rules expect them, rerun with a new task id, `--may-touch <path>` and `--seed-patch <patch>`; when they are unrelated or sensitive, drop them (edit the patch or rerun the author with a sharper prompt) and say so in the report. Never widen scope into `free_pool_deny`, secrets, CI, deploy or credential paths this way.

`ENVIRONMENT_ERROR` from the acceptance command: the runner already retried once in a fresh temp folder. Fix the machine problem (locks, permissions, disk), then rerun with a new task id and `--seed-patch <recover_patch>`; the change is not re-authored. A seeded patch is untrusted: it gets the same scope, link, secret and review checks as any author output.

`FAIL` after a commit also leaves `recover_patch`. Use it only when the failure was not in the change itself.

## Owner-accepted risks (2026-11-04)

The Owner explicitly accepted review3 findings 8, 24, 25, and 26 on 2026-11-04. They remain accepted risks unless the Owner revisits them.

## Owner-accepted risk (2026-11-05)

Content scanning cannot recognize unpublished data that has no secret pattern. The coordinator must not include unpublished data in `--allowed` on the low lane, or set `no_free_pools` for that repository in `repos.json`.

## Test cadence

Full project suite once per PR on the final version after the last code change. Review-round fixes run only affected test files and obvious dependents plus cheap verify steps. Additive-only changes run the new tests and a small sample. Kill an obsolete full-suite run as soon as code changes again.
