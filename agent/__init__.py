"""Coding agent package.

``run_task`` and ``TaskResult`` are re-exported lazily so that importing a
lightweight submodule (e.g. ``agent.llm``) does not load the RAG stack.
"""

__all__ = ["TaskResult", "run_task"]


def __getattr__(name):
    if name in __all__:
        from agent import agent as _agent

        return getattr(_agent, name)
    raise AttributeError(f"module 'agent' has no attribute {name!r}")
