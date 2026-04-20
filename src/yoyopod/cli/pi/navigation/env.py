"""Navigation soak environment helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
import os


@contextmanager
def _temporary_env_var(name: str, value: str | None) -> Iterator[None]:
    """Temporarily override one environment variable."""

    previous = os.environ.get(name)
    if value is None:
        yield
        return

    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous
