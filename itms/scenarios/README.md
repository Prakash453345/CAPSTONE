# scenarios

Executable acceptance tests `[ARCH §23]`, build guide §8.4: each scenario is a
YAML file of network + demand + scripted injections + assertions, runnable in CI.

- `networks/` — `.net.xml` road networks (synthetic grid first, then a real OSM
  extract of the chosen 9–16 junction area, build guide M1).
- `demand/` — `.rou.xml` traffic demand.
- `suite/` — the scenario YAML files themselves.

`networks/vijayawada/` has the first real network (M1): the MG Road corridor,
Benz Circle to PNBS, 16 junctions — see its own README for how it was built and
why that scope, not the whole city.

`demand/vijayawada/` has the first real demand (M1): 708 vehicles over a
30-minute window (seed 42), generated via `randomTrips.py` + `duarouter` —
see its own README for why this is explicitly *not* calibrated OD demand
(that's build guide §8.5, deferred to M8.5) and what it's for instead
(demonstrating the M1 gate, not drawing real conclusions).

`suite/` is still empty — it grows from **M2** onward as each milestone's
gate criteria become scenario assertions (build guide §5, the case atlas —
aim for ~40 scenarios covering it by M9).
