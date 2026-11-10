"""Pool availability and dispatch tracker for multi-agent-dispatch.

Usage:
  python pools.py status                 pools + open tasks (read-only)
  python pools.py wt <agent> [repo]      find a FREE fixed pool worktree <agent>-work-N (read-only); run BEFORE any git worktree add
  python pools.py ok <pool> [tokens]     successful run; clears an expired cooldown (= pre-flight passed)
  python pools.py fail <pool> [text...]  failure; quota/429/rate text -> COOLDOWN, auth/outage text -> DOWN
  python pools.py reset <pool>           clear COOLDOWN/DOWN after a passing pre-flight
  python pools.py start <task-id> <pool> <goal...>   register a launched job (id must be new)
  python pools.py done <task-id> <state> [note...]   PASS/FAIL/TIMEOUT/BLOCKED/... closes it;
                                                     WAITING_QUOTA/NEEDS_REVIEW keep it open
Pools: opencode (30m cooldown), codex (5h). Claude is not tracked.
State: pools.json next to this file. agy is refused (Antigravity terms ban risk).
"""
import json, os, pathlib, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get('DISPATCH_POOLS_STATE', os.path.join(HERE, 'pools.json'))
LOCK = STATE + '.lock'
COOLDOWN = {'opencode': 30 * 60, 'codex': 5 * 3600}
QUOTA_RE = re.compile(r'quota|429|rate.?limit|usage.?limit|exhaust|too many requests', re.I)
DOWN_RE = re.compile(r'auth|login|unauthori[sz]ed|401|403|outage|unavailable|503|upgrade', re.I)
SECRET_RE = re.compile(r'(token|key|secret|password|bearer)\S*\s*[:=]?\s*\S+', re.I)
VALID_STATES = {'PASS','PASS_UNREVIEWED','NEEDS_SCOPE_DECISION','FAIL','BLOCKED','TIMEOUT','ENVIRONMENT_ERROR','CANCELLED','WAITING_QUOTA','NEEDS_REVIEW','VERIFYING','RUNNING'}
OPEN_STATES = {'', 'RUNNING', 'PENDING', 'WAITING_QUOTA', 'NEEDS_REVIEW', 'VERIFYING'}
FAR = 10 ** 12  # DOWN: no expiry


class StateError(Exception):
    pass


def fresh_pool():
    return {'until': 0, 'cooled': False, 'runs': 0, 'tokens': 0, 'fails': 0, 'last': ''}


def load():
    if not os.path.exists(STATE):
        s = {}
    else:
        try:
            with open(STATE, encoding='utf-8') as f:
                s = json.load(f)
        except Exception as ex:
            raise StateError('pools.json unreadable (%s); fix or move it, nothing was changed' % ex)
        if not isinstance(s, dict):
            raise StateError('pools.json is not an object; nothing was changed')
    for p in COOLDOWN:
        v = s.setdefault(p, fresh_pool())
        if not isinstance(v, dict):
            raise StateError('pool %s entry is malformed' % p)
        for k, d in fresh_pool().items():
            v.setdefault(k, d)
    if not isinstance(s.setdefault('tasks', {}), dict):
        raise StateError('tasks entry is malformed')
    return s


def save(s):
    tmp = STATE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, STATE)  # atomic


def lock():
    for _ in range(100):
        try:
            return os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.time() - os.path.getmtime(LOCK) > 60:  # stale lock
                os.remove(LOCK)
            time.sleep(0.1)
    raise StateError('could not get pools.json.lock')


def pool_state(v, now):
    if v['until'] >= FAR:
        return 'DOWN'
    if v['until'] > now:
        return 'COOLDOWN'
    if v['cooled']:
        return 'PREFLIGHT'
    return 'AVAILABLE'


def status(s):
    now = time.time()
    for p in COOLDOWN:
        v = s[p]
        st = pool_state(v, now)
        if st == 'COOLDOWN':
            print('%s: COOLDOWN %d min left (until %s) - %s' % (
                p, (v['until'] - now) / 60, time.strftime('%H:%M', time.localtime(v['until'])), v['last']))
        elif st in ('DOWN', 'PREFLIGHT'):
            print('%s: %s - %s' % (p, st, v['last'] or 'run a pre-flight, then ok/reset'))
        else:
            print('%s: AVAILABLE (runs %d, tokens %d, fails %d)' % (p, v['runs'], v['tokens'], v['fails']))
    open_t = {k: t for k, t in s['tasks'].items() if t.get('state', '') in OPEN_STATES or 'PENDING' in str(t.get('state',''))}
    print('OPEN TASKS: %d' % len(open_t))
    for k, t in open_t.items():
        print('  %s [%s] %s %d min - %s' % (k, t['pool'], t.get('state') or 'RUNNING', (now - t['start']) / 60, t['goal']))


