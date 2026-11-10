"""Stub-only dispatch integration and policy regression tests."""
import json
import contextlib
import io
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import dispatch
import metrics
import pools

TMP = pathlib.Path(os.environ.get("DISPATCH_TEST_TMP", str(pathlib.Path.home() / "worktrees" / "_tmp" / "dispatch-tests")))


class Fixture(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TMP, prefix="new-dispatch-")
        self.root = pathlib.Path(self.temp.name)
        self.bare = self.root / "origin.git"
        self.primary = self.root / "primary"
        self.wt = self.root / "worktrees" / "pool"
        self.wt.parent.mkdir()
        self.git(self.root, "init", "--bare", str(self.bare))
        self.git(self.root, "init", str(self.primary))
        self.git(self.primary, "config", "user.name", "Test")
        self.git(self.primary, "config", "user.email", "test@example.invalid")
        (self.primary / "base.txt").write_text("base\n", encoding="utf-8")
        self.git(self.primary, "add", "base.txt")
        self.git(self.primary, "commit", "-m", "base")
        self.git(self.primary, "branch", "-M", "trunk")
        self.git(self.primary, "remote", "add", "origin", str(self.bare))
        self.git(self.primary, "push", "-u", "origin", "trunk")
        self.base_sha = self.git(self.primary, "rev-parse", "HEAD")
        self.git(self.bare, "symbolic-ref", "HEAD", "refs/heads/trunk")
        self.git(self.primary, "worktree", "add", "--detach", str(self.wt), "origin/trunk")
        self.prompt = self.root / "prompt.md"
        self.prompt.write_text("Edit base.txt as requested.", encoding="utf-8")
        self.body = self.root / "body.md"
        self.body.write_text("Draft for review", encoding="utf-8")
        self.out = self.root / "out"
        self.tmproot = self.root / "tmp"
        self.log = self.root / "launch.jsonl"
        self.codex = self.stub("codex", self.codex_script())
        self.agy = self.stub("agy", self.agy_script())
        self.opencode = self.stub("opencode", self.opencode_script())
        self.gh = self.stub("gh", self.gh_script())
        self.claude = self.stub("claude", self.claude_script())

    def tearDown(self):
        self.temp.cleanup()

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()

    def stub(self, name, source):
        path = self.root / (name + ".py")
        path.write_text(source, encoding="utf-8")
        return path

    def codex_script(self):
        return '''import json,os,pathlib,subprocess,sys
args=sys.argv[1:]; prompt=sys.stdin.read(); log=pathlib.Path(os.environ["STUB_LOG"])
with log.open("a",encoding="utf-8") as f:f.write(json.dumps({"tool":"codex","args":args,"prompt":prompt,"env":{k:v for k,v in os.environ.items() if "TOKEN" in k},"remote_branch_exists":subprocess.run(["git","--git-dir",os.environ["STUB_BARE"],"show-ref","--verify","--quiet","refs/heads/dispatch/case"]).returncode==0})+"\\n")
if "debug" in args: print(os.environ.get("CODEX_MODELS_BAD", "gpt-6.1-luna")); raise SystemExit(0)
if "read-only" in args:
 seq=json.loads(os.environ["REVIEW_SEQ"]) if os.environ.get("REVIEW_SEQ") else None; n=sum(1 for x in log.read_text(encoding="utf-8").splitlines() if json.loads(x).get("tool")=="codex" and "read-only" in json.loads(x).get("args",[]))-1; final=seq[min(n,len(seq)-1)] if seq else os.environ.get("REVIEW_FINAL",'{"findings":[]}')
 print(os.environ.get("REVIEW_STREAM",json.dumps({"type":"item.completed","item":{"text":final}}))); raise SystemExit(int(os.environ.get("REVIEW_RC","0")))
print(json.dumps({"type":"thread.started","thread_id":"thread-1"}))
if "resume" in args and os.environ.get("CODEX_RESUME_FAIL")=="1": raise SystemExit(5)
if os.environ.get("CODEX_MODE")=="hang": pathlib.Path(os.environ["STUB_HUNG_PID"]).write_text(str(os.getpid())); import time; time.sleep(20)
if os.environ.get("CODEX_MODE")=="secret": pathlib.Path(os.environ["STUB_WT"],"base.txt").write_text("Authorization: Bearer opaque-token-value\\n"); raise SystemExit(0)
if os.environ.get("CODEX_FIX_FAIL")=="1" and "Address these review findings" in prompt: raise SystemExit(4)
if os.environ.get("CODEX_FIX_STRAY")=="1" and "Address these review findings" in prompt: pathlib.Path(os.environ["STUB_WT"],"base.txt").write_text("fixed\\n"); pathlib.Path(os.environ["STUB_WT"],"stray.txt").write_text("x\\n"); raise SystemExit(0)
if os.environ.get("CODEX_MODE")=="commit":
 p=os.environ["STUB_WT"]; pathlib.Path(p,"base.txt").write_text("worker change\\n"); subprocess.run(["git","-C",p,"add","base.txt"],check=True); subprocess.run(["git","-C",p,"-c","user.name=Stub","-c","user.email=stub@example.invalid","commit","-m","worker"],check=True); raise SystemExit(0)
if os.environ.get("CODEX_MODE")=="fail": raise SystemExit(2)
if os.environ.get("CODEX_MODE")=="partial": pathlib.Path(os.environ["STUB_WT"],"base.txt").write_text("half done\\n"); raise SystemExit(2)
if os.environ.get("CODEX_MODE")=="extra": pathlib.Path(os.environ["STUB_WT"],"base.txt").write_text("extra change\\n"); pathlib.Path(os.environ["STUB_WT"],"tests").mkdir(exist_ok=True); pathlib.Path(os.environ["STUB_WT"],"tests","test_x.py").write_text("def test_x():\\n    assert True\\n"); raise SystemExit(0)
if "The acceptance command failed" in prompt: n=sum("The acceptance command failed" in x for x in log.read_text(encoding="utf-8").splitlines()); pathlib.Path(os.environ["STUB_WT"],"base.txt").write_text("accept fixed %d\\n" % n,encoding="utf-8"); raise SystemExit(0)
if "Address these review findings" in prompt: n=sum("Address these review findings" in x for x in log.read_text(encoding="utf-8").splitlines()); pathlib.Path(os.environ["STUB_WT"],"base.txt").write_text("fixed %d\\n" % n,encoding="utf-8"); raise SystemExit(0)
pathlib.Path(os.environ["STUB_WT"],"base.txt").write_text("changed\\n",encoding="utf-8")
if os.environ.get("CODEX_MODE")=="tokens": print(json.dumps({"total_tokens":167008}))
'''

    def agy_script(self):
        return '''import json,os,pathlib,subprocess,sys
args=sys.argv[1:]; settings=args[args.index("--settings")+1] if "--settings" in args else ""; pathlib.Path(os.environ["STUB_LOG"]).open("a",encoding="utf-8").write(json.dumps({"tool":"agy","args":args,"settings":json.loads(pathlib.Path(settings).read_text()) if settings and pathlib.Path(settings).exists() else None,"cwd":os.getcwd(),"env":{k:v for k,v in os.environ.items() if "TOKEN" in k}})+"\\n")
pathlib.Path(os.environ["STUB_WT"],"base.txt").write_text("agy change\\n",encoding="utf-8")
'''

    def opencode_script(self):
        return '''import json,os,pathlib,subprocess,sys
args=sys.argv[1:]; launch=pathlib.Path(args[args.index("--dir")+1]) if "--dir" in args else pathlib.Path(os.environ.get("PWD",os.getcwd())); pathlib.Path(os.environ["STUB_LOG"]).open("a",encoding="utf-8").write(json.dumps({"tool":"opencode","args":args,"cwd":os.getcwd(),"pwd":os.environ.get("PWD"),"oldpwd":os.environ.get("OLDPWD"),"launch":str(launch),"files":sorted(str(p.relative_to(launch)) for p in launch.rglob('*') if p.is_file()),"env":{k:v for k,v in os.environ.items() if "TOKEN" in k}})+"\\n")
os.chdir(launch)
if os.environ.get("OPENCODE_ASK"): print(os.environ["OPENCODE_ASK"]); raise SystemExit(0)
if os.environ.get("OPENCODE_MODE")=="breach": pathlib.Path("base.txt").write_text("breach edit\\n"); print("\\x1b[91mRead C:/outside/private.txt failed\\x1b[0m"); raise SystemExit(1)
if os.environ.get("OPENCODE_MODE")=="fail": raise SystemExit(2)
if os.environ.get("OPENCODE_MODE")=="empty": raise SystemExit(0)
if os.environ.get("OPENCODE_MODE")=="out": pathlib.Path("evil.txt").write_text("x"); raise SystemExit(0)
if os.environ.get("OPENCODE_MODE")=="link": subprocess.run(["cmd.exe","/d","/c","mklink","/J","linkdir",os.environ["STUB_WT"]],check=True); raise SystemExit(0)
pathlib.Path("base.txt").write_text("opencode change\\n",encoding="utf-8")
'''

    def claude_script(self):
        return """import json,os,pathlib,sys
args=sys.argv[1:]; prompt=sys.stdin.read(); pathlib.Path(os.environ["STUB_LOG"]).open("a",encoding="utf-8").write(json.dumps({"tool":"claude","args":args,"cwd":os.getcwd(),"env":sorted(k for k in os.environ if k.upper().startswith("CLAUDE") or "TOKEN" in k)})+"\\n")
tools=args[args.index("--tools")+1] if "--tools" in args else ""
if "--json-schema" in args: print(os.environ.get("STUB_REVIEW",json.dumps({"type":"result","is_error":False,"structured_output":{"findings":[]},"usage":{"input_tokens":3,"output_tokens":4}}))); raise SystemExit(0)
if "Edit" in tools: pathlib.Path("base.txt").open("a",encoding="utf-8").write("claude change\\n")
print(json.dumps({"type":"result","is_error":False,"result":"claude answer"}))
"""

    def gh_script(self):
        return '''import json,os,pathlib,subprocess,sys
args=sys.argv[1:]; log=pathlib.Path(os.environ["STUB_LOG"]); pathlib.Path(os.environ["GH_CREATE_COUNT"]).write_text(str(sum(1 for x in log.read_text().splitlines() if json.loads(x).get("tool")=="gh" and json.loads(x).get("args",[])[:2]==["pr","create"]) + (args[:2]==["pr","create"]))) if log.exists() else None
with log.open("a",encoding="utf-8") as f:f.write(json.dumps({"tool":"gh","args":args})+"\\n")
if args[:2]==["pr","create"] and int(pathlib.Path(os.environ["GH_CREATE_COUNT"]).read_text())>1: print("a pull request already exists",file=sys.stderr); raise SystemExit(1)
if args[:2]==["pr","create"] and os.environ.get("CHANGE_DEFAULT_TO"): subprocess.run(["git","--git-dir",os.environ["STUB_BARE"],"update-ref","refs/heads/trunk",os.environ["CHANGE_DEFAULT_TO"]],check=True)
print(json.dumps({"visibility":os.environ.get("GH_VISIBILITY","PRIVATE")} ) if args[:3]==["repo","view","--json"] else json.dumps({"url":"https://example.invalid/pr/1"}) if args[:3]==["pr","view","--json"] else "https://example.invalid/pr/1")
'''

    def env(self, **extra):
        return dict(os.environ, DISPATCH_TEST_MODE="1", DISPATCH_WORKTREES_ROOT=str(self.wt.parent),
                    DISPATCH_TEST_WORKTREES_ROOT=str(self.wt.parent), DISPATCH_TMP_ROOT=str(self.tmproot), DISPATCH_POOLS_STATE=str(self.root / "pools.json"),
                    DISPATCH_CODEX_MODEL="gpt-6.1-luna", DISPATCH_CODEX=str(self.codex),
                    DISPATCH_AGY=str(self.agy), DISPATCH_OPENCODE=str(self.opencode), DISPATCH_GH=str(self.gh), DISPATCH_CLAUDE=str(self.claude), CLAUDECODE="1",
                    DISPATCH_STUB_WT=str(self.wt), STUB_WT=str(self.wt), STUB_BARE=str(self.bare), STUB_LOG=str(self.log), STUB_HUNG_PID=str(self.root / "hung.pid"), GH_CREATE_COUNT=str(self.root / "gh-count"), GH_TOKEN="secret",
                    **extra)

    def invoke(self, lane="low", extra=(), env=None, accept="exit 0", task="case", allow_extra=True, wt=None, body=True, default_trailers=False):
        command = [sys.executable, str(pathlib.Path(dispatch.__file__)), "run", task, "--wt", wt or str(self.wt),
                   "--prompt", str(self.prompt), "--lane", lane, "--accept", accept, "--allowed", "base.txt",
                   "--title", "Test change", "--base", "origin/trunk",
                   "--out-dir", str(self.out)] + (["--body-file", str(self.body)] if body else []) + (["--allow-extra-worktree"] if allow_extra else []) + ([] if "--trailer-file" in extra or default_trailers else ["--no-trailer"]) + list(extra)
        e = env or self.env()
        return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=e, timeout=40)

    def summary(self, task="case"):
        return json.loads((self.out / task / "summary.json").read_text(encoding="utf-8"))

    def launched(self):
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []

    def test_full_fallthrough(self):
        r = self.invoke(env=self.env(OPENCODE_MODE="fail"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        names = [x["tool"] for x in self.launched()]
        self.assertLess(names.index("opencode"), names.index("codex"))
        self.assertNotIn("agy", names)

    def test_empty_author_falls_through(self):
        r = self.invoke(env=self.env(OPENCODE_MODE="empty"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.summary()["author"], "codex")

    def test_high_lane_skips_free_authors(self):
        r = self.invoke("high")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertLess(len(r.stdout.strip()), 400)
        names = [x["tool"] for x in self.launched()]
        self.assertIn("codex", names)
        self.assertNotIn("agy", names); self.assertNotIn("opencode", names)

    def test_ledger_records_real_author_pool_tokens_and_once_only_pool_ok(self):
        r = self.invoke("high", env=self.env(CODEX_MODE="tokens"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = json.loads((self.root / "pools.json").read_text(encoding="utf-8"))
        self.assertEqual(state["tasks"]["case"]["pool"], "codex")
        self.assertEqual(state["tasks"]["case"]["tokens"], 167008)
        self.assertEqual(state["codex"]["tokens"], 167008); self.assertEqual(state["codex"]["runs"], 1)

    def test_opencode_isolated_folder_has_no_git_and_only_allowed_files(self):
        # The worker cwd is checked by the actual stub's absence of repository metadata.
        r = self.invoke(extra=("--no-pr",))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        item = next(x for x in self.launched() if x["tool"] == "opencode")
        self.assertNotIn(".git", item["files"])
        self.assertEqual(sorted(item["files"]), ["TASK.md", "base.txt", "opencode.json"])
        self.assertIn("--dir", item["args"]); self.assertEqual(item["pwd"], item["launch"]); self.assertEqual(item["oldpwd"], item["launch"])

    def test_opencode_isolation_breach_discards_and_records_paths(self):
        r = self.invoke(env=self.env(OPENCODE_MODE="breach"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        stage = next(x for x in self.summary()["stages"] if x.get("pool") == "opencode" and x.get("stage") == "author")
        self.assertTrue(stage["isolation_breach"]); self.assertEqual(stage["reason"], "isolation breach")
        self.assertEqual([x.replace("\\", "/") for x in self.summary()["isolation_breach_paths"]], ["C:/outside/private.txt"])
        self.assertEqual((self.wt / "base.txt").read_text(), "changed\n")

    def test_prescreen_isolation_breach_is_reported(self):
        task = self.root / "prescreen-task"; task.mkdir(); args = type("Args", (), {"wt": self.wt})
        def breached(cmd, cwd, path, *args, **kwargs):
            pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True); pathlib.Path(path).write_text("Read C:/outside/file.txt failed")
            return 1, 0.1, "refused"
        with mock.patch.object(dispatch, "execute", side_effect=breached):
            result = dispatch.free_prescreen(args, task, self.out, "review", "diff")
        self.assertTrue(result["isolation_breach"]); self.assertEqual(result["reason"], "isolation breach")

    def test_opencode_link_rejected(self):
        r = self.invoke(env=self.env(OPENCODE_MODE="link"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        stage = next(x for x in self.summary()["stages"] if x.get("pool") == "opencode")
        self.assertTrue(stage["isolation_breach"]); self.assertTrue(stage["offending_paths"])

    def test_opencode_out_of_scope_return_rejected(self):
        r = self.invoke(env=self.env(OPENCODE_MODE="out"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        stage = next(x for x in self.summary()["stages"] if x.get("pool") == "opencode")
        self.assertIn("out-of-scope", stage["error"])

    def test_worker_environment_strips_github_token(self):
        with mock.patch.dict(os.environ, {"GH_TOKEN": "x", "GITHUB_TOKEN": "y", "NORMAL": "z"}):
            env = dispatch.safe_worker_env()
        self.assertNotIn("GH_TOKEN", env); self.assertNotIn("GITHUB_TOKEN", env); self.assertEqual(env["NORMAL"], "z")

    def test_worker_environment_adds_no_empty_values(self):
        # The runner must not add empty values (Windows drops them when os.environ is restored);
        # an empty value the caller passes on, such as a test stub's REVIEW_FINAL, is kept as is.
        with mock.patch.dict(os.environ, {"NORMAL": "z", "INHERITED_EMPTY": ""}, clear=True):
            env = dispatch.safe_worker_env()
        self.assertEqual([key for key, value in env.items() if value == ""], ["INHERITED_EMPTY"])

    def test_worker_environment_resets_local_credential_helpers(self):
        repo = pathlib.Path(tempfile.mkdtemp(dir=TMP, prefix="credential-helper-"))
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        credentials = repo.parent / (repo.name + "-credentials")
        self.addCleanup(credentials.unlink, missing_ok=True)
        credentials.write_text("https://worker:secret@example.invalid", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "credential.helper",
                        "store --file=" + credentials.as_posix()], check=True)
        request = "protocol=https\nhost=example.invalid\n"
        result = subprocess.run(["git", "-C", str(repo), "credential", "fill"], input=request,
                                env=dispatch.safe_worker_env(), capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        control = subprocess.run(["git", "-C", str(repo), "credential", "fill"], input=request,
                                 env={k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_CONFIG_")},
                                 capture_output=True, text=True)
        self.assertEqual(control.returncode, 0, control.stdout + control.stderr)

    def test_worker_environment_survives_os_environ_round_trip(self):
        root = pathlib.Path(tempfile.mkdtemp(dir=TMP, prefix="env-round-trip-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        code = (
            "import os, subprocess, sys; from unittest.mock import patch; "
            "ctx=patch.dict(os.environ, {'DISPATCH_ROUND_TRIP':'1'}); ctx.__enter__(); ctx.__exit__(None,None,None); "
            "p=subprocess.run(['git','init','--bare',sys.argv[1]],capture_output=True,text=True); "
            "print(p.stderr); sys.exit(p.returncode)"
        )
        result = subprocess.run([sys.executable, "-c", code, str(root / "child.git")],
                                env=dispatch.safe_worker_env(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_no_worker_stub_receives_github_token(self):
        r = self.invoke("high")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(all(not x.get("env") for x in self.launched() if x["tool"] in {"codex", "agy", "opencode"}))

    def test_secret_prompt_skips_both_free_authors(self):
        self.prompt.write_text("Please use password=private-value only locally", encoding="utf-8")
        r = self.invoke()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        stages = self.summary()["stages"]
        self.assertTrue(all(x.get("result") == "SKIPPED" for x in stages if x.get("pool") in {"agy", "opencode"} and x.get("stage") == "author"))
        self.assertEqual(self.summary()["author"], "codex")

    def test_private_pushes_and_opens_draft_before_review(self):
        r = self.invoke("high", env=self.env(GH_VISIBILITY="PRIVATE"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        stages = [x.get("stage") for x in self.summary()["stages"]]
        self.assertEqual(self.summary()["pr_url"], "https://example.invalid/pr/1")
        self.assertEqual(self.summary()["state"], "PASS")
        self.assertLess(stages.index("author"), stages.index("review"))
        codex_review = next(x for x in self.launched() if x["tool"] == "codex" and "read-only" in x["args"])
        gh_create = next(i for i, x in enumerate(self.launched()) if x["tool"] == "gh" and x["args"][:2] == ["pr", "create"])
        review_i = next(i for i, x in enumerate(self.launched()) if x == codex_review)
        self.assertLess(gh_create, review_i)
        self.assertEqual(sum(x["tool"] == "gh" and x["args"][:2] == ["pr", "create"] for x in self.launched()), 1)

    def test_public_visibility_waits_for_review(self):
        r = self.invoke("high", env=self.env(GH_VISIBILITY="PUBLIC"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        review = next(x for x in self.launched() if x["tool"] == "codex" and "read-only" in x["args"])
        self.assertFalse(review["remote_branch_exists"])

    def test_unknown_visibility_is_public_behavior(self):
        r = self.invoke("high", env=self.env(GH_VISIBILITY="UNKNOWN"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        review = next(x for x in self.launched() if x["tool"] == "codex" and "read-only" in x["args"])
        self.assertFalse(review["remote_branch_exists"])

    def test_worker_commit_detected(self):
        r = self.invoke("high", env=self.env(CODEX_MODE="commit"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("worker-made commit", self.summary()["stages"][0]["error"])

    def test_remote_default_branch_unchanged_and_branch_not_default(self):
        r = self.invoke()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.git(self.wt, "branch", "--show-current"), "dispatch/case")
        self.assertEqual(self.git(self.bare, "rev-parse", "refs/heads/trunk"), self.base_sha)

    def test_default_branch_remote_change_is_fail(self):
        (self.primary / "base.txt").write_text("advanced\n", encoding="utf-8")
        self.git(self.primary, "add", "base.txt"); self.git(self.primary, "commit", "-m", "advance")
        next_sha = self.git(self.primary, "rev-parse", "HEAD")
        self.git(self.primary, "push", "origin", "HEAD:refs/heads/test-next")
        r = self.invoke("high", env=self.env(CHANGE_DEFAULT_TO=next_sha))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("default branch changed", self.summary()["error"])

    def test_no_pr(self):
        r = self.invoke(extra=("--no-pr",))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNone(self.summary()["pr_url"])

    def test_malformed_review_not_pass(self):
        r = self.invoke("high", env=self.env(REVIEW_FINAL="not json"))
        self.assertNotEqual(r.returncode, 0)

    def test_empty_review_not_pass(self):
        r = self.invoke("high", env=self.env(REVIEW_FINAL=""))
        self.assertNotEqual(r.returncode, 0)

    def test_nonzero_review_not_pass(self):
        r = self.invoke("high", env=self.env(REVIEW_RC="3"))
        self.assertNotEqual(r.returncode, 0)

    def test_multi_item_stream_final_unparseable_not_pass(self):
        stream = '\n'.join([json.dumps({"type": "item.completed", "item": {"text": '{"findings":[]}'}}), json.dumps({"type": "item.completed", "item": {"text": "unparseable final"}})])
        with mock.patch.dict(os.environ, {"DISPATCH_TEST_MODE": "1", "DISPATCH_CODEX_MODEL": "gpt-test-luna"}), mock.patch.object(dispatch, "execute", return_value=(0, 0.1, stream)):
            with self.assertRaises(dispatch.DispatchError): dispatch.codex_review(self.wt, "origin/trunk", self.git(self.wt, "rev-parse", "HEAD"), "review", self.out, "multi")

    def test_failed_fix_cannot_be_followed_by_empty_review(self):
        finding = {"file": "base.txt", "line": 1, "severity": "High", "scenario": "repro"}
        r = self.invoke("high", env=self.env(REVIEW_FINAL=json.dumps({"findings": [finding]}), CODEX_FIX_FAIL="1"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("fix stage failed", self.summary()["error"])

    def test_fix_stage_partial_patch_is_full_change_from_base(self):
        finding = {"file": "base.txt", "line": 1, "severity": "High", "scenario": "repro"}
        r = self.invoke("high", env=self.env(REVIEW_FINAL=json.dumps({"findings": [finding]}), CODEX_FIX_STRAY="1"))
        self.assertNotEqual(r.returncode, 0)
        patches = [x["partial_patch"] for x in self.summary()["stages"] if x.get("stage") == "fix" and x.get("partial_patch")]
        self.assertTrue(patches)
        text = pathlib.Path(patches[0]).read_text(encoding="utf-8")
        self.assertIn("+fixed", text)
        self.assertIn("-base", text)
        self.assertEqual(self.status(), "")

    def test_empty_may_touch_is_a_clear_error(self):
        r = self.invoke(extra=["--may-touch", ""])
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("IndexError", r.stdout + r.stderr)
        self.assertIn("safe worktree-relative", r.stdout + r.stderr)

    def test_failed_author_edit_is_discarded_so_a_retry_can_run(self):
        r = self.invoke(extra=["--author", "codex", "--reviewer", "none"], env=self.env(CODEX_MODE="partial"))
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.summary()["state"], "FAIL")
        self.assertEqual(subprocess.run(["git", "-C", str(self.wt), "status", "--porcelain"], capture_output=True, text=True).stdout.strip(), "")

    def status(self):
        return subprocess.run(["git", "-C", str(self.wt), "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True).stdout.strip()

    def test_may_touch_accepts_adjacent_test_and_reports_it(self):
        r = self.invoke(extra=["--author", "codex", "--reviewer", "none", "--may-touch", "tests"], env=self.env(CODEX_MODE="extra"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        s = self.summary()
        self.assertEqual(s["state"], "PASS_UNREVIEWED")
        self.assertEqual(s["scope_expanded"], ["tests/test_x.py"])
        self.assertEqual(s["version"], dispatch.VERSION)

    def test_out_of_scope_keeps_patch_cleans_slot_and_seed_patch_resumes(self):
        r = self.invoke(extra=["--author", "codex", "--reviewer", "none"], env=self.env(CODEX_MODE="extra"))
        self.assertNotEqual(r.returncode, 0)
        s = self.summary()
        self.assertEqual(s["state"], "NEEDS_SCOPE_DECISION")
        self.assertEqual(s["out_of_scope"][0]["files"], ["tests/test_x.py"])
        patch = pathlib.Path(s["out_of_scope"][0]["patch"])
        text = patch.read_text(encoding="utf-8")
        self.assertIn("tests/test_x.py", text)
        self.assertIn("extra change", text)
        self.assertEqual(self.status(), "")
        self.git(self.wt, "switch", "--detach", "origin/trunk")
        before = len(self.launched())
        r = self.invoke(task="case2", extra=["--author", "codex", "--reviewer", "none", "--may-touch", "tests", "--seed-patch", str(patch)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        s = self.summary("case2")
        self.assertEqual(s["author"], "seed")
        self.assertEqual(s["scope_expanded"], ["tests/test_x.py"])
        self.assertFalse(any(x["tool"] == "codex" and "workspace-write" in x["args"] for x in self.launched()[before:]))

    def test_seed_patch_outside_scope_is_refused_and_slot_clean(self):
        self.invoke(extra=["--author", "codex", "--reviewer", "none"], env=self.env(CODEX_MODE="extra"))
        patch = pathlib.Path(self.summary()["out_of_scope"][0]["patch"])
        self.git(self.wt, "switch", "--detach", "origin/trunk")
        r = self.invoke(task="case2", extra=["--author", "codex", "--reviewer", "none", "--seed-patch", str(patch)])
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.summary("case2")["state"], "NEEDS_SCOPE_DECISION")
        self.assertEqual(self.status(), "")

    def test_stray_out_of_scope_file_does_not_block_next_author(self):
        r = self.invoke(extra=["--author", "codex", "--author", "claude-haiku"], env=self.env(CODEX_MODE="extra"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        s = self.summary()
        self.assertEqual(s["author"], "claude-haiku")
        self.assertEqual([x["result"] for x in s["stages"] if x.get("pool") == "codex" and x.get("stage") == "author"], ["OUT_OF_SCOPE"])
        self.assertNotIn("tests/test_x.py", self.git(self.wt, "ls-files"))

    def test_accept_environment_error_retries_once_then_passes(self):
        marker = (self.root / "lock-once").as_posix()
        cmd = "python -c \"import pathlib, sys; p = pathlib.Path('%s'); first = not p.exists(); p.write_text('x'); print('PermissionError: [WinError 32] in use' if first else 'ok'); sys.exit(1 if first else 0)\"" % marker
        r = self.invoke(accept=cmd, extra=["--reviewer", "none"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.out / "case" / "accept_retry.log").exists())

    def test_accept_environment_error_twice_is_environment_error_with_recover_patch(self):
        r = self.invoke(accept="python -c \"import sys; print('PermissionError: [WinError 32] in use'); sys.exit(1)\"", extra=["--reviewer", "none"])
        self.assertNotEqual(r.returncode, 0)
        s = self.summary()
        self.assertEqual(s["state"], "ENVIRONMENT_ERROR")
        self.assertIn("+opencode change", pathlib.Path(s["recover_patch"]).read_text(encoding="utf-8"))

    def test_real_test_failure_is_not_retried(self):
        r = self.invoke(accept="python -c \"import sys; print('AssertionError: 1 != 2'); sys.exit(1)\"", extra=["--reviewer", "none"])
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.summary()["state"], "FAIL")
        self.assertFalse((self.out / "case" / "accept_retry.log").exists())

    def test_accept_gets_private_temp_folder(self):
        r = self.invoke(accept="python -c \"import os, sys; sys.exit(0 if 'accept-tmp' in os.environ['TEMP'] else 5)\"", extra=["--reviewer", "none"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_version_flag(self):
        r = subprocess.run([sys.executable, str(pathlib.Path(dispatch.__file__)), "--version"], capture_output=True, text=True)
        self.assertIn(dispatch.VERSION, r.stdout)

    def test_accept_keeps_inner_quotes_and_writes_no_bytecode(self):
        r = self.invoke(accept='python -c "import os, sys; sys.exit(0 if os.environ.get(\'PYTHONDONTWRITEBYTECODE\') else 3)"')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_accept_tracked_mutation_fails(self):
        r = self.invoke(accept="echo bad > base.txt")
        self.assertNotEqual(r.returncode, 0)

    def test_accept_mutation_with_codex_author_gets_no_fix(self):
        r = self.invoke("high", accept="echo bad > base.txt")
        self.assertNotEqual(r.returncode, 0)
        s = self.summary()
        self.assertEqual(s["state"], "FAIL")
        self.assertFalse(any(x.get("stage") == "accept_fix" for x in s["stages"]))
        self.assertFalse(any("The acceptance command failed" in x["prompt"] for x in self.launched() if x["tool"] == "codex"))

    def test_accept_failure_goes_back_to_author_then_passes(self):
        accept = "python -c \"import pathlib, sys; ok = pathlib.Path('base.txt').read_text().startswith('accept fixed'); print('AssertionError: base.txt not fixed'); sys.exit(0 if ok else 1)\""
        r = self.invoke("high", accept=accept)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        s = self.summary()
        self.assertEqual(s["state"], "PASS")
        self.assertEqual([x["result"] for x in s["stages"] if x.get("stage") == "accept_fix"], ["OK"])
        fix = next(x for x in self.launched() if x["tool"] == "codex" and "The acceptance command failed" in x["prompt"])
        self.assertIn("AssertionError: base.txt not fixed", fix["prompt"])
        stages = [x.get("stage") for x in s["stages"]]
        self.assertLess(stages.index("accept_fix"), stages.index("review"))

    def test_accept_keeps_failing_after_two_fixes_ends_fail(self):
        r = self.invoke("high", accept="python -c \"import sys; print('AssertionError: never passes'); sys.exit(1)\"")
        self.assertNotEqual(r.returncode, 0)
        s = self.summary()
        self.assertEqual(s["state"], "FAIL")
        self.assertIn("accept failed or modified tracked/untracked worktree files", s["error"])
        self.assertEqual(sum(x.get("stage") == "accept_fix" for x in s["stages"]), 2)
        self.assertTrue(s["accept_log"].endswith("accept_retry_2.log"))
        self.assertTrue(pathlib.Path(s["accept_log"]).is_file())
        self.assertEqual(sum("The acceptance command failed" in x["prompt"] for x in self.launched() if x["tool"] == "codex"), 2)

    def test_seed_patch_with_failing_accept_is_not_reviewed(self):
        self.invoke(extra=["--author", "codex", "--reviewer", "none"], env=self.env(CODEX_MODE="extra"))
        patch = pathlib.Path(self.summary()["out_of_scope"][0]["patch"])
        self.git(self.wt, "switch", "--detach", "origin/trunk")
        r = self.invoke("high", task="case2", accept="python -c \"import sys; print('AssertionError: nope'); sys.exit(1)\"",
                        extra=["--author", "codex", "--may-touch", "tests", "--seed-patch", str(patch)], env=self.env(CODEX_MODE="fail"))
        self.assertNotEqual(r.returncode, 0)
        s = self.summary("case2")
        self.assertEqual(s["state"], "FAIL")
        self.assertIn("accept failed", s["error"])
        self.assertFalse(any(x.get("stage") == "review" for x in s["stages"]))

    def test_accept_fix_never_goes_to_a_free_pool(self):
        self.invoke(extra=["--author", "codex", "--reviewer", "none"], env=self.env(CODEX_MODE="extra"))
        patch = pathlib.Path(self.summary()["out_of_scope"][0]["patch"])
        self.git(self.wt, "switch", "--detach", "origin/trunk")
        before = len(self.launched())
        r = self.invoke("low", task="case2", accept="python -c \"import sys; print('AssertionError: nope'); sys.exit(1)\"",
                        extra=["--may-touch", "tests", "--seed-patch", str(patch)])
        self.assertNotEqual(r.returncode, 0)
        fixes = [x for x in self.summary("case2")["stages"] if x.get("stage") == "accept_fix"]
        self.assertTrue(fixes)
        self.assertEqual({x["pool"] for x in fixes}, {"codex"})
        self.assertFalse(any(x["tool"] == "opencode" for x in self.launched()[before:]))

    def test_author_is_told_the_acceptance_command_and_reviewer_is_not(self):
        r = self.invoke("high", accept="exit 0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        author = next(x for x in self.launched() if x["tool"] == "codex" and "workspace-write" in x["args"])
        reviewer = next(x for x in self.launched() if x["tool"] == "codex" and "read-only" in x["args"])
        self.assertIn("Acceptance command the runner will run", author["prompt"])
        self.assertIn("\nexit 0\n", author["prompt"])
        self.assertNotIn("Acceptance command the runner will run", reviewer["prompt"])

    def test_cleanup_failure_keeps_pass_and_is_reported(self):
        argv = ["run", "case", "--wt", str(self.wt), "--prompt", str(self.prompt), "--lane", "high", "--accept", "exit 0", "--allowed", "base.txt",
                "--title", "Test change", "--body-file", str(self.body), "--base", "origin/trunk", "--no-pr", "--no-trailer", "--allow-extra-worktree", "--out-dir", str(self.out)]
        with mock.patch.dict(os.environ, self.env()), mock.patch.object(dispatch, "remove_tree", return_value="WinError 32 file in use"), contextlib.redirect_stdout(io.StringIO()):
            code = dispatch.main(argv)
        self.assertEqual(code, 0)
        s = self.summary()
        self.assertEqual(s["state"], "PASS")
        self.assertTrue(s["cleanup_failed"].endswith("case"))
        self.assertIn("temporary folder removal failed: WinError 32 file in use", s["not_verified"])

    def test_remove_tree_deletes_read_only_file(self):
        tree = self.root / "readonly-tree"; (tree / "sub").mkdir(parents=True)
        locked = tree / "sub" / "locked.txt"; locked.write_text("x", encoding="utf-8"); os.chmod(locked, stat.S_IREAD)
        self.assertIsNone(dispatch.remove_tree(tree))
        self.assertFalse(tree.exists())

    def test_existing_temp_gets_suffix_and_content_preserved(self):
        d = self.tmproot / "case"; d.mkdir(parents=True); marker = d / "keep"; marker.write_text("safe")
        r = self.invoke()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertEqual(marker.read_text(), "safe")
        self.assertEqual(self.summary("case-2")["task_id"], "case-2")

    def test_summary_write_failure_nonzero(self):
        args = ["run", "writefail", "--wt", str(self.wt), "--prompt", str(self.prompt), "--lane", "high", "--accept", "exit 0", "--allowed", "base.txt", "--title", "x", "--body-file", str(self.body), "--base", "origin/trunk", "--no-pr", "--out-dir", str(self.out)]
        (self.tmproot / "writefail").parent.mkdir(parents=True, exist_ok=True)
        old = dispatch.write_summary
        try:
            dispatch.write_summary = mock.Mock(side_effect=OSError("disk full"))
            with mock.patch.dict(os.environ, self.env()), contextlib.redirect_stdout(io.StringIO()):
                result = dispatch.main(args)
        finally:
            dispatch.write_summary = old
        self.assertNotEqual(result, 0)

    def test_hung_author_is_killed_and_summary_written(self):
        r = self.invoke("high", env=self.env(CODEX_MODE="hang", DISPATCH_STAGE_TIMEOUT="0.3"))
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((self.out / "case" / "summary.json").is_file())
        pid = int((self.root / "hung.pid").read_text())
        process_list = subprocess.run(["tasklist", "/FI", "PID eq " + str(pid)], capture_output=True).stdout.decode("utf-8", "replace")
        self.assertNotIn(str(pid), process_list)

    def test_secret_diff_blocks_before_push(self):
        r = self.invoke("high", env=self.env(CODEX_MODE="secret"))
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.summary()["state"], "BLOCKED")
        result = subprocess.run(["git", "--git-dir", str(self.bare), "show-ref", "--verify", "--quiet", "refs/heads/codex/case"])
        self.assertNotEqual(result.returncode, 0)

    def test_prompt_is_stdin_not_process_argument(self):
        self.prompt.write_text('" & whoami & %PATH%', encoding="utf-8")
        r = self.invoke("high")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("whoami", " ".join(sum((x["args"] for x in self.launched()), [])))

    def test_final_max_is_explicit_and_review_schema_is_passed(self):
        sha = self.git(self.wt, "rev-parse", "HEAD")
        stream = json.dumps({"type": "item.completed", "item": {"text": '{"findings":[]}'}})
        with mock.patch.dict(os.environ, {"DISPATCH_TEST_MODE": "1", "DISPATCH_CODEX_MODEL": "gpt-test-luna"}), mock.patch.object(dispatch, "execute", return_value=(0, 0.1, stream)) as execute:
            dispatch.codex_review(self.wt, "origin/trunk", sha, "review", self.out, "medium-review", "medium")
            medium = execute.call_args.args[0]
            dispatch.codex_review(self.wt, "origin/trunk", sha, "review", self.out, "max-review", "max")
            maximum = execute.call_args.args[0]
        self.assertIn("--output-schema", medium)
        self.assertIn("model_reasoning_effort=medium", medium)
        self.assertIn("model_reasoning_effort=max", maximum)

    def test_codex_stage_timeout_mapping_and_fix_prompt(self):
        self.assertEqual([dispatch.codex_stage_timeout(x) for x in ("medium", "high", "xhigh", "max", "other")], [900, 900, 1200, 1800, 900])
        prompt = dispatch.fix_prompt("task", [{"file": "a.py"}])
        self.assertIn("Keep the change minimal and targeted at these findings", prompt)
        self.assertIn("Run only tests that cover the files you change, not the full suite", prompt)

    def test_author_uses_effort_timeout_and_claude_stays_at_900(self):
        args = type("Args", (), {"wt": self.wt})()
        with mock.patch.dict(os.environ, {"DISPATCH_TEST_MODE": "1", "DISPATCH_CODEX_MODEL": "gpt-test-luna", "DISPATCH_CODEX_EFFORT": "max"}), mock.patch.object(dispatch, "execute", return_value=(0, 0.1, "")) as execute:
            dispatch.author("codex", args, "task", self.root, self.out, "fix", {})
            self.assertEqual(execute.call_args.args[3], 1800)
        with mock.patch.dict(os.environ, {"DISPATCH_TEST_MODE": "1", "DISPATCH_CODEX_MODEL": "gpt-test-luna", "DISPATCH_CODEX_EFFORT": "medium"}), mock.patch.object(dispatch, "execute", return_value=(0, 0.1, "")) as execute:
            dispatch.author("codex", args, "task", self.root, self.out, "author", {})
            self.assertEqual(execute.call_args.args[3], 900)
        with mock.patch.object(dispatch, "execute", return_value=(0, 0.1, "")) as execute, mock.patch.object(dispatch, "claude_model", return_value="haiku"):
            dispatch.author("claude-haiku", args, "task", self.root, self.out, "author", {})
            self.assertEqual(execute.call_args.args[3], 900)

    def test_codex_max_review_uses_1800_second_timeout(self):
        sha = self.git(self.wt, "rev-parse", "HEAD")
        stream = json.dumps({"type": "item.completed", "item": {"text": '{"findings":[]}'}})
        with mock.patch.dict(os.environ, {"DISPATCH_TEST_MODE": "1", "DISPATCH_CODEX_MODEL": "gpt-test-luna"}), mock.patch.object(dispatch, "execute", return_value=(0, 0.1, stream)) as execute:
            dispatch.codex_review(self.wt, "origin/trunk", sha, "review", self.out, "max-review", "max")
            self.assertEqual(execute.call_args.args[3], 1800)

    def test_free_prescreen_uses_empty_opencode_folder_never_agy(self):
        r = self.invoke(extra=["--prescreen"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        items = self.launched()
        reader = next(x for x in items if x["tool"] == "opencode" and "free-reader" in x["args"])
        self.assertEqual(sorted(reader["files"]), ["TASK.md", "opencode.json"])
        self.assertIn("--dir", reader["args"]); self.assertEqual(reader["pwd"], reader["launch"])
        self.assertNotIn("agy", [x["tool"] for x in items])

    def test_repos_json_normalized_lookup(self):
        text = (ROOT / "repos.json").read_text(encoding="utf-8")
        self.assertIn("github.com/example-owner/private-repo", text)
        with mock.patch.object(dispatch, "remote_url", return_value="git@github.com:example-owner/private-repo.git"):
            policy, key = dispatch.repo_policy(self.wt)
        self.assertEqual(key, "github.com/example-owner/private-repo")
        self.assertEqual(policy["free_pool_deny"], ["src/miningkit/data", "_reports"])

    def test_scope_rejects_out_of_scope(self):
        (self.wt / "other.txt").write_text("bad")
        with self.assertRaises(dispatch.DispatchError): dispatch.scope(self.wt, "origin/trunk", [pathlib.PurePosixPath("base.txt")])

    def test_secret_bearer_detected(self):
        self.assertTrue(dispatch.SECRET.search("Authorization: Bearer opaque-token-value"))

    def test_p12_sensitive_name_detected(self):
        self.assertTrue(dispatch.SENSITIVE.search("certs/client.p12"))

    def test_default_branch_discovery_non_main(self):
        self.assertEqual(dispatch.default_branch(self.wt), "origin/trunk")

    def test_codex_model_override_only_in_test_mode(self):
        with mock.patch.dict(os.environ, {"DISPATCH_TEST_MODE": "1", "DISPATCH_CODEX_MODEL": "gpt-test-luna"}):
            self.assertEqual(dispatch.codex_model(), "gpt-test-luna")
        with mock.patch.dict(os.environ, {"DISPATCH_TEST_MODE": "0", "DISPATCH_CODEX_MODEL": "bad"}):
            sample = (pathlib.Path(__file__).resolve().parent / "test_fixtures" / "codex-models.json").read_text(encoding="utf-8")
            compact = json.dumps(json.loads(sample))
            self.assertIn('"slug": "gpt-6-luna"', sample)
            with mock.patch.object(dispatch, "run", return_value=type("P", (), {"returncode": 0, "stdout": "codex\n" + compact})()):
                self.assertEqual(dispatch.codex_model(), "gpt-6-luna")

    def test_named_codex_model_must_exist_and_luna_stays_default(self):
        listing = type("P", (), {"returncode": 0, "stdout": "codex\n" + json.dumps({"models": [{"slug": x} for x in ("gpt-6-luna", "gpt-6.1-sol", "gpt-5.6-luna")]})})()
        try:
            with mock.patch.dict(os.environ, {"DISPATCH_TEST_MODE": "0"}), mock.patch.object(dispatch, "run", return_value=listing):
                self.assertEqual(dispatch.codex_model(), "gpt-6-luna")
                dispatch.MODEL_OVERRIDES["codex"] = "gpt-6.1-sol"
                self.assertEqual(dispatch.codex_model(), "gpt-6.1-sol")
                dispatch.MODEL_OVERRIDES["codex"] = "gpt-9-made-up"
                with self.assertRaises(dispatch.ModelLookupError):
                    dispatch.codex_model()
        finally:
            dispatch.MODEL_OVERRIDES.clear()

    def test_run_model_flag_reaches_every_codex_call_and_is_reported(self):
        r = self.invoke("high", extra=["--model", "codex=gpt-6.1-sol"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = [x["args"] for x in self.launched() if x["tool"] == "codex" and "exec" in x["args"]]
        self.assertTrue(calls)
        self.assertTrue(all(c[c.index("-m") + 1] == "gpt-6.1-sol" for c in calls))
        self.assertEqual(self.summary()["models_named"], {"codex": "gpt-6.1-sol"})

    def test_run_model_flag_rejects_bad_format(self):
        r = self.invoke(extra=["--model", "gpt-6.1-sol"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("POOL=MODEL", r.stdout + r.stderr)
        r = self.invoke(task="case2", extra=["--model", "codex=gpt-6-luna", "--model", "codex=gpt-6.1-sol"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("two different --model", r.stdout + r.stderr)

    def test_free_prescreen_is_opt_in(self):
        r = self.invoke()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse([x for x in self.summary()["stages"] if x.get("stage") == "prescreen"])
        r = self.invoke(task="case2", extra=["--prescreen"])
        self.assertTrue([x for x in self.summary("case2")["stages"] if x.get("stage") == "prescreen"])

    def test_codex_model_lookup_failure_is_environment_error(self):
        env = self.env(OPENCODE_MODE="fail", CODEX_MODELS_BAD="invalid JSON"); env["DISPATCH_CODEX_MODEL"] = ""
        r = self.invoke(env=env)
        self.assertNotEqual(r.returncode, 0)
        summary = self.summary()
        self.assertEqual(summary["state"], "ENVIRONMENT_ERROR", json.dumps(summary)[:1500])

    def test_pools_pending_can_close_and_probe_models(self):
        self.assertIn("PENDING", pools.OPEN_STATES)
        self.assertNotIn("agy", pools.COOLDOWN)
        self.assertIn("codex_model()", pathlib.Path(pools.__file__).read_text(encoding="utf-8"))
        state = self.root / "pools-test.json"
        state.write_text(json.dumps({"opencode": pools.fresh_pool(), "agy": pools.fresh_pool(), "codex": pools.fresh_pool(), "tasks": {"pending": {"pool": "agy", "goal": "test", "start": 1, "state": "PENDING"}}}), encoding="utf-8")
        old_state, old_lock = pools.STATE, pools.LOCK
        try:
            pools.STATE, pools.LOCK = str(state), str(state) + ".lock"
            self.assertEqual(pools.main(["done", "pending", "PASS", "--tokens", "2"]), 0)
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["tasks"]["pending"]["state"], "PASS")
            self.assertEqual(pools.main(["start", "old-agy", "agy", "test"]), 2)
            self.assertEqual(pools.main(["start", "unknown", "codex", "test"]), 0)
            self.assertEqual(pools.main(["done", "unknown", "UNKNOWN"]), 2)
        finally:
            pools.STATE, pools.LOCK = old_state, old_lock

    def test_pool_probes_use_approved_models_without_launching_real_tools(self):
        with mock.patch.object(pools, "_run", return_value=(0, "OK")) as worker:
            self.assertEqual(pools.probe(["agy"]), 2)
            self.assertEqual(pools.live_probe("agy"), (False, "unknown pool"))
            worker.assert_not_called()
        with mock.patch.object(pools, "_run", return_value=(0, "OK")) as worker, mock.patch.object(dispatch, "resolve_tool", return_value=["codex-stub"]), mock.patch.dict(os.environ, {"DISPATCH_TEST_MODE": "1", "DISPATCH_CODEX_MODEL": "gpt-test-luna"}):
            pools.live_probe("codex")
            self.assertIn("gpt-test-luna", worker.call_args.args[0])

    def test_metrics_only_marks_actual_tool_use(self):
        f = self.root / "s.jsonl"
        f.write_text(json.dumps({"message": {"id": "1", "role": "assistant", "content": [{"type": "text", "text": "multi-agent-dispatch"}]}}), encoding="utf-8")
        self.assertFalse(metrics.summarize(f)["multi_agent_dispatch"])
        f.write_text(json.dumps({"message": {"id": "2", "role": "assistant", "content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "multi-agent-dispatch"}}]}}), encoding="utf-8")
        self.assertTrue(metrics.summarize(f)["multi_agent_dispatch"])


    def test_empty_accept_refused_before_workers(self):
        r=self.invoke(accept="   "); self.assertNotEqual(r.returncode,0); self.assertEqual(self.launched(),[])

    def test_policy_invalid_fails_closed_and_missing_is_empty(self):
        with mock.patch.object(dispatch,"ROOT",self.root):
            (self.root/"repos.json").write_text("{",encoding="utf-8")
            with self.assertRaises(dispatch.DispatchError): dispatch.repo_policy(self.wt)
            (self.root/"repos.json").write_text('{"x": []}',encoding="utf-8")
            with self.assertRaises(dispatch.DispatchError): dispatch.repo_policy(self.wt)
            (self.root/"repos.json").unlink(); self.assertEqual(dispatch.repo_policy(self.wt)[0],{})

    def test_embedded_remote_credentials_refused_and_redacted(self):
        self.git(self.wt,"remote","set-url","origin","https://user:ghp_secretcredential123456789@github.com/o/r.git")
        r=self.invoke("high"); self.assertNotEqual(r.returncode,0); self.assertEqual(self.launched(),[])
        self.assertNotIn("ghp_secret",(self.out/"case"/"summary.json").read_text(encoding="utf-8"))

    def test_hardlink_under_allowed_refused(self):
        import os as _os
        _os.link(self.wt/"base.txt",self.wt/"linked.txt")
        r=self.invoke("high"); self.assertNotEqual(r.returncode,0); self.assertEqual(self.launched(),[])

    def test_commit_rechecks_hardlinks_after_authoring(self):
        import os as _os
        _os.link(self.wt/"base.txt",self.wt/"linked.txt")
        with self.assertRaisesRegex(dispatch.DispatchError, "hard-linked allowed file"):
            dispatch.commit(self.wt, "origin/trunk", [pathlib.PurePosixPath("base.txt"), pathlib.PurePosixPath("linked.txt")], "test", None, False)
        self.assertEqual(self.git(self.wt,"rev-parse","HEAD"), self.base_sha)

    def test_output_task_reuse_keeps_old_content(self):
        d=self.out/"case"; d.mkdir(parents=True); (d/"keep").write_text("old")
        r=self.invoke(); self.assertEqual(r.returncode,0,r.stdout+r.stderr); self.assertEqual((d/"keep").read_text(),"old"); self.assertFalse((d/"summary.json").exists())
        self.assertEqual(self.summary("case-2")["task_id"],"case-2")

    def test_branch_collision_gets_suffix_before_author(self):
        self.git(self.wt,"branch","dispatch/case","origin/trunk")
        r=self.invoke(); self.assertEqual(r.returncode,0,r.stdout+r.stderr); self.assertEqual(self.summary("case-2")["state"],"PASS")
        self.assertEqual(self.git(self.wt,"branch","--show-current"),"dispatch/case-2")

    def test_remote_branch_collision_gets_suffix_before_author(self):
        self.git(self.primary,"branch","dispatch/case","origin/trunk"); self.git(self.primary,"push","origin","dispatch/case")
        r=self.invoke(); self.assertEqual(r.returncode,0,r.stdout+r.stderr); self.assertEqual(self.summary("case-2")["state"],"PASS")
        self.assertEqual(self.summary("case-2")["task_id_requested"],"case")

    def test_pool_cooldown_skips_opencode_but_codex_available(self):
        st={x:pools.fresh_pool() for x in pools.COOLDOWN}; st["tasks"]={}; st["opencode"].update(until=9999999999,cooled=True)
        (self.root/"pools.json").write_text(json.dumps(st))
        r=self.invoke(); self.assertEqual(r.returncode,0,r.stdout+r.stderr); self.assertNotIn("opencode",[x["tool"] for x in self.launched()])

    def test_preflight_pool_is_skipped_and_required_codex_unavailable_fails(self):
        st={x:pools.fresh_pool() for x in pools.COOLDOWN}; st["tasks"]={}; st["opencode"]["cooled"]=True
        (self.root/"pools.json").write_text(json.dumps(st)); r=self.invoke()
        self.assertEqual(r.returncode,0,r.stdout+r.stderr); self.assertEqual(self.summary()["pool_skips"]["opencode"],"PREFLIGHT")
        st["codex"]["cooled"]=True; (self.root/"pools.json").write_text(json.dumps(st)); r=self.invoke("high",task="codexdown")
        self.assertNotEqual(r.returncode,0); self.assertEqual(self.summary("codexdown")["state"],"ENVIRONMENT_ERROR")

    def test_existing_ledger_task_gets_suffix(self):
        st={x:pools.fresh_pool() for x in pools.COOLDOWN}; st["tasks"]={"case":{"pool":"codex","state":"RUNNING"}}
        (self.root/"pools.json").write_text(json.dumps(st))
        r=self.invoke("high"); self.assertEqual(r.returncode,0,r.stdout+r.stderr); self.assertEqual(self.summary("case-2")["state"],"PASS")

    def test_worktree_extra_slot_requires_flag(self):
        r=self.invoke(allow_extra=False); self.assertNotEqual(r.returncode,0)
        self.assertIn("must match <root>/<repo>/<agent>-work-N",self.summary()["error"])

    def test_trailer_required_unless_explicit_no_trailer(self):
        trailer=self.root/"trailer.txt"; trailer.write_text("Session-Attribution: commit",encoding="utf-8")
        pr_trailer=self.root/"pr-trailer.txt"; pr_trailer.write_text("Session-Attribution: PR",encoding="utf-8")
        r=self.invoke(extra=("--trailer-file",str(trailer),"--pr-trailer-file",str(pr_trailer))); self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn("Session-Attribution: commit",self.git(self.wt,"log","-1","--format=%B"))
        gh=next(x for x in self.launched() if x["tool"]=="gh" and x["args"][:2]==["pr","create"])
        self.assertTrue(gh["args"][gh["args"].index("--body")+1].endswith("Session-Attribution: PR"))
        self.assertEqual(sum(x["tool"]=="gh" and x["args"][:2]==["pr","create"] for x in self.launched()),1)

    def test_model_lookup_and_token_fixture_from_real_formats(self):
        sample = (pathlib.Path(__file__).resolve().parent / "test_fixtures" / "codex-models.json").read_text(encoding="utf-8")
        slugs = [model["slug"] for model in json.loads(sample)["models"] if model["slug"].endswith("-luna")]
        with mock.patch.dict(os.environ, {"DISPATCH_TEST_MODE": "0", "DISPATCH_CODEX_MODEL": "bad"}), mock.patch.object(dispatch, "run", return_value=type("P", (), {"returncode": 0, "stdout": "codex\n" + json.dumps({"models": [{"slug": x} for x in slugs]})})()):
            self.assertEqual(dispatch.codex_model(), "gpt-6-luna")
        usage = (pathlib.Path(__file__).resolve().parent / "test_fixtures" / "codex-stream.jsonl").read_text(encoding="utf-8")
        self.assertGreater(dispatch.token_count(usage), 0)

    def test_free_secret_scope_and_strict_names(self):
        (self.wt / "src").mkdir(); (self.wt / "src" / "inject_token.py").write_text("safe source", encoding="utf-8")
        self.assertFalse(dispatch.SENSITIVE.search("src/inject_token.py"))
        self.assertEqual(dispatch.secret_reason(self.wt, "prompt", "", allowed=["base.txt"]), "")
        (self.wt / ".env.local").write_text("safe", encoding="utf-8")
        self.assertTrue(dispatch.SENSITIVE.search(".env.local"))

    def ask(self, *extra, env=None, task="q1"):
        return subprocess.run([sys.executable, str(pathlib.Path(dispatch.__file__)), "ask", task, "--prompt", str(self.prompt), "--out-dir", str(self.out), *extra], capture_output=True, text=True, encoding="utf-8", env=env or self.env(), timeout=40)

    def data(self, text="plain facts\n", name="data.txt"):
        path = self.root / name; path.write_text(text, encoding="utf-8"); return str(path)

    def authors(self, task="case"):
        return [s["pool"] for s in self.summary(task)["stages"] if s.get("stage") == "author"]

    def test_ask_claude_without_files_gets_no_tools_and_is_not_told_to_seek_material(self):
        r = self.ask("--pool", "claude-haiku"); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        args = self.launched()[0]["args"]; self.assertEqual(args[args.index("--tools") + 1], "")
        folder = self.root / "f"; folder.mkdir()
        with mock.patch.object(dispatch, "execute", return_value=(0, 1, "")) as ex, mock.patch.object(dispatch, "tool_cmd", return_value=["claude"]):
            dispatch.ask_launch(mock.Mock(pool="claude-haiku", model=None, timeout=5), "write copy", [], folder, self.out)
        self.assertIn("No files are involved", ex.call_args.args[4]); self.assertNotIn("not found", ex.call_args.args[4])

    def test_ask_secret_and_sensitive_name_blocked_before_launch(self):
        r = self.ask("--pool", "opencode", "--read", self.data("password = hunter2\n"), env=self.env(OPENCODE_ASK="x"))
        self.assertEqual(json.loads(r.stdout)["state"], "BLOCKED")
        r = self.ask("--pool", "codex", "--read", self.data("A=1\n", ".env"), task="q2")
        self.assertEqual(json.loads(r.stdout)["state"], "BLOCKED"); self.assertEqual(self.launched(), [])

    def test_ask_link_in_folder_refused(self):
        folder = self.root / "data"; folder.mkdir(); (folder / "a.txt").write_text("x")
        subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(folder / "link"), str(self.wt)], check=True, capture_output=True)
        r = self.ask("--pool", "opencode", "--read", str(folder), env=self.env(OPENCODE_ASK="ok"))
        self.assertNotEqual(r.returncode, 0); self.assertIn("link", r.stdout); self.assertEqual(self.launched(), [])

    def test_ask_opencode_sees_only_copy_with_reader_agent(self):
        source = self.data()
        r = self.ask("--pool", "opencode", "--read", source, env=self.env(OPENCODE_ASK="\x1b[91manswer\x1b[0m"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        call = self.launched()[0]; self.assertIn("free-reader", call["args"])
        self.assertEqual(sorted(x.replace("\\", "/") for x in call["files"]), ["TASK.md", "input/data.txt", "opencode.json"])
        self.assertEqual((self.out / "q1" / "result.md").read_text(encoding="utf-8"), "answer")

    def test_ask_opencode_progress_lines_stay_out_of_the_answer(self):
        r = self.ask("--pool", "opencode", env=self.env(OPENCODE_ASK="> free-reader · deepseek\n\n→ Read TASK.md\n→ Read input/a.txt\nFirst line\n→ kept"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.out / "q1" / "result.md").read_text(encoding="utf-8"), "First line\n→ kept")
        r = self.ask("--pool", "opencode", env=self.env(OPENCODE_ASK="> free-reader · deepseek\n→ Read TASK.md"), task="q2")
        self.assertNotEqual(r.returncode, 0)

    def test_ask_codex_gets_material_on_stdin_with_a_limit(self):
        folder = self.root / "f"; folder.mkdir(); source = pathlib.Path(self.data("bridge facts\n"))
        args = mock.Mock(pool="codex", model="m", timeout=5)
        with mock.patch.object(dispatch, "execute", return_value=(0, 1, "")) as ex, mock.patch.object(dispatch, "tool_cmd", return_value=["codex"]), mock.patch.object(dispatch, "codex_model", return_value="m"):
            dispatch.ask_launch(args, "task", [(source, "data.txt")], folder, self.out)
            self.assertIn("bridge facts", ex.call_args.args[4]); self.assertFalse((folder / "input").exists())
            big = pathlib.Path(self.data("x" * (dispatch.ASK_STDIN_LIMIT + 1), "big.txt")); ex.reset_mock()
            with self.assertRaisesRegex(dispatch.DispatchError, "too large for codex"):
                dispatch.ask_launch(args, "task", [(big, "big.txt")], folder, self.out)
            ex.assert_not_called()

    def test_ask_opencode_rejects_unapproved_model(self):
        r = self.ask("--pool", "opencode", "--model", "opencode/paid", env=self.env(OPENCODE_ASK="x"))
        self.assertNotEqual(r.returncode, 0); self.assertEqual(self.launched(), [])

    def test_ask_codex_runs_read_only(self):
        r = self.ask("--pool", "codex", "--read", self.data(), env=self.env(REVIEW_FINAL="codex answer"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        call = [c for c in self.launched() if "exec" in c["args"]][0]; self.assertEqual(call["args"][call["args"].index("-s") + 1], "read-only")
        self.assertEqual((self.out / "q1" / "result.md").read_text(encoding="utf-8"), "codex answer")

    def test_ask_claude_haiku_read_only_and_stripped_env(self):
        r = self.ask("--pool", "claude-haiku", "--read", self.data())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        call = self.launched()[0]; args = call["args"]
        self.assertEqual(args[args.index("--model") + 1], "haiku"); self.assertEqual(args[args.index("--tools") + 1], "Read,Glob,Grep"); self.assertEqual(call["env"], [])
        self.assertEqual((self.out / "q1" / "result.md").read_text(encoding="utf-8"), "claude answer")

    def test_ask_breach_discards_answer_but_quoted_paths_are_fine(self):
        r = self.ask("--pool", "opencode", env=self.env(OPENCODE_ASK="Read C:/outside/private.txt failed"))
        self.assertEqual(json.loads(r.stdout)["state"], "BLOCKED"); self.assertFalse((self.out / "q1" / "result.md").exists())
        r = self.ask("--pool", "opencode", "--read", self.data("log said C:\\outside\\private.txt\n"), env=self.env(OPENCODE_ASK="Saw C:/outside/private.txt"), task="q2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_ask_retry_after_failure_but_never_overwrites_pass(self):
        r = self.ask("--pool", "opencode", env=self.env(OPENCODE_MODE="fail"))
        self.assertNotEqual(r.returncode, 0); self.assertIn("exited with code 2", r.stdout)
        r = self.ask("--pool", "opencode", env=self.env(OPENCODE_ASK="first")); self.assertEqual(r.returncode, 0, r.stdout)
        r = self.ask("--pool", "opencode", env=self.env(OPENCODE_ASK="second")); self.assertEqual(r.stdout.strip(), "ERROR: task output already exists")
        self.assertEqual((self.out / "q1" / "result.md").read_text(encoding="utf-8"), "first")

    def test_ask_unavailable_pool_is_environment_error(self):
        st = {x: pools.fresh_pool() for x in pools.COOLDOWN}; st["tasks"] = {}; st["opencode"]["until"] = 10 ** 12
        (self.root / "pools.json").write_text(json.dumps(st))
        r = self.ask("--pool", "opencode", env=self.env(OPENCODE_ASK="x"))
        self.assertEqual(json.loads(r.stdout)["state"], "ENVIRONMENT_ERROR"); self.assertEqual(self.launched(), [])

    def test_ask_repo_policy_blocks_free_pool_not_codex(self):
        (self.wt / "secretdata").mkdir(); path = self.wt / "secretdata" / "a.txt"; path.write_text("x")
        args = mock.Mock(read=[str(path)], pool="opencode")
        with mock.patch.object(dispatch, "repo_policy", return_value=({"free_pool_deny": ["secretdata"]}, "k")):
            with self.assertRaisesRegex(dispatch.DispatchError, "free_pool_deny"):
                dispatch.ask_read_set(args)
            args.pool = "codex"; self.assertEqual(len(dispatch.ask_read_set(args)), 1)
        with mock.patch.object(dispatch, "repo_policy", return_value=({"no_free_pools": True}, "k")):
            args.pool = "opencode"
            with self.assertRaisesRegex(dispatch.DispatchError, "no_free_pools"):
                dispatch.ask_read_set(args)

    def test_combo_opencode_author_claude_sonnet_reviewer(self):
        r = self.invoke(extra=["--author", "opencode", "--reviewer", "claude-sonnet"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertEqual(self.summary()["author"], "opencode"); self.assertEqual(self.authors(), ["opencode"])
        calls = self.launched(); self.assertEqual([c for c in calls if c["tool"] == "codex" and "exec" in c["args"]], []); self.assertNotIn("agy", [c["tool"] for c in calls])
        review = [c for c in calls if c["tool"] == "claude"]; self.assertEqual(len(review), 1); args = review[0]["args"]
        self.assertEqual(args[args.index("--model") + 1], "sonnet"); self.assertEqual(args[args.index("--tools") + 1], ""); self.assertEqual(review[0]["env"], [])

    def test_combo_claude_haiku_author_codex_reviewer(self):
        r = self.invoke(extra=["--author", "claude-haiku", "--reviewer", "codex"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertEqual(self.summary()["author"], "claude-haiku")
        args = [c for c in self.launched() if c["tool"] == "claude"][0]["args"]
        self.assertEqual(args[args.index("--model") + 1], "haiku"); self.assertEqual(args[args.index("--tools") + 1], "Read,Edit,Write,Glob,Grep"); self.assertNotIn("--allowedTools", args); self.assertNotIn("Bash", " ".join(args))
        self.assertEqual(len([c for c in self.launched() if c["tool"] == "codex" and "read-only" in c["args"]]), 1)
        self.assertIn("changed" if False else "claude change", self.git(self.wt, "show", "HEAD:base.txt"))

    def test_reviewer_none_is_marked_unreviewed_and_runs_no_review(self):
        r = self.invoke(extra=["--author", "opencode", "--reviewer", "none"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertEqual(self.summary()["state"], "PASS_UNREVIEWED")
        self.assertIn("no review: requested with --reviewer none", self.summary()["not_verified"])
        calls = self.launched(); self.assertEqual([c for c in calls if c["tool"] == "codex" and "exec" in c["args"]], []); self.assertEqual([c["tool"] for c in calls if c["tool"] == "opencode"], ["opencode"]); self.assertNotIn("claude", [c["tool"] for c in calls])

    def test_reviewer_named_failure_blocks_without_fallback(self):
        r = self.invoke(extra=["--author", "opencode", "--reviewer", "claude-sonnet"], env=self.env(STUB_REVIEW=json.dumps({"type": "result", "is_error": True, "result": "limit"})), task="c2")
        self.assertEqual(self.summary("c2")["state"], "BLOCKED")
        self.assertEqual([c for c in self.launched() if c["tool"] == "codex" and "read-only" in c["args"]], [])
        r = self.invoke(extra=["--author", "opencode", "--reviewer", "claude-sonnet"], env=self.env(STUB_REVIEW=json.dumps({"type": "result", "is_error": False, "structured_output": {"findings": [{"file": "x"}]}})), task="c3")
        self.assertEqual(self.summary("c3")["state"], "BLOCKED")

    def test_claude_reviewer_findings_trigger_fix_by_same_author(self):
        finding = json.dumps({"type": "result", "is_error": False, "structured_output": {"findings": [{"file": "base.txt", "line": 1, "severity": "high", "scenario": "bad"}]}})
        r = self.invoke(extra=["--author", "claude-haiku", "--reviewer", "claude-sonnet"], env=self.env(STUB_REVIEW=finding))
        self.assertNotEqual(r.returncode, 0); self.assertEqual(self.summary()["state"], "BLOCKED", self.summary().get("error"))
        stages = self.summary()["stages"]
        # The same finding comes back in the verification round, so the loop stops instead of running a third review.
        self.assertEqual(sum(s.get("stage") == "review" for s in stages), 2)
        self.assertEqual([s["pool"] for s in stages if s.get("stage") == "fix"], ["claude-haiku"])
        self.assertTrue(self.summary()["error"].startswith("review findings are not converging"))
        reviews = [c for c in self.launched() if c["tool"] == "claude" and "--json-schema" in c["args"]]
        self.assertTrue(all(pathlib.Path(c["cwd"]).resolve() != self.wt.resolve() for c in reviews))

    def finding(self, scenario, severity="medium", origin=None):
        item = {"file": "base.txt", "line": 1, "severity": severity, "scenario": scenario}
        if origin:
            item["origin"] = origin
        return item

    def review_env(self, *rounds, **extra):
        return self.env(REVIEW_SEQ=json.dumps([json.dumps({"findings": list(r)}) for r in rounds]), **extra)

    def review_prompts(self):
        return [c["prompt"] for c in self.launched() if c["tool"] == "codex" and "read-only" in c["args"]]

    def test_round_one_review_is_full_and_exhaustive(self):
        r = self.invoke("high")
        self.assertEqual(self.summary()["state"], "PASS", self.summary().get("error"))
        self.assertIn("only full review", self.review_prompts()[0])
        schema = json.loads((self.out / "case" / "review.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["findings"]["items"]["properties"]["severity"]["enum"], ["high", "medium", "low"])

    def test_second_round_only_verifies_prior_findings(self):
        r = self.invoke("high", env=self.review_env([self.finding("edge case")], []))
        self.assertEqual(self.summary()["state"], "PASS", self.summary().get("error"))
        second = self.review_prompts()[1]
        self.assertIn("verification round", second)
        self.assertIn("Previous findings:", second)
        self.assertIn("Fix diff", second)
        self.assertEqual([s["mode"] for s in self.summary()["stages"] if s.get("stage") == "review"], ["full", "verify"])

    def test_review_stops_when_findings_do_not_converge(self):
        r = self.invoke("high", env=self.review_env([self.finding("first")], [self.finding("second", origin="new")]))
        summary = self.summary()
        self.assertEqual(summary["state"], "BLOCKED")
        self.assertTrue(summary["error"].startswith("review findings are not converging"))
        self.assertEqual(sum(s.get("stage") == "review" for s in summary["stages"]), 2)
        self.assertEqual(sum(s.get("stage") == "fix" for s in summary["stages"]), 1)

    def test_review_converging_reaches_round_three(self):
        r = self.invoke("high", env=self.review_env([self.finding("first"), self.finding("second")], [self.finding("first", origin="unfixed")], []))
        self.assertEqual(self.summary()["state"], "PASS", self.summary().get("error"))
        self.assertEqual(sum(s.get("stage") == "review" for s in self.summary()["stages"]), 3)

    def test_review_shrinking_findings_reach_three_rounds(self):
        r = self.invoke("high", env=self.review_env([self.finding("a"), self.finding("b"), self.finding("c")], [self.finding("a", origin="unfixed"), self.finding("b", origin="unfixed")], [self.finding("a", origin="unfixed")]))
        self.assertEqual(self.summary()["state"], "BLOCKED")
        self.assertIn("review findings remain after three rounds", self.summary()["error"])

    def test_unknown_severity_is_rejected(self):
        bad = {"findings": [{"file": "base.txt", "line": 1, "severity": "critical", "scenario": "x"}]}
        r = self.invoke("high", env=self.env(REVIEW_FINAL=json.dumps(bad)))
        self.assertEqual(self.summary()["state"], "BLOCKED")

    def test_low_only_findings_in_verify_round_pass(self):
        r = self.invoke("high", env=self.review_env([self.finding("first")], [self.finding("minor", severity="low", origin="new")]))
        self.assertEqual(self.summary()["state"], "PASS", self.summary().get("error"))

    def test_codex_fix_resumes_author_session_when_enabled(self):
        r = self.invoke("high", env=self.review_env([self.finding("first")], [], DISPATCH_CODEX_RESUME="1"))
        self.assertEqual(self.summary()["state"], "PASS", self.summary().get("error"))
        resumes = [c for c in self.launched() if c["tool"] == "codex" and "resume" in c["args"]]
        self.assertTrue(resumes)
        self.assertIn("thread-1", resumes[0]["args"])
        self.assertNotIn("Edit base.txt as requested.", resumes[0]["prompt"])
        fixes = [s for s in self.summary()["stages"] if s.get("stage") == "fix"]
        self.assertTrue(fixes[0]["resumed"])

    def test_codex_fix_resume_failure_falls_back_to_fresh_call(self):
        r = self.invoke("high", env=self.review_env([self.finding("first")], [], DISPATCH_CODEX_RESUME="1", CODEX_RESUME_FAIL="1"))
        self.assertEqual(self.summary()["state"], "PASS", self.summary().get("error"))
        self.assertEqual([s["result"] for s in self.summary()["stages"] if s.get("stage") == "fix"], ["RESUME_FAILED", "OK"])

    def test_resume_is_off_by_default(self):
        r = self.invoke("high", env=self.review_env([self.finding("first")], []))
        self.assertEqual(self.summary()["state"], "PASS", self.summary().get("error"))
        self.assertFalse([c for c in self.launched() if c["tool"] == "codex" and "resume" in c["args"]])

    def test_final_max_refused_with_non_codex_reviewer(self):
        r = self.invoke(extra=["--author", "opencode", "--reviewer", "claude-sonnet", "--final-max"])
        self.assertNotEqual(r.returncode, 0); self.assertIn("--final-max", self.summary()["error"]); self.assertEqual(self.launched(), [])

    def test_author_plan_rules(self):
        self.assertEqual(dispatch.author_plan("low", [], None, {}), ["opencode", "codex"])
        self.assertEqual(dispatch.author_plan("high", [], None, {}), ["codex"])
        self.assertEqual(dispatch.author_plan("high", ["claude-haiku"], "codex", {}), ["claude-haiku"])
        for requested, reviewer in ((["opencode"], "codex"), (["claude-haiku", "opencode"], None), (["opencode"], None)):
            with self.assertRaisesRegex(dispatch.DispatchError, "no_free_pools"):
                dispatch.author_plan("high", requested, reviewer, {"no_free_pools": True})
        self.assertEqual(dispatch.author_plan("high", ["claude-haiku"], "claude-sonnet", {"no_free_pools": True}), ["claude-haiku"])

    def test_author_flag_uses_only_named_author_and_no_fallback(self):
        r = self.invoke(extra=["--author", "opencode"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertEqual(self.summary()["author"], "opencode"); self.assertEqual(self.authors(), ["opencode"])
        r = self.invoke(extra=["--author", "opencode"], env=self.env(OPENCODE_MODE="fail"), task="c2")
        self.assertNotEqual(r.returncode, 0); self.assertEqual(self.summary("c2")["author"], None); self.assertEqual(self.authors("c2"), ["opencode"])

    def test_author_flag_unavailable_pool_does_not_fall_back(self):
        st = {x: pools.fresh_pool() for x in pools.COOLDOWN}; st["tasks"] = {}; st["opencode"]["until"] = 10 ** 12
        (self.root / "pools.json").write_text(json.dumps(st))
        r = self.invoke(extra=["--author", "opencode"]); self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.summary()["state"], "ENVIRONMENT_ERROR"); self.assertEqual([c for c in self.launched() if "exec" in c["args"]], [])

    def test_worktree_slot_accepts_any_worker_and_either_repo_spelling(self):
        self.git(self.primary, "remote", "set-url", "origin", "https://github.com/x/li-lab.git")
        root = self.root / "slots"; ok = root / "primary" / "agy-work-1"; ok2 = root / "li_lab" / "opencode-work-2"; ok3 = root / "li-lab" / "claude-work-1"; bad = root / "other" / "agy-work-1"; bad2 = root / "li-lab" / "tang-work-1"
        for path in (ok, ok2, ok3, bad, bad2):
            path.parent.mkdir(parents=True, exist_ok=True); self.git(self.primary, "worktree", "add", "--detach", str(path), "HEAD")
        for good in (ok, ok2, ok3):
            self.assertTrue(dispatch.worktree_slot_ok(good.resolve(), root.resolve()), good)
        for wrong in (bad, bad2):
            self.assertFalse(dispatch.worktree_slot_ok(wrong.resolve(), root.resolve()), wrong)

    def test_preflight_failure_does_not_burn_task_id(self):
        r = self.invoke(allow_extra=False); self.assertNotEqual(r.returncode, 0)
        self.assertIn("must match", r.stdout); self.assertTrue(self.summary()["preflight_only"])
        r = self.invoke(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("preflight_only", self.summary())
        r = self.invoke(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.summary("case-2")["task_id_requested"], "case")

    def test_early_failure_keeps_earlier_run_summary(self):
        r = self.invoke(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        before = (self.out / "case" / "summary.json").read_bytes() if (self.out / "case" / "summary.json").exists() else None
        self.assertIsNotNone(before)
        r = self.invoke(allow_extra=False); self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.out / "case" / "summary.json").read_bytes(), before)
        last = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertIsNone(last["summary"]); self.assertEqual(last["task_id"], "case")

    def test_failure_after_start_still_keeps_task_id(self):
        r = self.invoke(env=self.env(OPENCODE_MODE="fail", CODEX_MODE="fail"), extra=["--author", "opencode", "--author", "codex"]); self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("preflight_only", self.summary())
        r = self.invoke(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.summary("case-2")["task_id_requested"], "case")

    def test_agy_is_disabled_on_every_path(self):
        # Antigravity terms section 6: an agent or script driving agy risks an account ban (2026-11-07).
        self.assertNotIn("agy", dispatch.AUTHORS); self.assertNotIn("agy", dispatch.REVIEWERS); self.assertNotIn("agy", dispatch.FREE_POOLS)
        with mock.patch.dict(os.environ, {"DISPATCH_AGY": str(self.agy)}):
            for call in (lambda: dispatch.resolve_tool("agy", "DISPATCH_AGY"), lambda: dispatch.tool_cmd("agy", "DISPATCH_AGY", "-p", "x"),
                         lambda: dispatch.author("agy", type("Args", (), {"wt": self.wt}), "x", self.root / "t", self.out, "a", {})):
                with self.assertRaisesRegex(dispatch.DispatchError, "agy is disabled"):
                    call()
        with mock.patch.dict(os.environ, {"DISPATCH_CODEX": str(self.agy)}):  # another tool's override pointed at agy
            with self.assertRaisesRegex(dispatch.DispatchError, "agy is disabled"):
                dispatch.resolve_tool("codex", "DISPATCH_CODEX")
        for extra in (["--author", "agy"], ["--reviewer", "agy"], ["--model", "agy=gemini-3.8-flash-medium"]):
            r = self.invoke(extra=extra); self.assertEqual(r.returncode, 2, extra)
        r = self.ask("--pool", "agy"); self.assertEqual(r.returncode, 2)
        self.assertEqual([c for c in self.launched() if c["tool"] == "agy"], [])
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("not supported", skill)

    def test_unpublished_content_policy_is_documented(self):
        skill=(ROOT/"SKILL.md").read_text(encoding="utf-8"); review=(ROOT/"references/review.md").read_text(encoding="utf-8")
        self.assertIn("unpublished",skill.lower()); self.assertIn("no_free_pools",skill); self.assertIn("Owner-accepted risk (2026-11-05)",review)

    def pr_body(self):
        gh = next(x for x in self.launched() if x["tool"] == "gh" and x["args"][:2] == ["pr", "create"])
        return gh["args"][gh["args"].index("--body") + 1]

    def two_slots(self):
        """Two claude slots of the primary checkout, under the same worktrees root the tests use."""
        slots = [self.wt.parent / "primary" / "claude-work-1", self.wt.parent / "primary" / "claude-work-2"]
        for slot in slots:
            slot.parent.mkdir(exist_ok=True)
            self.git(self.primary, "worktree", "add", "--detach", str(slot), "origin/trunk")
        return slots

    def test_body_file_is_optional_and_defaults_to_task_and_prompt(self):
        r = self.invoke(body=False); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Dispatched task `case`", self.pr_body()); self.assertIn("Edit base.txt as requested.", self.pr_body())

    def test_trailers_default_from_repos_json(self):
        repos = self.root / "repos-default.json"
        repos.write_text(json.dumps({"*": {"trailer": "Session-Attribution: commit-default", "pr_trailer": "Session-Attribution: PR-default"}}), encoding="utf-8")
        r = self.invoke(default_trailers=True, env=self.env(DISPATCH_REPOS_FILE=str(repos))); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Session-Attribution: commit-default", self.git(self.wt, "log", "-1", "--format=%B"))
        self.assertTrue(self.pr_body().endswith("Session-Attribution: PR-default"))

    def test_missing_trailers_without_defaults_is_refused(self):
        repos = self.root / "repos-empty.json"; repos.write_text("{}", encoding="utf-8")
        r = self.invoke(default_trailers=True, env=self.env(DISPATCH_REPOS_FILE=str(repos))); self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.summary()["error"], "provide --trailer-file and --pr-trailer-file, set trailer and pr_trailer in repos.json, or explicitly pass --no-trailer")
        self.assertEqual(self.launched(), [])

    def test_repo_entry_overrides_star_defaults(self):
        repos = self.root / "repos-override.json"
        repos.write_text(json.dumps({"*": {"trailer": "T", "pr_trailer": "P", "no_pr": True}, "github.com/x/y": {"pr_trailer": "R"}}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"DISPATCH_REPOS_FILE": str(repos)}):
            with mock.patch.object(dispatch, "remote_url", return_value="https://github.com/X/y.git"):
                self.assertEqual(dispatch.repo_policy(self.wt), ({"trailer": "T", "pr_trailer": "R", "no_pr": True}, "github.com/x/y"))
            with mock.patch.object(dispatch, "remote_url", return_value="https://github.com/other/repo.git"):
                self.assertEqual(dispatch.repo_policy(self.wt), ({"trailer": "T", "pr_trailer": "P", "no_pr": True}, "github.com/other/repo"))

    def test_wt_auto_picks_free_claude_slot(self):
        slots = self.two_slots()
        env = self.env(); env["STUB_WT"] = env["DISPATCH_STUB_WT"] = str(slots[0])
        r = self.invoke(wt="auto", extra=("--repo", str(self.primary)), allow_extra=False, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.summary()["slot"].endswith("claude-work-1"))

    def test_wt_auto_skips_dirty_and_locked_slots(self):
        slots = self.two_slots()
        env = self.env(); env["STUB_WT"] = env["DISPATCH_STUB_WT"] = str(slots[1])
        (slots[0] / "untracked.txt").write_text("dirty", encoding="utf-8")
        r = self.invoke(wt="auto", extra=("--repo", str(self.primary)), allow_extra=False, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.summary()["slot"].endswith("claude-work-2"))
        self.assertIn("claude-work-1", self.summary()["slot_skipped"])
        # second case: slot 2 is held by another run and slot 1 is still dirty
        with mock.patch.dict(os.environ, {"DISPATCH_TMP_ROOT": str(self.tmproot)}):
            self.assertTrue(dispatch.acquire_slot(slots[1], "other"))
        r = self.invoke(wt="auto", extra=("--repo", str(self.primary)), allow_extra=False, env=env, task="case2"); self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.summary("case2")["state"], "ENVIRONMENT_ERROR")
        self.assertIn("no free slot", self.summary("case2")["error"]); self.assertIn("in use by task other", self.summary("case2")["error"])

    def test_explicit_slot_in_use_is_refused_and_lock_is_released_after_run(self):
        with mock.patch.dict(os.environ, {"DISPATCH_TMP_ROOT": str(self.tmproot)}):
            self.assertTrue(dispatch.acquire_slot(self.wt, "other"))
            lock = dispatch.slot_lock_path(self.wt)
        self.assertTrue(lock.exists())
        r = self.invoke(); self.assertNotEqual(r.returncode, 0); self.assertIn("in use by task other", r.stdout)
        self.assertEqual(self.launched(), [])
        with mock.patch.dict(os.environ, {"DISPATCH_TMP_ROOT": str(self.tmproot)}):
            dispatch.release_slot(self.wt)
        r = self.invoke(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(lock.exists())

    def test_stale_slot_lock_is_taken_over(self):
        with mock.patch.dict(os.environ, {"DISPATCH_TMP_ROOT": str(self.tmproot)}):
            self.assertTrue(dispatch.acquire_slot(self.wt, "dead"))
            lock = dispatch.slot_lock_path(self.wt)
        old = time.time() - 7 * 3600; os.utime(lock, (old, old))
        r = self.invoke(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(lock.exists())

    def test_reused_task_id_gets_suffix(self):
        r = self.invoke(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.invoke(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1])["task_id"], "case-2")
        self.assertTrue((self.out / "case-2").is_dir()); self.assertEqual(self.git(self.wt, "branch", "--show-current"), "dispatch/case-2")
        self.assertEqual(self.summary("case-2")["task_id_requested"], "case")

    def test_leftover_temp_folder_does_not_block_the_run(self):
        (self.tmproot / "case").mkdir(parents=True)
        r = self.invoke(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.summary("case-2")["task_id"], "case-2"); self.assertTrue((self.tmproot / "case").is_dir())


ROOT = pathlib.Path(__file__).resolve().parent
if __name__ == "__main__":
    unittest.main(verbosity=2)
