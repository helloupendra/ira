# The Ira companion for Mac

Lets your own Ira read and watch your Chrome tabs when you ask, and tell you
when something finishes. It is a device in IRA's sense: it pairs with your
IRA server with a one-time code, holds one WebSocket to it, and offers three
tools that belong to the **chrome** skill:

| Tool | Tier | What it does |
| --- | --- | --- |
| `chrome_list_tabs` | 0 | the open tabs: id, title, address without its query, which one is in front |
| `chrome_read_tab {tabId?, match?}` | 0 | one tab's title, address, visible text (20,000 characters at most) and progress |
| `chrome_watch_tab {tabId?, match?, untilText?, idleSeconds?, timeoutMinutes?}` | 1 | watches a tab and announces `watch_done` when the text appears, it reaches 100%, it newly says Completed or Failed, it is quiet for `idleSeconds`, it closes, or the time runs out (60 minutes by default). At most 5 at once |

`match` picks a tab by words from its title or address, preferring the tab in
front. The person switches the skill on for this Mac on their Devices page,
with their PIN; until then IRA offers none of these tools.

Users: see [the Mac guide](../../docs/clients/mac.md). This file is for
developers.

## Two processes, on purpose

```text
Chrome ── Ira extension ──native messaging (stdio)──> host (in.ira.mac)
                                                           │ Unix socket, mode 0700
                                                           ▼
IRA server <──── WebSocket, device token ─────────── daemon (LaunchAgent)
```

- **Chrome decides when the host runs.** Chrome starts a native messaging
  host itself, only while the extension holds a port, and talks to it over
  stdin and stdout. A process like that cannot be the one that stays
  connected to the server: it would vanish whenever Chrome quits.
- **The daemon must outlive Chrome.** It holds the WebSocket around the
  clock, reconnects with backoff, keeps watches running and queues events,
  and (in phase 2) runs tasks that have nothing to do with Chrome. launchd
  starts it at login and restarts it if it stops.
- **The token stays out of Chrome's reach.** Only the daemon reads the token
  from the Keychain. The host holds no token and opens no network
  connection; it only relays frames to the daemon's socket, which lives in a
  folder only you can open. If the host is ever compromised through Chrome,
  it can do no more than the extension already could.
- **Restarts are cheap on both sides.** The host keeps retrying the socket
  while Chrome holds the port, so the extension stays connected while the
  daemon restarts, and the server connection survives Chrome restarts.

## Files

| Path | What |
| --- | --- |
| `ira_mac/daemon.py` | the WebSocket client: hello, calls, pings, reconnects, the event outbox |
| `ira_mac/bridge.py` | the daemon's Unix socket for Chrome, and requests to the extension |
| `ira_mac/host.py` | the native messaging host: a relay, nothing more |
| `ira_mac/frames.py` | length-prefixed JSON frames, as Chrome uses them |
| `ira_mac/tools.py` | the three tools and the watches |
| `ira_mac/tabs.py`, `ira_mac/watch.py` | which tab is meant; when a watch is done |
| `ira_mac/keychain.py` | the token in the Keychain, through `security` on stdin |
| `ira_mac/pair.py` | trading the pairing code for the token |
| `ira_mac/logs.py` | logs without page text, queries or tokens |
| `install.sh`, `uninstall.sh` | set up and remove everything for one user; safe to run again |

## Rules it keeps

- **The token** lives in the login Keychain under service `ira-mac`. It is
  never in a file, a log or a command line: saving it types the command into
  `security -i` on stdin, and the WebSocket carries it in a header.
- **TCC.** macOS does not let launchd processes read `~/Documents` without a
  permission. Everything is installed under
  `~/Library/Application Support/ira-mac/`, and the companion reads nothing
  under `~/Documents` in this version.
- **Logs** (`~/Library/Application Support/ira-mac/logs/`) hold tool names,
  tab ids and timings. Never page text, and never an address with its query;
  a redacting formatter strips any that slip in.
- **Limits** follow the server: frames of 1 MB at most (a bigger answer is
  replaced by an error), one event per 30 seconds (the outbox waits), pings
  every 30 seconds, and a reconnect after 90 seconds of silence. After a
  revoked token it waits 5 minutes between tries and logs why.

## Develop

Python 3.9 or newer (the Command Line Tools' Python is enough).

```bash
python3 -m venv .venv && .venv/bin/pip install "websockets>=13" pytest
.venv/bin/python -m pytest          # no network: fake servers on 127.0.0.1
.venv/bin/python -m ira_mac run --foreground   # with a paired token in the Keychain
```

The tests cover the frame codec; the protocol against a fake WebSocket
server (handshake, call and result, a Chrome that does not answer, reconnect,
ping and pong, silence, the 1 MB cap, event spacing); tab matching; the watch
rules; log redaction; the Keychain (and a real throwaway keychain on macOS);
the host relay and the bridge end to end; pairing; and a dry run of
`install.sh` and `uninstall.sh` in a temporary home folder.
