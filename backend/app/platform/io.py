"""Dispatch a whole synchronous operation through the assembly's I/O policy."""

from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


async def dispatch_io(platform, function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """DB operations use their own bounded threads; fake operations stay inline.

    Callers pass a complete repository transaction or synchronous business method,
    rather than dispatching individual SQL statements across different threads.
    """
    runner = getattr(platform, "run_io", None)
    if runner is not None:
        return await runner(function, *args, **kwargs)
    return function(*args, **kwargs)
