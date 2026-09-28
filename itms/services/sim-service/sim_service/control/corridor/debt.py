"""What a preemption owes the movements it stopped, and how that debt is
repaid.

Preemption's cost is not paid by the network. It is paid by a specific,
identifiable set of movements -- the ones held on red -- and the same ones
every time, because preemption density is highest near fire stations and
hospitals. The literature is unusually clear about the size of the bill
and unusually quiet about who receives it. Reno's comparison of five EVP
exit strategies found that EVP "tends to worsen arterial and intersection
operations for **all five**"; a Route 7 hardware-in-the-loop study reported
a 1.6% average travel-time increase and then explicitly cautioned that the
figure came from wide intersection spacing, long cycles and platoon
dispersion, and "may not generalize to corridors with closer intersection
spacing, shorter cycles" -- which describes this corridor; and Plano
measured 10 to 20 minutes to return to normal near hospitals at peak.

A mean travel-time number cannot represent that. Averaging a cost that
lands entirely on one set of movements across every movement is precisely
the operation that makes the burden invisible, which is H9's point: report
EVP performance as a distribution, not a mean.

This module does two things with that observation.

**Measurement.** A ledger, per junction per movement, of seconds spent on
red while a preemption ran at that junction. That is a directly observed
quantity, not a model, and it is what the benchmark reports instead of --
not alongside -- a corridor average.

**Control.** The ledger is also readable by the controller, as pressure
term `D(p)` in A-CA-MP. This is the part that differs from the exit-
strategy literature. Reno's five strategies are all one-shot decisions:
which phase to return to at the instant the preemption ends. "Return to
the most delayed phase" is the closest of them to this idea and it is
still a single choice made once, after which the controller forgets that
the preemption happened. A decaying debt makes the repayment continuous
and proportional: a movement held for 30 seconds carries more claim than
one held for 4, the claim is spent as the movement is served, and it is
gone by the time the next preemption arrives rather than accumulating
into a permanent bias.

The decay is what keeps it a *repayment* rather than a grudge. Without
one, a movement near a fire station would accumulate unbounded priority
and the controller would optimise the corridor for the cross street of
the busiest EVP junction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


class DebtLedger:
    """Per-junction, per-movement preemption debt in PCU-seconds-equivalent
    units of "seconds held on red by a preemption".

    Deliberately *not* seconds-times-queue. A movement held on red with an
    empty approach was not harmed, but weighting the debt by the queue
    present at the time would make the debt largest exactly where the
    receiving-link congestion already makes `𝒫(p)` largest, double-counting
    a quantity the pressure function measures directly and better. The
    debt's job is to carry information the live state has *lost* -- that
    this movement was denied service for a reason unconnected to its own
    demand -- so it counts only the denial."""

    def __init__(self, *, half_life_s: float = 120.0) -> None:
        self._half_life_s = max(1e-6, half_life_s)
        self._debt: dict[tuple[str, str], float] = {}
        self._last_decay_s: float = 0.0
        self._total_incurred_s: dict[str, float] = {}
        """Undecayed running total per movement, for reporting. The
        decayed value drives control; the raw total is what H9's
        distribution is built from, and a decayed number cannot answer
        "how much service did this movement lose today"."""

    def incur(self, junction_id: str, movements: Iterable[str], seconds: float) -> None:
        for movement in movements:
            key = (junction_id, movement)
            self._debt[key] = self._debt.get(key, 0.0) + seconds
            self._total_incurred_s[f"{junction_id}/{movement}"] = (
                self._total_incurred_s.get(f"{junction_id}/{movement}", 0.0) + seconds
            )

    def repay(self, junction_id: str, movements: Iterable[str], seconds: float) -> None:
        """Extinguish debt by actually serving the movement.

        **This is what makes the ledger a repayment rather than a mood,
        and its absence was a real defect measured on the corridor.**

        The first version had `incur` and `decay_to` and nothing else, so
        a movement's debt fell only with the clock and never registered
        that the service had been given back. Two consequences, both
        wrong. A movement served ten times still carried the same debt as
        one never served at all — so `D(p)` could not distinguish "owed"
        from "already repaid", which is the single distinction it exists
        to make. And with a 120 s half-life, debt from a preemption at
        t=300 takes about 2,900 s to fall below the ledger's own cull
        threshold, which is longer than the whole scenario.

        Instrumented on one seed, `D(p)` was non-zero on **82.9% of
        ticks** — 9,493 of 11,458. Not the rare, low-leverage term it was
        designed as, but a persistent phase-asymmetric bias that never
        switched off, sitting underneath every decision the controller
        made for the rest of the run. That is the shape M4's `S(p)` had,
        arrived at from the opposite direction: not a constant that never
        scaled, but a decaying quantity that never cleared.

        One second of green repays one second of lost green, so the unit
        is exact rather than a conversion factor. Debt is now bounded
        between the preemption that incurred it and the service that
        settles it, which is the window the term was always meant to
        occupy."""
        if seconds <= 0.0:
            return
        for movement in movements:
            key = (junction_id, movement)
            remaining = self._debt.get(key)
            if remaining is None:
                continue
            remaining -= seconds
            if remaining <= 1e-6:
                del self._debt[key]
            else:
                self._debt[key] = remaining

    def decay_to(self, now_s: float) -> None:
        """Exponential decay to `now_s`, driven by elapsed simulation time
        rather than by tick count.

        Time-driven and not tick-driven because this ledger is read on
        every tick but written only during preemption, and a junction that
        is skipped while mid-transition (`runner.py` `continue`s past one)
        would otherwise decay more slowly than its neighbours purely
        because it was busy.

        Kept alongside `repay` rather than replaced by it. Decay handles
        the debt that repayment cannot reach: a movement whose demand
        diverted to a parallel route (G6) may never present a queue to be
        served, and its claim should lapse rather than wait forever for a
        repayment that will not be asked for."""
        elapsed = now_s - self._last_decay_s
        if elapsed <= 0.0:
            return
        self._last_decay_s = now_s
        factor = 0.5 ** (elapsed / self._half_life_s)
        for key in list(self._debt):
            value = self._debt[key] * factor
            if value < 1e-6:
                del self._debt[key]
            else:
                self._debt[key] = value

    def owed(self, junction_id: str, movement: str) -> float:
        return self._debt.get((junction_id, movement), 0.0)

    def owed_to_phase(self, junction_id: str, movements: Iterable[str]) -> float:
        return sum(self.owed(junction_id, m) for m in movements)

    def report(self) -> Mapping[str, float]:
        """Undecayed seconds of preemption-caused red per movement -- the
        distribution H9 asks for, not a corridor mean."""
        return dict(self._total_incurred_s)
