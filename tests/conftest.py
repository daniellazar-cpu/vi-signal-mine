"""Shared fixtures.

Task 2's global constraint is that the whole suite is hermetic: every Bright
Data surface is exercised through ``httpx.MockTransport`` and no test makes a
real network call. This is enforced here rather than left to convention —
patching ``socket.socket.connect`` to raise means a test that ever does reach
for a real connection fails loudly and immediately, instead of hanging on a
live host or (worse) silently succeeding against one.

``httpx.MockTransport`` never touches a real socket, so this guard is
transparent to every hermetic test in the suite. It has nothing to do with
``tests/test_mining_parity.py`` reading the parent checkout off local disk —
that is a filesystem import, not a network call, and is unaffected.
"""

from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def _no_real_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(
            "a test attempted a real socket connection — this suite is hermetic; "
            "use httpx.MockTransport instead"
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
