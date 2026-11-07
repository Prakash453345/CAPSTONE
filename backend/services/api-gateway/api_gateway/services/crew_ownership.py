"""Which crew each live call and emergency trip belongs to.

A crew account may answer its own call and ask for a new route for its own
trip -- not anyone else's. The commands it sends name only an `offer_id` or a
`request_id`, and every signed-in page sees those ids on the live stream, so
the gateway has to know whose they are before letting a crew act on one.

It learns that from the bus, as the relay passes events through:

* `CrewOfferUpdated`         offer_id   -> unit_id (the crew being asked)
* `EmergencyRequestUpdated`  request_id -> vehicle_id
* `EmergencyVehicleUpdated`  request_id -> vehicle_id (sent every tick while a
                             unit is on the move, so it is relearned quickly
                             after a gateway restart)

A crew's vehicle id is its account's `unit_id` (sim-service dispatches a crew
under `vehicle_id=offer.unit_id`). Ids it has not seen yet are refused rather
than guessed: fail closed, the page can try again on the next update.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

# Enough for a long shift's worth of calls; the oldest are forgotten first.
_LIMIT = 5000


class _Bounded:
    def __init__(self, limit: int) -> None:
        self._items: OrderedDict[str, str] = OrderedDict()
        self._limit = limit

    def put(self, key: str, value: str) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self._limit:
            self._items.popitem(last=False)

    def get(self, key: str) -> str | None:
        return self._items.get(key)


class CrewOwnership:
    def __init__(self, limit: int = _LIMIT) -> None:
        self._offers = _Bounded(limit)
        self._requests = _Bounded(limit)
        self._lock = threading.Lock()

    def apply_event(self, event_type: str, payload: dict) -> None:
        if event_type == "CrewOfferUpdated":
            offer_id, unit = payload.get("offer_id"), payload.get("unit_id")
            if offer_id and unit:
                with self._lock:
                    self._offers.put(str(offer_id), str(unit))
        elif event_type in ("EmergencyRequestUpdated", "EmergencyVehicleUpdated"):
            request_id, vehicle = payload.get("request_id"), payload.get("vehicle_id")
            if request_id and vehicle:
                with self._lock:
                    self._requests.put(str(request_id), str(vehicle))

    def offer_unit(self, offer_id: str) -> str | None:
        with self._lock:
            return self._offers.get(offer_id)

    def request_unit(self, request_id: str) -> str | None:
        with self._lock:
            return self._requests.get(request_id)
