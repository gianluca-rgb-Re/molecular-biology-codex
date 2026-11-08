"""Revisão espaçada simples e transparente (variante simplificada do SM-2).

Entrada: avaliação (0 Errei, 1 Difícil, 2 Bom, 3 Fácil) e confiança declarada ANTES
de ver a resposta (1 Chutei, 2 Razoável, 3 Tenho certeza).

Regras (intervalos em dias):
  Errei   -> reps=0, intervalo=1, facilidade -0.20 (-0.30 se a confiança era 3: erro com alta confiança)
  Difícil -> intervalo = max(1, round(intervalo*1.2)), facilidade -0.15
  Bom     -> reps 0: 1 dia; reps 1: 3 dias; depois round(intervalo*facilidade)
  Fácil   -> reps 0: 3 dias; reps 1: 6 dias; depois round(intervalo*facilidade*1.3); facilidade +0.15
  Se a resposta foi Bom/Fácil mas a confiança era 1 (acerto por chute), o intervalo é multiplicado por 0,6.
Facilidade mínima: 1,3. Inicial: 2,5.
"""
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass

RATINGS = {0: "Errei", 1: "Difícil", 2: "Bom", 3: "Fácil"}
CONFIDENCE = {1: "Chutei", 2: "Razoável", 3: "Tenho certeza"}


@dataclass
class CardState:
    ease: float = 2.5
    interval: int = 0
    reps: int = 0
    lapses: int = 0
    due: str = ""          # AAAA-MM-DD ("" = nunca revisado)


def schedule(state: CardState, rating: int, confidence: int = 2, today: dt.date | None = None) -> CardState:
    today = today or dt.date.today()
    ease, interval, reps, lapses = state.ease, state.interval, state.reps, state.lapses
    if rating <= 0:
        reps, interval, lapses = 0, 1, lapses + 1
        ease = max(1.3, ease - (0.30 if confidence >= 3 else 0.20))
    elif rating == 1:
        interval = max(1, round(max(interval, 1) * 1.2))
        ease = max(1.3, ease - 0.15)
        reps += 1
    elif rating == 2:
        interval = 1 if reps == 0 else 3 if reps == 1 else max(1, round(interval * ease))
        reps += 1
    else:
        interval = 3 if reps == 0 else 6 if reps == 1 else max(1, round(interval * ease * 1.3))
        ease += 0.15
        reps += 1
    if rating >= 2 and confidence <= 1:
        interval = max(1, round(interval * 0.6))
    due = today + dt.timedelta(days=interval)
    return CardState(round(ease, 2), interval, reps, lapses, due.isoformat())


def preview_interval(state: CardState, rating: int, confidence: int = 2) -> int:
    return schedule(state, rating, confidence).interval
