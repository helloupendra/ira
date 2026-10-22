"""Tasks: a stand-in agent in a real worktree, the sandbox, no push from inside, the push."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

from ira_mac.tasks import TaskError, TaskRunner, TaskSettings, _tcc_hint, progress_of

AGENT = textwrap.dedent(
    """
    import json, os, pathlib, subprocess, sys, time
    prompt = sys.argv[1]
    say = lambda text: print(json.dumps({"type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]}}), flush=True)
    print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
    say("Fixing the typo")
    pathlib.Path("a.txt").write_text("hello world\\n")
    push = subprocess.run(["git", "push", "origin", "HEAD"], capture_output=True)
    outside = "written"
    try:
        pathlib.Path(os.environ["IRA_TEST_PROBE"]).write_text("x")
    except OSError:
        outside = "refused"
    say(f"push exit {push.returncode}; outside {outside}")
    if "slowly" in prompt:
        time.sleep(30)
    if "fail" in prompt:
        print(json.dumps({"type": "result", "result": "Could not find it.", "is_error": True}))
        sys.exit(1)
    print(json.dumps({"type": "result", "result": "Fixed the typo in a.txt.", "is_error": False}))
    """
)


def git(where: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(where), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "owner@example.com")
    git(repo, "config", "user.name", "Owner")
    (repo / "a.txt").write_text("helo world\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "First")
    git(repo, "remote", "add", "origin", str(origin))
    agent = tmp_path / "agent.py"
    agent.write_text(AGENT)
    # Something outside every allowed folder, in the home folder.
    probe = Path.home() / f".ira-task-probe-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("IRA_TEST_PROBE", str(probe))
    events = []
    settings = TaskSettings.from_config(
        {
            "command": [sys.executable, str(agent), "{prompt}"],
            "repos": {"demo": {"path": str(repo), "test": "grep -q 'hello world' a.txt"}},
            "worktrees": str(tmp_path / "tasks"),
            "minutes": 1,
        }
    )
    runner = TaskRunner(settings, lambda *event: events.append(event))
    yield runner, repo, origin, events, probe
    probe.unlink(missing_ok=True)


def run(coroutine):
    return asyncio.get_event_loop().run_until_complete(coroutine)


@pytest.fixture(autouse=True)
def loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


def test_a_task_works_in_its_own_worktree_and_never_pushes(setup):
    runner, repo, origin, events, probe = setup
    started = run(runner.start({"repo": "demo", "instruction": "fix the typo in a.txt"}))
    task = runner.tasks[started["id"]]
    assert task.branch == f"ira/task-{task.id}" and task.worktree.is_dir()
    run(task.runner)
    view = run(runner.status({"id": task.id}))
    assert view["status"] == "done", view
    assert view["files"] == ["a.txt"] and view["tests"] == "passed"
    assert view["summary"] == "Fixed the typo in a.txt."
    assert "push exit 0" not in " ".join(view["progress"])  # its git refused to push
    assert (repo / "a.txt").read_text() == "helo world\n"  # the person's checkout untouched
    assert git(origin, "branch", "--list") == ""
    if sys.platform == "darwin":
        assert "outside refused" in " ".join(view["progress"]) and not probe.exists()
    ((kind, title, text, data),) = events
    assert kind == "task_done" and title == f"Task {task.id} in demo is done"
    assert text == "Fixed the typo in a.txt. 1 file changed. Tests: passed."
    assert data["files"] == ["a.txt"] and data["branch"] == task.branch
    # The person's PIN-confirmed push: the task's branch, never main.
    pushed = run(runner.push({"id": task.id}))
    assert "Nothing was merged" in pushed["summary"]
    assert task.branch in git(origin, "branch", "--list")
    assert "main" not in git(origin, "branch", "--list")


def test_a_failed_or_stopped_task_says_so(setup):
    runner, _, _, events, _ = setup
    failed = run(runner.start({"repo": "demo", "instruction": "fail at this"}))
    run(runner.tasks[failed["id"]].runner)
    assert runner.tasks[failed["id"]].status == "failed"
    assert events[-1][0] == "task_failed" and "Could not find it." in events[-1][2]
    with pytest.raises(TaskError, match="only a finished task"):
        run(runner.push({"id": failed["id"]}))

    slow = run(runner.start({"repo": "demo", "instruction": "do it slowly"}))
    task = runner.tasks[slow["id"]]

    async def stop_soon():
        while not task.progress:
            await asyncio.sleep(0.05)
        await runner.stop({"id": task.id})
        await task.runner

    run(stop_soon())
    assert task.status == "stopped" and events[-1][0] == "task_failed"
    assert events[-1][1].endswith("stopped")


def test_only_allowed_repositories_and_two_at_once(setup):
    runner, *_ = setup
    with pytest.raises(TaskError, match="not allowed here; allowed: demo"):
        run(runner.start({"repo": "secrets", "instruction": "read it"}))
    with pytest.raises(TaskError, match="say what the task is"):
        run(runner.start({"repo": "demo", "instruction": "  "}))
    first = run(runner.start({"repo": "demo", "instruction": "do it slowly"}))
    second = run(runner.start({"repo": "demo", "instruction": "do it slowly"}))
    with pytest.raises(TaskError, match="2 tasks are running"):
        run(runner.start({"repo": "demo", "instruction": "a third"}))
    for started in (first, second):
        run(runner.stop({"id": started["id"]}))
        run(runner.tasks[started["id"]].runner)
    listed = run(runner.list({}))
    assert listed["repos"] == ["demo"] and len(listed["tasks"]) == 2


def test_no_tasks_without_a_command_and_repositories():
    assert TaskSettings.from_config({}) is None
    assert TaskSettings.from_config({"command": ["agent"], "repos": {}}) is None
    settings = TaskSettings.from_config({"command": ["agent"], "repos": {"ira": "~/code/ira"}})
    assert settings is not None and settings.repos["ira"].path == Path.home() / "code" / "ira"


def test_progress_from_the_agents_lines():
    line = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Reading"}]}}
    )
    assert progress_of(line) == ("Reading", None)
    tool = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit"}]}}
    )
    assert progress_of(tool) == ("using Edit", None)
    result = {"type": "result", "result": "Done.", "is_error": False}
    assert progress_of(json.dumps(result)) == (None, result)
    assert progress_of("plain text from another agent") == ("plain text from another agent", None)
    assert progress_of("  ") == (None, None)


def test_a_folder_macos_keeps_out_is_explained():
    hint = _tcc_hint(Path("/Users/me/Documents/code"), "fatal: Operation not permitted")
    assert hint and "ira-mac detach" in hint and "Full Disk Access" in hint
    assert _tcc_hint(Path("/tmp"), "fatal: not a git repository") is None
