"""Summarize Claude Code session JSONL usage and actual tool calls."""
import argparse
import glob
import json
import pathlib
import statistics
import time


def is_tool_use(block):
    return isinstance(block, dict) and block.get("type") == "tool_use"


def tool_name(block):
    return str(block.get("name", "")).lower()


def summarize(filename):
    try:
        rows = [json.loads(line) for line in pathlib.Path(filename).read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return None
    unique = {}
    for row in rows:
        message = row.get("message", {})
        if message.get("role") == "assistant" and message.get("id"):
            unique[message["id"]] = row
    usage = [row.get("message", {}).get("usage", {}) or {} for row in unique.values()]
    contexts = [u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0) for u in usage]
    calls = {"Monitor": 0, "pools.py": 0, "dispatch.py": 0}
    seen_calls = set()
    for row in unique.values():
        message = row.get("message", {})
        for block in message.get("content", []):
            if not is_tool_use(block):
                continue
            call_id = block.get("id") or (message.get("id"), json.dumps(block, sort_keys=True))
            if call_id in seen_calls:
                continue
            seen_calls.add(call_id)
            name = tool_name(block)
            args = json.dumps(block.get("input", {}), ensure_ascii=False).lower()
            if name == "monitor":
                calls["Monitor"] += 1
            if "pools.py" in args:
                calls["pools.py"] += 1
            if "dispatch.py" in args:
                calls["dispatch.py"] += 1
    compactions = sum(
        1 for row in rows
        if row.get("type") in {"compact_boundary", "compaction"}
        or row.get("subtype") in {"compact_boundary", "compaction"}
    )
    multi = any(
        block.get("type") == "tool_use"
        and str(block.get("name", "")).lower() in {"skill", "read_skill"}
        and "multi-agent-dispatch" in json.dumps(block.get("input", {})).lower()
        for row in unique.values()
        for block in row.get("message", {}).get("content", [])
    )
    return {
        "turns": len(unique),
        "cache_read": sum(u.get("cache_read_input_tokens", 0) for u in usage),
        "cache_create": sum(u.get("cache_creation_input_tokens", 0) for u in usage),
        "output": sum(u.get("output_tokens", 0) for u in usage),
        "median_context": int(statistics.median(contexts)) if contexts else 0,
        "compactions": compactions,
        **calls,
        "multi_agent_dispatch": multi,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--since-days", type=int)
    parser.add_argument("--session")
    parser.add_argument("--projects-dir", default=str(pathlib.Path.home() / ".claude" / "projects"))
    args = parser.parse_args(argv)
    cutoff = time.time() - args.since_days * 86400 if args.since_days else 0
    for filename in glob.glob(str(pathlib.Path(args.projects_dir) / "*" / "*.jsonl")):
        path = pathlib.Path(filename)
        if args.session and not path.stem.startswith(args.session):
            continue
        if cutoff and path.stat().st_mtime < cutoff:
            continue
        values = summarize(filename)
        if values is None:
            continue
        print(path.stem + " " + " ".join("%s=%s" % (key, value) for key, value in values.items()))


if __name__ == "__main__":
    main()
