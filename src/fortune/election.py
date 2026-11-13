"""Adapter between the bully package and the website.

This is the only module that knows about both sides. It runs one Bully node in a
background thread and answers one question for the web layer: is this pod the leader?

Planned implementation:
    start()      bully.__main__.Config.from_env(os.environ), then build() and serve()
                 in a daemon thread, with a threading.Event to stop it.
    is_leader()  under node._lock: node.state.c == node.id and node.state.s == Status.NORMAL
"""


class LeaderElection:
    """Runs this pod's Bully node and reports who the leader is."""

    def start(self) -> None:
        """Start the election node in a background thread."""
        raise NotImplementedError

    def stop(self) -> None:
        """Stop the node and wait for its thread to finish."""
        raise NotImplementedError

    def is_leader(self) -> bool:
        """True if this pod is the coordinator and its state is Normal."""
        raise NotImplementedError

    def leader_id(self) -> int | None:
        """The id of the current coordinator, or None during an election."""
        raise NotImplementedError
