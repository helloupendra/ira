"""The device token in the macOS Keychain (service ``ira-mac``), never in a file, a log or argv.

``security`` is the system's own Keychain tool. Saving runs ``security -i`` and
types the command on its standard input, so the token never appears in a
process list; reading prints the token to a pipe this process reads.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

SERVICE = "ira-mac"
ACCOUNT = "device"
TOKEN = re.compile(r"^irad_[A-Za-z0-9_-]{20,100}$")

Runner = Callable[..., Any]  # subprocess.run's signature


class KeychainError(RuntimeError):
    pass


class Keychain:
    def __init__(
        self,
        *,
        service: str = SERVICE,
        account: str = ACCOUNT,
        keychain: str | None = None,
        run: Runner = subprocess.run,
    ) -> None:
        self.service = service
        self.account = account
        self.keychain = keychain  # a keychain file; None: the login keychain
        self.run = run

    def _where(self) -> list[str]:
        return [self.keychain] if self.keychain else []

    def save(self, token: str) -> None:
        if not TOKEN.match(token):
            raise KeychainError("that is not a device token")
        where = f" {self.keychain}" if self.keychain else ""
        command = (
            f"add-generic-password -U -s {self.service} -a {self.account} "
            f'-l "IRA device token" -w {token}{where}\n'
        )
        self.run(
            ["/usr/bin/security", "-i"],
            input=command,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if self.load() != token:
            raise KeychainError("the Keychain did not keep the token")

    def load(self) -> str | None:
        args: Sequence[str] = [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            self.service,
            "-a",
            self.account,
            "-w",
            *self._where(),
        ]
        result = self.run(list(args), capture_output=True, text=True, check=False, timeout=30)
        if result.returncode != 0:
            return None
        token = (result.stdout or "").strip()
        return token if TOKEN.match(token) else None

    def delete(self) -> bool:
        args = [
            "/usr/bin/security",
            "delete-generic-password",
            "-s",
            self.service,
            "-a",
            self.account,
            *self._where(),
        ]
        result = self.run(args, capture_output=True, text=True, check=False, timeout=30)
        return result.returncode == 0
