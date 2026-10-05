"""Auto-load chain: sends a fixed sequence of foundation payloads to the PS5 in order,
pausing between each so the console has time to initialize it before the next one lands.

The sequence and its delays come from the same ``payloads-catalog.json`` metadata bundled
with the Trainers feature (``autoload_priority`` / ``autoload_delay_ms`` per entry):

    kstuff-lite   priority 0   delay 3000 ms   kernel R/W primitive, must load first
    CheatRunner   priority 5   delay  500 ms   on-console cheat engine, needs kstuff loaded

Both steps reuse the app's normal payload pipeline (:class:`HttpDownloadService` for the
fetch+cache, :class:`PayloadTcpSender` for the TCP send) — this is not a new delivery
mechanism, just the two existing single-payload senders run back to back with the catalog's
own recommended pacing between them.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from app.services.xeno.cheatrunner_release_service import CheatRunnerReleaseService
from app.services.xeno.kstuff_elf_release_service import KstuffElfReleaseService

StepCallback = Callable[[str, int, int], None]
"""``(step_label, step_index_1_based, step_count)`` — fired when a step starts."""


@dataclass(frozen=True)
class AutoLoadStep:
    label: str
    delay_after_ms: int


AUTO_LOAD_STEPS = (
    AutoLoadStep(label="kstuff", delay_after_ms=3000),
    AutoLoadStep(label="CheatRunner", delay_after_ms=500),
)


class AutoLoaderService:
    def __init__(
        self,
        kstuff: KstuffElfReleaseService,
        cheatrunner: CheatRunnerReleaseService,
    ) -> None:
        self._kstuff = kstuff
        self._cheatrunner = cheatrunner

    def run(
        self,
        *,
        host: str,
        port: int,
        is_android: bool,
        on_step: Optional[StepCallback] = None,
        progress: Optional[Callable[[object], None]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        total = len(AUTO_LOAD_STEPS)
        for index, step in enumerate(AUTO_LOAD_STEPS, start=1):
            if on_step is not None:
                on_step(step.label, index, total)
            if step.label == "kstuff":
                self._kstuff.send(host=host, port=port, is_android=is_android, progress=progress)
            elif step.label == "CheatRunner":
                self._cheatrunner.send(host=host, port=port, is_android=is_android, progress=progress)
            else:  # pragma: no cover - defensive, AUTO_LOAD_STEPS is fixed above
                raise RuntimeError(f"Etapa de carregamento automático desconhecida: {step.label}")
            if step.delay_after_ms > 0:
                sleep(step.delay_after_ms / 1000.0)
