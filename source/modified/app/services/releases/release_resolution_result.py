from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar


Item = TypeVar("Item")


@dataclass(frozen=True)
class ReleaseResolutionResult(Generic[Item]):
    """Itens resolvidos e prova de que todas as origens terminaram a consulta."""

    items: tuple[Item, ...]
    complete: bool
