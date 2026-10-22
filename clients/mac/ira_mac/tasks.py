"""Tasks: a coding agent at work in a new git worktree of a repository the person allowed.

Everything about it is set on this Mac, in ``config.json``'s ``tasks``
section, never in the repository or on the server::

    "tasks": {
      "command": ["/path/to/agent", "-p", "{prompt}", "--output-format", "stream-json"],
      "repos": {"ira": {"path": "/Users/me/code/ira", "test": "pytest -q"}},
      "worktrees": "~/ira-tasks",
      "writable": ["~/.agent-state"],
      "minutes": 60
    }

The agent runs in a macOS sandbox that lets it write only to its worktree,
the repository's ``.git``, temporary folders and the ``writable`` list. Its
git refuses to push. Only ``task_push``, which Ira runs after the person's
PIN, pushes, and only the task's own branch. These stop accidents and a
confused agent; they are not a wall against hostile code.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import shutil
import signal
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("ira_mac.tasks")

MAX_RUNNING = 2
DEFAULT_MINUTES = 60
TEST_MINUTES = 15
MAX_INSTRUCTION = 4000
MAX_FILES = 50
SANDBOX = Path("/usr/bin/sandbox-exec")
NO_PUSH_URL = "ira-task-cannot-push:"

PROMPT = """\
You are doing a task for {person} in this folder: a new git worktree of the \
repository "{repo}", on the branch {branch}. Rules: work only in this folder. \
Do not push, merge, deploy or publish anything. Do not delete or change files \
outside this folder. Do not install anything from the network unless the task \
says so. Commit your work on this branch if that helps. When you finish, end \
with a short summary: what you changed, and how you checked it.

The task: {instruction}"""

PROFILE = """\
(version 1)
(allow default)
(deny file-write* (subpath (param "HOME")) (subpath "/opt/homebrew") (subpath "/usr/local"))
(allow file-write*
  (subpath (param "WORKTREE"))
  (subpath (param "GITDIR"))
  (subpath "/private/tmp")
  (subpath "/private/var/folders")
  (subpath (string-append (param "HOME") "/Library/Caches"))
{extra})
"""

DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "task_start",
        "description": "Start a coding or research task on this Mac: a coding agent works in a "
        "new git worktree of one of the person's allowed repositories, on its own branch. It "
        "never pushes. Ira says when it is done.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "An allowed repository's name."},
                "instruction": {"type": "string", "description": "What to do, in full."},
            },
            "required": ["repo", "instruction"],
        },
        "skill": "tasks",
        "tier": 2,
    },
    {
        "name": "task_status",
        "description": "How a task is going: running, done, failed or stopped; its latest "
        "progress, the files changed and the tests.",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
        "skill": "tasks",
        "tier": 0,
    },
    {
        "name": "task_list",
        "description": "This Mac's tasks, newest first, and the repositories tasks may use.",
        "parameters": {"type": "object", "properties": {}},
        "skill": "tasks",
        "tier": 0,
    },
    {
        "name": "task_stop",
        "description": "Stop a running task. Its worktree and branch stay.",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
        "skill": "tasks",
        "tier": 1,
    },
    {
        "name": "task_push",
        "description": "Push a finished task's branch (never main) to the repository's origin.",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
        "skill": "tasks",
        "tier": 3,
    },
]


class TaskError(Exception):
    """A task request that cannot be done, with a message for the person."""


@dataclass
class Repo:
    name: str
    path: Path
    test: str | None = None


@dataclass
class TaskSettings:
    command: list[str]
    repos: dict[str, Repo]
    worktrees: Path
    writable: list[Path] = field(default_factory=list)
    minutes: float = DEFAULT_MINUTES
    sandbox: bool = True

    @classmethod
    def from_config(cls, raw: dict[str, Any]) -> TaskSettings | None:
        """None when tasks are not set up on this Mac."""
        command = raw.get("command")
        repos = raw.get("repos")
        if not (isinstance(command, list) and command and isinstance(repos, dict) and repos):
            return None
        allowed = {}
        for name, entry in repos.items():
            entry = {"path": entry} if isinstance(entry, str) else entry
            if not isinstance(entry, dict) or not entry.get("path"):
                continue
            test = entry.get("test")
            allowed[str(name)] = Repo(
                str(name),
                Path(os.path.expanduser(str(entry["path"]))),
                str(test) if test else None,
            )
        if not allowed:
            return None
        return cls(
            command=[str(part) for part in command],
            repos=allowed,
            worktrees=Path(os.path.expanduser(str(raw.get("worktrees") or "~/ira-tasks"))),
            writable=[Path(os.path.expanduser(str(p))) for p in raw.get("writable") or []],
            minutes=float(raw.get("minutes") or DEFAULT_MINUTES),
            sandbox=raw.get("sandbox", True) is not False,
        )


@dataclass
class Task:
    id: str
    repo: Repo
    instruction: str
    branch: str
    worktree: Path
    base: str
    started: float
    status: str = "starting"  # starting, running, done, failed, stopped
    finished: float | None = None
    progress: deque = field(default_factory=lambda: deque(maxlen=5))
    result: str = ""
    error: str = ""
    files: list[str] = field(default_factory=list)
    tests: str = "not run"
    process: Any = None
    runner: Any = None

    def view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "repo": self.repo.name,
            "branch": self.branch,
            "status": self.status,
            "instruction": self.instruction[:200],
            "started": self.started,
            "finished": self.finished,
            "progress": list(self.progress),
            "summary": self.result[:2000],
            "error": self.error,
            "files": self.files,
            "tests": self.tests,
        }


def _short(text: str, limit: int = 240) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def progress_of(line: str) -> tuple[str | None, dict[str, Any] | None]:
    """(a progress line, the final result) from one line of the agent's output."""
    line = line.strip()
    if not line:
        return None, None
    try:
        item = json.loads(line)
    except ValueError:
        return _short(line), None
    if not isinstance(item, dict):
        return None, None
    if item.get("type") == "result":
        return None, item
    message = item.get("message")
    if item.get("type") == "assistant" and isinstance(message, dict):
        parts = message.get("content")
        if isinstance(parts, list):
            texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
            text = " ".join(t for t in texts if t)
            if text:
                return _short(text), None
            tools = [p.get("name") for p in parts if isinstance(p, dict) and p.get("name")]
            if tools:
                return f"using {', '.join(tools)}", None
    return None, None


class TaskRunner:
    def __init__(
        self,
        settings: TaskSettings,
        announce: Callable[[str, str, str, dict[str, Any]], None],
        *,
        person: str = "the person who owns this Mac",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.announce = announce
        self.person = person
        self.clock = clock
        self.tasks: dict[str, Task] = {}
        self.hooks = Path(tempfile.mkdtemp(prefix="ira-task-hooks-"))
        hook = self.hooks / "pre-push"
        hook.write_text(
            "#!/bin/sh\necho 'Ira tasks never push: the person pushes after their PIN.' >&2\n"
            "exit 1\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return DEFINITIONS

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        handler = {
            "task_start": self.start,
            "task_status": self.status,
            "task_list": self.list,
            "task_stop": self.stop,
            "task_push": self.push,
        }.get(name)
        if handler is None:
            raise TaskError(f"no tool '{name}'")
        return await handler(args)

    def _task(self, args: dict[str, Any]) -> Task:
        task = self.tasks.get(str(args.get("id") or ""))
        if task is None:
            raise TaskError("no such task on this Mac")
        return task

    # The tools.

    async def start(self, args: dict[str, Any]) -> dict[str, Any]:
        repo = self.settings.repos.get(str(args.get("repo") or ""))
        if repo is None:
            names = ", ".join(sorted(self.settings.repos))
            raise TaskError(f"that repository is not allowed here; allowed: {names}")
        instruction = " ".join(str(args.get("instruction") or "").split())
        if not instruction:
            raise TaskError("say what the task is")
        if len(instruction) > MAX_INSTRUCTION:
            raise TaskError(f"keep the task under {MAX_INSTRUCTION} characters")
        running = [t for t in self.tasks.values() if t.status in ("starting", "running")]
        if len(running) >= MAX_RUNNING:
            raise TaskError(f"{MAX_RUNNING} tasks are running already; wait or stop one")
        task_id = "t" + secrets.token_hex(3)
        branch = f"ira/task-{task_id}"
        worktree = self.settings.worktrees / f"{repo.name}-{task_id}"
        base = await self._git(repo.path, "rev-parse", "HEAD")
        self.settings.worktrees.mkdir(parents=True, exist_ok=True)
        await self._git(repo.path, "worktree", "add", "-b", branch, str(worktree), base)
        task = Task(task_id, repo, instruction, branch, worktree, base, self.clock())
        self.tasks[task_id] = task
        task.runner = asyncio.ensure_future(self._run(task))
        return {
            "id": task_id,
            "repo": repo.name,
            "branch": branch,
            "summary": f"Task {task_id} started in {repo.name} on {branch}. Ira says when it is "
            "done.",
        }

    async def status(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._task(args).view()

    async def list(self, args: dict[str, Any]) -> dict[str, Any]:
        tasks = sorted(self.tasks.values(), key=lambda t: t.started, reverse=True)
        return {
            "repos": sorted(self.settings.repos),
            "tasks": [
                {k: v for k, v in t.view().items() if k in ("id", "repo", "status", "instruction")}
                for t in tasks
            ],
        }

    async def stop(self, args: dict[str, Any]) -> dict[str, Any]:
        task = self._task(args)
        if task.status not in ("starting", "running"):
            return {"id": task.id, "summary": f"Task {task.id} had already {task.status}."}
        task.status = "stopped"
        self._kill(task)
        return {"id": task.id, "summary": f"Stopped task {task.id}. Its worktree stays."}

    async def push(self, args: dict[str, Any]) -> dict[str, Any]:
        task = self._task(args)
        if task.status != "done":
            raise TaskError(f"task {task.id} is {task.status}; only a finished task is pushed")
        # As the person, outside the sandbox and without the task's no-push settings.
        await self._git(task.worktree, "push", "--set-upstream", "origin", task.branch)
        return {"id": task.id, "summary": f"Pushed {task.branch} to origin. Nothing was merged."}

    # Running.

    def environment(self, task: Task) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "core.hooksPath",
                "GIT_CONFIG_VALUE_0": str(self.hooks),
                "GIT_CONFIG_KEY_1": "remote.origin.pushurl",
                "GIT_CONFIG_VALUE_1": NO_PUSH_URL,
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        return env

    def sandboxed(self, task: Task, argv: list[str]) -> list[str]:
        """argv inside macOS's sandbox, when it is on and this Mac has it."""
        if not (self.settings.sandbox and SANDBOX.exists()):
            return argv
        extra = "\n".join(
            f'  (subpath (param "W{i}")) (literal (param "W{i}"))'
            for i in range(len(self.settings.writable))
        )
        params = [
            "-D",
            f"HOME={Path.home()}",
            "-D",
            f"WORKTREE={task.worktree.resolve()}",
            "-D",
            f"GITDIR={(task.repo.path / '.git').resolve()}",
        ]
        for i, path in enumerate(self.settings.writable):
            params += ["-D", f"W{i}={path.resolve()}"]
        return [str(SANDBOX), "-p", PROFILE.format(extra=extra), *params, *argv]

    def prompt(self, task: Task) -> str:
        return PROMPT.format(
            person=self.person,
            repo=task.repo.name,
            branch=task.branch,
            instruction=task.instruction,
        )

    def argv(self, task: Task) -> list[str]:
        prompt = self.prompt(task)
        command = self.settings.command
        if any("{prompt}" in part for part in command):
            return [part.replace("{prompt}", prompt) for part in command]
        return [*command, prompt]

    async def _run(self, task: Task) -> None:
        try:
            task.process = await asyncio.create_subprocess_exec(
                *self.sandboxed(task, self.argv(task)),
                cwd=str(task.worktree),
                env=self.environment(task),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            task.status = "running"
            errors: deque = deque(maxlen=5)
            reader = asyncio.ensure_future(self._read(task))
            err_reader = asyncio.ensure_future(self._lines(task.process.stderr, errors))
            try:
                await asyncio.wait_for(task.process.wait(), self.settings.minutes * 60)
            except asyncio.TimeoutError:
                task.error = f"it took longer than {self.settings.minutes:.0f} minutes"
                self._kill(task)
                await task.process.wait()
            final = await reader
            await err_reader
            code = task.process.returncode
            if task.status == "stopped":
                task.error = task.error or "stopped"
            elif final is not None:
                task.result = str(final.get("result") or "")
                if final.get("is_error"):
                    task.error = _short(task.result or "the agent reported an error")
            elif not task.result:
                task.result = " ".join(task.progress)
            if code and not task.error and task.status != "stopped":
                task.error = _short(" ".join(errors) or f"the agent exited with code {code}")
        except Exception as exc:  # starting failed, or something unexpected
            log.exception("task %s failed", task.id)
            task.error = _short(f"{type(exc).__name__}: {exc}")
        await self._finish(task)

    async def _lines(self, stream: Any, into: deque) -> None:
        while True:
            line = await stream.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").strip()
            if text:
                into.append(_short(text))

    async def _read(self, task: Task) -> dict[str, Any] | None:
        final = None
        while True:
            line = await task.process.stdout.readline()
            if not line:
                return final
            progress, result = progress_of(line.decode("utf-8", "replace"))
            if progress:
                task.progress.append(progress)
            if result is not None:
                final = result

    def _kill(self, task: Task) -> None:
        process = task.process
        if process is None or process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGTERM)

    async def _finish(self, task: Task) -> None:
        with contextlib.suppress(TaskError):
            task.files = await self.changed(task)
        if not task.error and task.repo.test:
            task.tests = await self.run_tests(task)
        if task.status != "stopped":
            task.status = "failed" if task.error else "done"
        task.finished = self.clock()
        files = f"{len(task.files)} file{'s' if len(task.files) != 1 else ''} changed"
        data = {
            "id": task.id,
            "repo": task.repo.name,
            "branch": task.branch,
            "files": task.files,
            "tests": task.tests,
        }
        if task.status == "done":
            summary = _short(task.result, 400) or "No summary."
            self.announce(
                "task_done",
                f"Task {task.id} in {task.repo.name} is done",
                f"{summary} {files}. Tests: {task.tests}.",
                data,
            )
        else:
            self.announce(
                "task_failed",
                f"Task {task.id} in {task.repo.name} {task.status}",
                f"{task.error or task.status}. {files}.",
                data,
            )

    async def changed(self, task: Task) -> list[str]:
        """Files changed on the branch: committed since the start, and not yet committed."""
        lists = [
            await self._git(task.worktree, "diff", "--name-only", f"{task.base}..HEAD"),
            await self._git(task.worktree, "diff", "--name-only", "HEAD"),
            await self._git(task.worktree, "ls-files", "--others", "--exclude-standard"),
        ]
        names = [line.strip() for text in lists for line in text.splitlines() if line.strip()]
        return list(dict.fromkeys(names))[:MAX_FILES]

    async def run_tests(self, task: Task) -> str:
        test = task.repo.test or ""
        try:
            process = await asyncio.create_subprocess_exec(
                *self.sandboxed(task, ["/bin/sh", "-c", test]),
                cwd=str(task.worktree),
                env=self.environment(task),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            output, _ = await asyncio.wait_for(process.communicate(), TEST_MINUTES * 60)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGTERM)
            return f"stopped after {TEST_MINUTES} minutes"
        except OSError as exc:
            return f"could not run ({exc.strerror or exc})"
        if process.returncode == 0:
            return "passed"
        tail = output.decode("utf-8", "replace").strip().splitlines()[-3:]
        return _short(f"failed (exit {process.returncode}): {' '.join(tail)}", 300)

    async def _git(self, where: Path, *args: str) -> str:
        """git in a folder, as the person: not sandboxed (the agent never runs this)."""
        git = shutil.which("git") or "/usr/bin/git"
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        try:
            process = await asyncio.create_subprocess_exec(
                git,
                "-C",
                str(where),
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            out, err = await asyncio.wait_for(process.communicate(), 120)
        except asyncio.TimeoutError:
            raise TaskError(f"git {args[0]} took too long") from None
        except OSError as exc:
            raise TaskError(_tcc_hint(where, exc) or f"git failed: {exc}") from None
        if process.returncode != 0:
            message = err.decode("utf-8", "replace")
            raise TaskError(_tcc_hint(where, message) or _short(f"git {args[0]}: {message}", 300))
        return out.decode("utf-8", "replace").strip()


def _tcc_hint(where: Path, problem: Any) -> str | None:
    """macOS keeps a LaunchAgent out of Documents, Desktop and Downloads: say how to fix it."""
    text = str(problem)
    if "Operation not permitted" not in text:
        return None
    return (
        f"macOS keeps the companion out of {where}. In Terminal, run "
        "'~/Library/Application Support/ira-mac/ira-mac detach' (until the next login), or "
        "give the companion's Python Full Disk Access in System Settings, Privacy & Security."
    )
