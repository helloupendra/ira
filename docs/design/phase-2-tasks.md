# Phase 2: tasks on your Mac

Status: design, 22 Oct 2026.

## What it is

From the Ira app (or Telegram), a person hands a job to a coding agent on
their own Mac: "IRA repo mein login page ka typo theek karo, aur tests
chalao". The Mac companion runs it in a new git worktree of a repository
the person allowed, streams how it goes, and says when it is done: what
changed, and whether the tests pass. Nothing leaves that worktree without
the person's PIN.

## Tools (skill `tasks`, switched on per Mac with the PIN)

| Tool | Tier | What it does |
| --- | --- | --- |
| `task_start {repo, instruction}` | 2: needs your yes | a new worktree of an allowed repo on a new branch `ira/task-<id>`, and the agent started in it |
| `task_status {id}` | 0 | running, done, failed or stopped; the last lines of progress; files changed; tests |
| `task_list {}` | 0 | the tasks since the companion started |
| `task_stop {id}` | 1 | stops the agent; the worktree stays |
| `task_push {id}` | 3: needs your PIN | pushes the task's branch (never `main`) to `origin` |

Results are device output: untrusted, wrapped, and a turn that read them
cannot propose a Tier 2 or 3 action. So an agent's summary can never start
another task or push.

## Configuration lives on the Mac only

The companion's `config.json` holds a `tasks` section; nothing about it is
in the repository or on the server:

```json
"tasks": {
  "command": ["/path/to/agent", "-p", "{prompt}", "--output-format", "stream-json"],
  "repos": {"ira": {"path": "/Users/me/code/ira", "test": "ruff check . && pytest -q"}},
  "worktrees": "~/ira-tasks",
  "writable": ["~/.agent-state"],
  "minutes": 60
}
```

- **The allow-list** is `repos`: a task names one of these, never a path.
- **The command** is the agent's headless command line. `{prompt}` is
  replaced by one argument (no shell), else the prompt is added last. Any
  agent that prints text, or one JSON object per line ending with
  `{"type": "result", "result": "...", "is_error": false}`, works.
- Without a `tasks` section the Mac offers no task tools at all.

## Safety

- **A new worktree and branch per task.** The person's own checkout is
  never touched.
- **A sandbox** (`sandbox-exec`, built into macOS): the agent and the test
  command may write only to the worktree, the repository's `.git`
  (commits on its own branch), temporary folders, and the folders listed in
  `writable`. Everything else under the home folder, `/opt/homebrew` and
  `/usr/local` is read-only to it, so it cannot delete files elsewhere and
  global installs (`brew install`, `npm -g`, `pip install --user`) fail.
- **No push from inside.** The agent's git has a `pre-push` hook that
  refuses, and `origin`'s push address points nowhere. Only `task_push`,
  after the person's PIN, pushes, and only the task's branch.
- **The prompt** tells the agent the same rules: work only here, never
  push, merge or deploy, install nothing from the network unless asked.
  The person's agent configuration can deny those commands too.
- These stop accidents and a confused agent. They are not a wall against
  hostile code: run tasks only in repositories you trust.
- At most 2 tasks at once; each is stopped after `minutes` (60).

## When it ends

The companion collects the files changed (uncommitted and committed on
the branch), runs the repository's `test` command if it has one (15
minutes at most, in the same sandbox), and sends one event:

- `task_done`: "Task t3a9f1 in ira is done: …the agent's summary…
  3 files changed. Tests passed."
- `task_failed`: the same, with why (the agent's error, a timeout, a stop).

## macOS privacy (TCC)

A LaunchAgent cannot read `~/Documents`, `~/Desktop` or `~/Downloads`. A
task in a repository there fails with a message naming the fix:

- `ira-mac detach` from Terminal: stops the LaunchAgent's copy and starts
  the companion from Terminal, which has that access, until the next
  login; or
- give the companion's Python Full Disk Access in System Settings, Privacy
  & Security. The companion never does this silently.
