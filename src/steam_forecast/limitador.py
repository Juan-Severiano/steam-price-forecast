"""Intervalo mínimo entre chamadas à Steam, com jitter. Relógio e sono são injetáveis para teste."""

from __future__ import annotations

import random
import time
from collections.abc import Callable


class Limitador:
    def __init__(
        self,
        intervalo_s: float,
        jitter_s: float = 0.0,
        *,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
        sorteio: Callable[[], float] = random.random,
    ) -> None:
        if intervalo_s < 0 or jitter_s < 0:
            raise ValueError("intervalo e jitter não podem ser negativos")
        self.intervalo_s = intervalo_s
        self.jitter_s = jitter_s
        self._relogio = relogio
        self._dormir = dormir
        self._sorteio = sorteio
        self._proximo = 0.0

    def esperar(self) -> float:
        """Bloqueia até a próxima chamada ser permitida e devolve quanto esperou."""
        agora = self._relogio()
        espera = max(0.0, self._proximo - agora)
        if espera > 0:
            self._dormir(espera)
        self._proximo = max(agora, self._proximo) + self.intervalo_s + self.jitter_s * self._sorteio()
        return espera
