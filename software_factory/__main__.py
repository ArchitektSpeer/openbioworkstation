"""python -m software_factory --help"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .engine import Factory, FactoryError, write_json


def doctor(root):
    report = {}
    commands = {
        "codex": [["codex", "--version"], ["codex", "login", "status"]],
        "claude": [["claude", "--version"], ["claude", "auth", "status"]],
        "qodercn": [["qodercn", "--version"], ["qodercn", "--list-models"]],
        "opencode": [["opencode", "--version"], ["opencode", "models"]],
        "gh": [["gh", "--version"]],
    }
    for provider, checks in commands.items():
        info = {"installed": shutil.which(provider) is not None, "checks": []}
        if info["installed"]:
            for argv in checks:
                try:
                    p = subprocess.run(argv, capture_output=True, text=True, timeout=25)
                    stdout = p.stdout.strip()
                    if (
                        provider == "claude"
                        and argv[1:] == ["auth", "status"]
                        and p.returncode == 0
                    ):
                        raw = json.loads(stdout)
                        stdout = json.dumps(
                            {
                                key: raw.get(key)
                                for key in (
                                    "loggedIn",
                                    "authMethod",
                                    "apiProvider",
                                    "subscriptionType",
                                )
                            }
                        )
                    info["checks"].append(
                        {
                            "argv": argv,
                            "returncode": p.returncode,
                            "stdout": stdout[-16000:],
                            "stderr": p.stderr[-2000:],
                        }
                    )
                except (subprocess.TimeoutExpired, ValueError) as exc:
                    info["checks"].append({"argv": argv, "error": type(exc).__name__})
        report[provider] = info
    write_json(root / "discovery.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Local multi-model factory; never deploys or merges"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "config/factory-routes.yaml",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "doctor",
        help="Inspect installed CLI versions, auth status and model catalogs without model calls",
    )
    create = commands.add_parser("create")
    create.add_argument("task_file", type=Path)
    create.add_argument(
        "--issue",
        help="GitHub issue URL or owner/repo#number; acceptance and checks still come from the trusted task file",
    )
    run = commands.add_parser("run")
    run.add_argument("task_id")
    run.add_argument("--recover", action="store_true")
    abandon = commands.add_parser(
        "abandon-call",
        help="Explicitly acknowledge an inspected dead call; never assumes it succeeded",
    )
    abandon.add_argument("task_id")
    abandon.add_argument("call_id", type=int)
    status = commands.add_parser("status")
    status.add_argument("task_id")
    publish = commands.add_parser(
        "publish", help="Explicitly push reviewed commit and create an idempotent draft PR"
    )
    publish.add_argument("task_id")
    args = parser.parse_args()
    root = (args.state_dir or args.repo / ".factory").resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "doctor":
            result = doctor(root)
        else:
            factory = Factory(args.repo, root, args.policy)
            if args.command == "create":
                task = json.loads(args.task_file.read_text())
                if args.issue:
                    reference = args.issue
                    command = ["gh", "issue", "view", reference, "--json", "title,body,url"]
                    if "#" in reference and not reference.startswith("https://"):
                        repository, number = reference.rsplit("#", 1)
                        command = [
                            "gh",
                            "issue",
                            "view",
                            number,
                            "--repo",
                            repository,
                            "--json",
                            "title,body,url",
                        ]
                    source = json.loads(subprocess.check_output(command, cwd=args.repo, text=True))
                    task["title"], task["request"], task["issue_url"] = (
                        source["title"],
                        source["body"],
                        source["url"],
                    )
                result = factory.create(task)
            elif args.command == "run":
                result = factory.run(args.task_id, recover=args.recover)
            elif args.command == "abandon-call":
                result = factory.abandon_call(args.task_id, args.call_id)
            elif args.command == "publish":
                result = factory.publish(args.task_id)
            else:
                result = {
                    "task": factory.store.task(args.task_id),
                    "calls": factory.store.calls(args.task_id),
                }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if isinstance(result, dict) and result.get("state") in (
            "needs_attention",
            "approval_required",
        ):
            return 2
        return 0
    except (FactoryError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Factory stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
