"""Adapter between the bully package and the website.

This is the only module that knows about both sides. It runs one Bully node in a
background thread and answers one question for the web layer: is this pod the leader?

The bully package is used exactly as `python -m bully node` uses it: Config.from_env(),
build() and serve() from bully.__main__. Only the thread around serve() is new.
"""

import logging
import os
import threading
from collections.abc import Mapping

from bully.__main__ import CHECK_INTERVAL, Config, build, serve
from bully.state import Status

log = logging.getLogger(__name__)


class LeaderElection:
    """Runs this pod's Bully node and reports who the leader is."""

    def __init__(self, env: Mapping[str, str] = os.environ, interval: float = CHECK_INTERVAL):
        self._env = env              # the BULLY_* variables, see src/bully/__main__.py
        self._interval = interval    # seconds between check() and timeout(); tests use less
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._node = None
        self.node_id: int | None = None

    def start(self) -> None:
        """Start the election node in a background thread.

        Raises ValueError if a BULLY_* variable is missing or wrong.
        """
        if self._thread is not None:
            raise RuntimeError("the election is already running")
        config = Config.from_env(self._env)
        logging.getLogger("bully").setLevel(config.log_level)
        log.info("%s Bully, node %d of %d, T = %.1f s",
                 config.algorithm, config.node_id, config.n, config.timeout)
        node, comm = build(config)
        self._node, self.node_id = node, config.node_id
        self._thread = threading.Thread(
            target=self._run, args=(node, comm), name="bully", daemon=True)
        self._thread.start()

    def _run(self, node, comm) -> None:
        try:
            serve(node, comm, self._stop, self._interval)
        except Exception:
            # Without this the thread would die silently and the pod would never lead again
            log.exception("the election node stopped with an error")

    def stop(self, timeout: float = 10.0) -> None:
        """Stop the node and wait for its thread to finish.

        To the other nodes this looks like a crash. The wait can last a few T if the node
        is in the middle of an election.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def is_leader(self) -> bool:
        """True if this pod is the coordinator and its state is Normal."""
        node = self._node
        if node is None:
            return False
        with node._lock:   # the library's own lock around the state vector
            return node.state.s == Status.NORMAL and node.state.c == node.id

    def leader_id(self) -> int | None:
        """The id of the current coordinator, or None during an election."""
        node = self._node
        if node is None:
            return None
        with node._lock:
            return node.state.c if node.state.s == Status.NORMAL else None
