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

`demand/` and `suite/` are still empty. `demand/` gets its first real content
once M1's TraCI loop needs vehicles to actually generate (next up); `suite/`
grows from **M2** onward as each milestone's gate criteria become scenario
assertions (build guide §5, the case atlas — aim for ~40 scenarios covering it
by M9).
