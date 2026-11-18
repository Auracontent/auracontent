"""Courbes d'accélération (x de 0 à 1 -> progression). « smooth » = le smoothstep du moteur linework."""
from __future__ import annotations

import math


def smooth(x: float) -> float:
    return x * x * (3 - 2 * x)


def linear(x: float) -> float:
    return x


def out(x: float) -> float:
    """Départ rapide, arrivée douce (cubique)."""
    return 1 - (1 - x) ** 3


def back(x: float) -> float:
    """Arrivée avec un léger dépassement puis retour (élan)."""
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def bounce(x: float) -> float:
    """Rebond à l'arrivée (objet qui tombe et rebondit)."""
    n1, d1 = 7.5625, 2.75
    if x < 1 / d1:
        return n1 * x * x
    if x < 2 / d1:
        x -= 1.5 / d1
        return n1 * x * x + 0.75
    if x < 2.5 / d1:
        x -= 2.25 / d1
        return n1 * x * x + 0.9375
    x -= 2.625 / d1
    return n1 * x * x + 0.984375


def spring(x: float) -> float:
    """Ressort amorti (petite oscillation qui se stabilise)."""
    if x in (0.0, 1.0):
        return x
    return 1 - math.exp(-6 * x) * math.cos(10 * x)


EASINGS = {"smooth": smooth, "linear": linear, "out": out, "back": back, "bounce": bounce, "spring": spring}


def ease(name: str | None, x: float) -> float:
    x = max(0.0, min(1.0, x))
    return EASINGS.get(name or "smooth", smooth)(x)
