# Finding and notifying the nearest crew

When an anomaly is created (or an operator asks for a unit), dispatch has to answer
"which free ambulance / police / fire crew is closest?" and tell that crew. This is
the same problem a ride-hailing app solves for drivers, and it is solved the same
way.

## The method: hexagons, then road time

1. **Hex index.** The map is divided into H3 hexagonal cells (resolution 8, edge about
   460 m). Every crew sits in one cell; the index is a dict `cell -> crews`
   (`sim_service/control/dispatch/crew_index.py`).
2. **Ring search.** A call looks at its own cell, then the ring around it, then the
   next, and stops one ring after it has `k` candidates (`k = 5`). Work depends on
   how many cells were visited, not on how many crews exist. Hexagons, not squares,
   because every neighbour of a hexagon is equally far, so a ring is a fair circle.
3. **Road time.** Straight-line distance is only a shortlist: the Krishna river
   makes a crew 400 m away 6 km by road. The shortlist is re-ranked by live
   travel time from SUMO's router (`rank_by_road_time`) and the fastest is sent.
   That is better than Uber's pure H3 distance would be here, because emergency
   crews are few and a wrong pick costs minutes.
4. **Notify.** The chosen crew gets a request addressed to its vehicle id. The crew
   page is subscribed to the same live stream as the console, so the call appears
   on that crew's screen as it is created; the phone vibrates and, with voice on,
   the destination is read out (`useNewCallAlert`). The other shortlisted crews are
   listed on the `emergency.dispatched` event (`notified`) so the operator can see
   who was considered and why this one was picked.

Crews are marked busy while they have a request and freed when it ends (arrival,
cancel, or failed routing).

## Who is a crew

`app_user.unit_kind` (`ambulance` | `police` | `fire_truck`) says what a crew account
drives, next to `unit_id`, the vehicle it is bound to. The crew page shows only that
vehicle's call and only that vehicle on the map. Operators dispatch by *kind*
("Send: Ambulance / Police / Fire truck" on the map) and see every unit.

## What is not built

- **Accept / decline with timeout.** Today the nearest crew is assigned directly.
  An Uber-style offer (ping the nearest, wait ~15 s, fall through to the next on
  the `notified` shortlist) needs a crew response channel; the shortlist is
  already in the right order for it.
- **Live crew GPS.** Units are simulated at their depots (hospitals for
  ambulances, OSM police stations). `IncidentResponseOrchestrator.register_crew` /
  `update_crew_position` are where a crew's phone location would feed the index; a
  position update only touches the index when the crew changes cell.
- **Fire crews.** There is no fire-station data in the OSM extract, so no fire unit
  exists until one is registered; a call for one reports it under
  `undispatched_kinds`.
