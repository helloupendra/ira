"""The IRA Mac companion: lets your own Ira read and watch your Chrome tabs when you ask.

Two processes, on purpose:

* ``daemon`` (a LaunchAgent) holds the device WebSocket to your IRA server, keeps
  the device token in the Keychain, and runs the tools and watches.
* ``host`` is the Chrome native-messaging host ``in.ira.mac``: Chrome starts it
  for the Ira extension, and it only relays frames to the daemon's Unix socket.
"""

__version__ = "0.3.0"
