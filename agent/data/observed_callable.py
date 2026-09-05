from collections.abc import Callable
from typing import Any


class ObservedCallable:
    def __init__(self, observed: Callable[..., Any], original: Callable[..., Any]) -> None:
        self._observed = observed
        self._original = original

    def __call__(self, *args, **kwargs):
        return self._observed(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._original, name)