def _run(cmd, timeout, cwd, input_text=None):
    """Run with a hard timeout that kills the whole process tree (a hung child must never hold the lock)."""
    import subprocess
    env = dict(os.environ, PYTHONUTF8='1')
    pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                          errors='replace', env=env, cwd=cwd,
                          stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL)
    try:
        out, _ = pr.communicate(input=input_text, timeout=timeout)
        return pr.returncode, out or ''
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(pr.pid)], capture_output=True)
        try:
            pr.communicate(timeout=5)
        except Exception:
            pass
        return None, 'timeout'


def live_probe(pool):
    """Cheap real call. Returns (ok, text). Live result overrides any stored cooldown."""
    tmp = str(pathlib.Path.home() / 'worktrees' / '_tmp')
    if pool == 'codex':
        from dispatch import resolve_tool
        command = resolve_tool('codex', 'DISPATCH_CODEX')
        from dispatch import codex_model
        rc, out = _run(command + ['exec', '-s', 'read-only', '-m', codex_model(), '--skip-git-repo-check', '-C', tmp,
                                  '-c', 'model_reasoning_effort=medium', '-'], 120, tmp,
                       input_text='Reply with exactly: OK')
        return (rc == 0 and 'usage limit' not in out), out[-200:]
    if pool == 'opencode':
        from dispatch import resolve_tool
        command = resolve_tool('opencode', 'DISPATCH_OPENCODE')
        rc, out = _run(command + ['run', '--model', 'opencode/deepseek-v4.1-flash-free',
                                  'Reply with exactly: OK'], 45, tmp)
        return (rc == 0 and 'OK' in out and 'limit' not in out.lower()), out[-200:]
    return False, 'unknown pool'


def probe(names):
    s = load()
    unknown = [p for p in names if p not in COOLDOWN]
    if unknown:
        print('unknown pool %s%s' % (','.join(unknown), ' (agy is disabled: Antigravity terms ban risk)' if 'agy' in unknown else ''))
        return 2
    for p in names:
        ok, text = live_probe(p)
        v = s[p]
        if ok:
            v['until'], v['cooled'], v['last'] = 0, False, ''
        else:
            text = SECRET_RE.sub('[redacted]', text.replace(chr(10), ' '))
            v['last'] = ('live probe failed: ' + text)[:80]
            if QUOTA_RE.search(text) or 'usage limit' in text.lower() or text == 'timeout':
                v['until'], v['cooled'] = time.time() + COOLDOWN[p], True
            else:
                v['until'], v['cooled'] = FAR, True
    save(s)
    status(s)
    return 0


WT_ROOT = str(pathlib.Path.home() / 'worktrees')


def _git(repo, *args):
    import subprocess
    r = subprocess.run(['git', '-C', repo] + list(args), capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.returncode, r.stdout.strip()


def worktree_pick(agent, repo):
    """Read-only: find a FREE fixed pool worktree <WT_ROOT>/<repo-name>/<agent>-work-N.

    FREE = registered, detached HEAD, clean status. Prints the path to use, or the
    exact command to create the next pool slot (never one folder per task).
    """
    rc, url = _git(repo, 'remote', 'get-url', 'origin')
    name = os.path.basename(url.rstrip('/')).removesuffix('.git') if rc == 0 and url else os.path.basename(os.path.abspath(repo))
    base = '%s/%s' % (WT_ROOT, name)
    rc, out = _git(repo, 'worktree', 'list', '--porcelain')
    if rc != 0:
        print('ERROR: not a git repo:', repo)
        return 3
    entries, cur = [], {}
    for line in out.splitlines() + ['']:
        if not line.strip():
            if cur:
                entries.append(cur)
            cur = {}
        elif ' ' in line:
            k, v = line.split(' ', 1)
            cur[k] = v
        else:
            cur[line] = True
    prefix = '%s/%s-work-' % (base, agent)
    slots = {}
    for e in entries:
        path = e.get('worktree', '').replace(chr(92), '/')
        if path.startswith(prefix) and path[len(prefix):].isdigit():
            slots[int(path[len(prefix):])] = (path, bool(e.get('detached')), e.get('branch', ''))
    print('repo=%s pool=%s-work-N under %s' % (name, agent, base))
    free = None
    for n in sorted(slots):
        path, detached, branch = slots[n]
        rc, st = _git(path, 'status', '--porcelain')
        dirty = bool(st)
        state = 'FREE' if (detached and not dirty) else 'BUSY (%s)' % ('on branch ' + branch if branch else 'dirty')
        print('  %s %s' % (state, path))
        if state == 'FREE' and free is None:
            free = path
    if free:
        print('USE: %s' % free)
        print('  prep: git fetch; resolve origin/HEAD to its default-branch ref; checkout it detached, then create your task branch from it')
        print('  after merge: return to the resolved default-branch ref; delete the branch; keep the folder (do NOT remove the worktree)')
        return 0
    nxt = (max(slots) + 1) if slots else 1
    print('NONE_FREE. Create pool slot (max 2 per agent; report to the Owner before a 3rd):')
    print('  resolve origin/HEAD to its default-branch ref, then: git worktree add --detach "%s%d" <default-branch-ref>' % (prefix, nxt))
    return 1


def main(a):
    need = {'probe': 1, 'wt': 2, 'status': 1, 'ok': 2, 'fail': 2, 'reset': 2, 'start': 4, 'done': 3, 'stats': 1}
    if not a or a[0] not in need or len(a) < need[a[0]]:
        print(__doc__)
        return 2
    cmd = a[0]
    if cmd == 'wt':
        return worktree_pick(a[1], a[2] if len(a) > 2 else os.getcwd())
    if cmd == 'probe':
        fd = lock()
        try:
            return probe(a[1:] or ['opencode'])
        finally:
            os.close(fd)
            os.remove(LOCK)
    if cmd == 'status':
        status(load())
        return 0
    if cmd == 'stats':
        s=load(); now=time.time()
        for p in COOLDOWN:
            ts=[t for t in s['tasks'].values() if t.get('pool')==p]
            passed=sum(t.get('state')=='PASS' for t in ts); failed=sum(t.get('state') in {'FAIL','TIMEOUT','ENVIRONMENT_ERROR','CANCELLED','BLOCKED','NEEDS_SCOPE_DECISION'} for t in ts)
            mins=[(t.get('end',now)-t.get('start',now))/60 for t in ts if t.get('end')]
            import statistics
            med=statistics.median(mins) if mins else 0
            print('%s tasks=%d PASS=%d failed=%d failure_rate=%.0f%% tokens=%d median_minutes=%.1f' % (p,len(ts),passed,failed,100*failed/max(1,passed+failed),s[p]['tokens'],med))
        return 0
    fd = lock()
    try:
        s = load()
        if cmd == 'start':
            tid, p = a[1], a[2]
            if p not in COOLDOWN and p != 'claude':
                print('unknown pool', p)
                return 2
            if tid in s['tasks']:
                print('task id already used:', tid)
                return 2
            s['tasks'][tid] = {'pool': p, 'goal': ' '.join(a[3:])[:100], 'start': time.time(), 'state': ''}
        elif cmd == 'done':
            import argparse
            t = s['tasks'].get(a[1])
            if not t:
                print('unknown task', a[1])
                return 2
            if t.get('state', '') not in OPEN_STATES:
                print('task already closed as', t['state'])
                return 2
            state=a[2].upper()
            if state not in VALID_STATES:
                print('unknown state', state); return 2
            rest=a[3:]; tokens=0
            if '--tokens' in rest:
                i=rest.index('--tokens')
                try: tokens=int(rest[i+1])
                except (ValueError,IndexError): print('invalid --tokens'); return 2
                rest=rest[:i]+rest[i+2:]
            t['state'] = state
            t['tokens'] = tokens
            t['note'] = ' '.join(rest)[:200]
            t['end'] = time.time()
            if t.get('pool') in COOLDOWN: s[t['pool']]['tokens'] += tokens
        else:
            p = a[1]
            if p not in COOLDOWN:
                print('unknown pool', p)
                return 2
            v = s[p]
            if cmd == 'ok':
                v['runs'] += 1
                v['tokens'] += int(a[2]) if len(a) > 2 and a[2].isdigit() else 0
                if pool_state(v, time.time()) == 'PREFLIGHT':
                    v['cooled'] = False
                    v['last'] = ''
            elif cmd == 'fail':
                text = SECRET_RE.sub('[redacted]', ' '.join(a[2:]))
                v['fails'] += 1
                v['last'] = text[:80]
                if QUOTA_RE.search(text):
                    v['until'], v['cooled'] = time.time() + COOLDOWN[p], True
                elif DOWN_RE.search(text):
                    v['until'], v['cooled'] = FAR, True
            elif cmd == 'reset':
                v['until'], v['cooled'], v['last'] = 0, False, ''
        save(s)
        status(s)
        return 0
    finally:
        os.close(fd)
        os.remove(LOCK)


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except StateError as ex:
        print('ERROR:', ex)
        sys.exit(3)
