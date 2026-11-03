"""Deterministic scheduler tests; fake model responses are not live-model evidence."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from software_factory.engine import Factory, FactoryError, git

POLICY = Path(__file__).resolve().parents[1] / "config/factory-routes.yaml"


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("test repository\n")
    (repo / ".gitignore").write_text("__pycache__/\n")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "initial")
    policy = yaml.safe_load(POLICY.read_text())
    policy["call_timeout"] = 5
    policy["max_calls_per_task"] = 20
    policy["max_calls_per_day"] = 100
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(policy))
    task = {
        "id": "example",
        "title": "Add feature",
        "request": "Add VALUE = 7",
        "acceptance": "VALUE must equal seven",
        "route": "tests_docs_lint",
        "risk": "low",
        "allowed_files": ["feature.py", "optional.py"],
        "checks": [["{python}", "-c", "from feature import VALUE; assert VALUE == 7"]],
    }
    return repo, tmp_path / "state", path, task


class Models:
    calls = []
    implementation = "VALUE = 7\n"
    failing = {}

    def __init__(self, provider, model):
        self.provider, self.model = provider, model

    def run(self, prompt, worktree, timeout, log_dir, write=False):
        self.calls.append((self.provider, self.model, write))
        status = self.failing.get(self.model, "success")
        if write:
            (Path(worktree) / "feature.py").write_text(self.implementation)
            text = "Implemented"
        elif "Current stage: plan" in prompt:
            text = json.dumps(
                {
                    "summary": "Plan",
                    "risk": "low",
                    "route": "tests_docs_lint",
                    "tasks": [{"id": "one", "depends_on": [], "acceptance": "VALUE is seven"}],
                }
            )
        elif "Current stage: review" in prompt:
            text = json.dumps({"approved": True, "findings": []})
        else:
            text = "PRD: VALUE must equal seven."
        return SimpleNamespace(
            status=status,
            text=text,
            cost_usd=None,
            retry_after=1,
            duration=0.01,
            version="test-double",
            actual_model=self.model,
        )


@pytest.fixture(autouse=True)
def reset():
    Models.calls = []
    Models.implementation = "VALUE = 7\n"
    Models.failing = {}


def test_serial_delivery_and_resume_without_replaying(setup):
    repo, root, policy, task = setup
    f = Factory(repo, root, policy, Models)
    f.create(task)
    assert f.run(task["id"])["state"] == "ready_for_pr"
    assert len(Models.calls) == 4
    assert Models.calls[2][1] != Models.calls[3][1]
    assert f.run(task["id"])["state"] == "ready_for_pr"
    assert len(Models.calls) == 4
    assert not (repo / "feature.py").exists()
    assert (root / "tasks/example/review.json").exists()


def test_repair_limit_survives_resume(setup):
    repo, root, policy, task = setup
    Models.implementation = "VALUE = 0\n"
    f = Factory(repo, root, policy, Models)
    f.create(task)
    assert f.run("example")["state"] == "needs_attention"
    assert sum(write for _, _, write in Models.calls) == 4
    assert f.run("example")["state"] == "needs_attention"
    assert sum(write for _, _, write in Models.calls) == 4
    assert len({model for _, model, write in Models.calls if write}) == 1


def test_auth_disable_and_fallback(setup):
    repo, root, policy, task = setup
    f = Factory(repo, root, policy, Models)
    f.create(task)
    Models.failing["claude-opus-5-5"] = "auth"
    assert f.run("example")["state"] == "ready_for_pr"
    assert f.store.provider("claude")["disabled"]
    assert Models.calls[0][1] == "claude-opus-5-5"
    assert Models.calls[1][1] == "gpt-6.1-sol"


def test_critical_task_held_before_model_call(setup):
    repo, root, policy, task = setup
    task["risk"] = "critical"
    f = Factory(repo, root, policy, Models)
    f.create(task)
    assert f.run("example")["state"] == "approval_required"
    assert Models.calls == []


def test_budget_reservation_is_persistent(setup):
    repo, root, policy, task = setup
    values = yaml.safe_load(policy.read_text())
    values["max_calls_per_task"] = 1
    policy.write_text(yaml.safe_dump(values))
    f = Factory(repo, root, policy, Models)
    f.create(task)
    with pytest.raises(RuntimeError, match="circuit breaker"):
        f.run("example")
    assert len(Models.calls) == 1


def test_failed_worker_does_not_trigger_quota_fallback(setup):
    repo, root, policy, task = setup
    Models.failing["Qwen3.8-Flash"] = "failed"
    f = Factory(repo, root, policy, Models)
    f.create(task)
    with pytest.raises(FactoryError, match="returned failed"):
        f.run("example")
    assert sum(write for _, _, write in Models.calls) == 1
    assert f.store.task("example")["worker_model"] == "qwen"


def test_worker_commit_cannot_hide_out_of_scope_changes(setup):
    repo, root, policy, task = setup

    class CommittingModel(Models):
        def run(self, prompt, worktree, timeout, log_dir, write=False):
            result = super().run(prompt, worktree, timeout, log_dir, write)
            if write:
                (worktree / "README.md").write_text("unauthorized edit")
                git(worktree, "add", "README.md")
                git(
                    worktree,
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@localhost",
                    "commit",
                    "-m",
                    "hidden",
                )
            return result

    f = Factory(repo, root, policy, CommittingModel)
    f.create(task)
    with pytest.raises(FactoryError, match="changed HEAD"):
        f.run("example")


def test_orphaned_complete_packet_recovers_creation(setup):
    repo, root, policy, task = setup
    f = Factory(repo, root, policy, Models)
    f.create(task)
    with f.store.connect() as db:
        db.execute("DELETE FROM tasks WHERE id=?", (task["id"],))
    assert f.create(task)["state"] == "queued"


def test_quota_cooldown_and_no_worker_replay_after_partial_write(setup):
    repo, root, policy, task = setup
    Models.failing["Qwen3.8-Flash"] = "quota"
    f = Factory(repo, root, policy, Models)
    f.create(task)
    with pytest.raises(FactoryError, match="Interrupted worker left changes"):
        f.run("example")
    assert f.store.task("example")["worker_model"] == "qwen"
    assert f.store.provider("qodercn:Qwen3.8-Flash")["cooldown"] > 0
    with pytest.raises(FactoryError, match="No eligible model"):
        f.run("example")
    assert sum(write for _, _, write in Models.calls) == 1


def test_passed_cursor_recovers_without_worker_replay(setup):
    repo, root, policy, task = setup
    f = Factory(repo, root, policy, Models)
    f.create(task)
    original = f.checkpoint

    def crash(task_id, stage, *args, **kwargs):
        if stage == "commit":
            raise SystemExit("crash after verified cursor before stage update")
        return original(task_id, stage, *args, **kwargs)

    f.checkpoint = crash
    with pytest.raises(SystemExit):
        f.run("example")
    assert sum(write for _, _, write in Models.calls) == 1
    f.checkpoint = original
    assert f.run("example", recover=True)["state"] == "ready_for_pr"
    assert sum(write for _, _, write in Models.calls) == 1


def test_commit_recovery_rejects_untested_changes(setup):
    repo, root, policy, task = setup
    f = Factory(repo, root, policy, Models)
    f.create(task)
    original = f.checkpoint

    def crash(task_id, stage, *args, **kwargs):
        original(task_id, stage, *args, **kwargs)
        if stage == "commit":
            raise SystemExit("crash at commit")

    f.checkpoint = crash
    with pytest.raises(SystemExit):
        f.run("example")
    (root / "worktrees/example/feature.py").write_text("VALUE = 0\n")
    f.checkpoint = original
    with pytest.raises(FactoryError, match="Source changed after verification"):
        f.run("example", recover=True)


def test_failed_invocations_consume_persistent_attempts(setup):
    repo, root, policy, task = setup
    f = Factory(repo, root, policy, Models)
    f.create(task)
    Models.failing["Qwen3.8-Flash"] = "failed"
    for _ in range(4):
        with pytest.raises(FactoryError, match="returned failed"):
            f.run("example")
    assert f.run("example")["state"] == "needs_attention"
    assert sum(write for _, _, write in Models.calls) == 4


def test_gate_logs_can_repeat_after_interruption(setup):
    repo, root, policy, task = setup
    f = Factory(repo, root, policy, Models)
    f.create(task)
    saved = json.loads((root / "tasks/example/task.json").read_text())
    worktree = Path(saved["worktree"])
    worktree.parent.mkdir(parents=True)
    git(repo, "worktree", "add", "-b", saved["branch"], str(worktree), saved["base_commit"])
    (worktree / "feature.py").write_text("VALUE = 7\n")
    first, evidence1 = f.gates(saved, 0)
    second, evidence2 = f.gates(saved, 0)
    assert first and second
    assert evidence1[0]["log_dir"] != evidence2[0]["log_dir"]


def test_auth_failure_with_edits_never_switches_worker(setup):
    repo, root, policy, task = setup
    f = Factory(repo, root, policy, Models)
    f.create(task)
    Models.failing["Qwen3.8-Flash"] = "auth"
    with pytest.raises(FactoryError, match="Interrupted worker left changes"):
        f.run("example")
    assert sum(write for _, _, write in Models.calls) == 1


def test_publish_pushes_reviewed_sha_not_mutable_branch(setup, monkeypatch):
    from software_factory import engine

    repo, root, policy, task = setup
    f = Factory(repo, root, policy, Models)
    f.create(task)
    row = f.run("example")
    saved = json.loads((root / "tasks/example/task.json").read_text())
    worktree = Path(saved["worktree"])
    git(worktree, "checkout", "--detach", row["commit_sha"])
    git(repo, "branch", "-f", saved["branch"], saved["base_commit"])
    pushes = []
    original_git, original_output = engine.git, engine.subprocess.check_output

    def git_spy(repo, *args):
        if args[0] == "push":
            pushes.append(args)
            return ""
        return original_git(repo, *args)

    def output(argv, *args, **kwargs):
        if argv[:3] == ["gh", "repo", "view"]:
            return json.dumps({"defaultBranchRef": {"name": "main"}})
        if argv[:3] == ["gh", "pr", "list"]:
            return json.dumps(
                [
                    {
                        "url": "https://example.test/pr/1",
                        "state": "OPEN",
                        "headRefOid": row["commit_sha"],
                        "baseRefName": "main",
                    }
                ]
            )
        return original_output(argv, *args, **kwargs)

    monkeypatch.setattr(engine, "git", git_spy)
    monkeypatch.setattr(engine.subprocess, "check_output", output)
    assert f.publish("example")["state"] == "published"
    assert pushes == [("push", "origin", f"{row['commit_sha']}:refs/heads/{saved['branch']}")]


def test_json_contract_rejects_multiple_or_embedded_verdicts():
    from software_factory.engine import extract_json

    with pytest.raises(FactoryError):
        extract_json('Example {"approved":true} actual verdict {"approved":false}')
    assert extract_json('```json\n{"approved":false}\n```')["approved"] is False


def test_staged_out_of_scope_change_cannot_hide_in_restored_worktree(setup):
    repo, root, policy, task = setup

    class StagingModel(Models):
        def run(self, prompt, worktree, timeout, log_dir, write=False):
            result = super().run(prompt, worktree, timeout, log_dir, write)
            if write:
                original = (worktree / "README.md").read_text()
                (worktree / "README.md").write_text("hidden unauthorized staging")
                git(worktree, "add", "README.md")
                (worktree / "README.md").write_text(original)
            return result

    f = Factory(repo, root, policy, StagingModel)
    f.create(task)
    with pytest.raises(FactoryError, match="outside allowed_files"):
        f.run("example")
