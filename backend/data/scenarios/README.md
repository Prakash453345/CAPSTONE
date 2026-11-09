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

## Any road network (2026-09-29)

Nothing downstream is tied to the corridor any more. `build_scenario.py` makes
a scenario from **any** SUMO network — one it generates (grids, radial rings,
irregular random streets, left- or right-hand traffic) or one you give it, such
as an OpenStreetMap export converted with `netconvert`:

```bash
python data/scenarios/build_scenario.py --generate grid:3x3,300,2 --lefthand --out data/scenarios/generated/grid3_lh
python data/scenarios/build_scenario.py --net my_city.net.xml --out data/scenarios/generated/my_city
ITMS_SCENARIO=data/scenarios/generated/my_city python scripts/m8_closed_loop_gate.py ...
ITMS_SCENARIO=data/scenarios/generated/my_city make dev     # the live services too
```

- **Demand levels are set by load, not by a trip rate:** the busiest
  junction's flow ratio `Y` (what `webster.compute_timing` reports as
  `degree_of_saturation`; lost time not counted, so 1.0 is past capacity).
  The defaults are light 0.25, medium 0.5 and heavy 1.0, which is where the
  corridor's own levels measure (0.245, 0.471, 0.996). Webster's nominal
  saturation flow overstates what a single lane shared with turning traffic
  carries, so on such roads a level is heavier than its number says.
- **What the builder does:** it signalises every junction where three or more
  roads meet. It routes the demand, applies the vehicle mix (`--mix india`,
  the corridor's, or `cars`) and plans the cameras.
- **Where the setting lives:** `ITMS_SCENARIO` is read by
  `itms_domain.scenario`, which every service and harness asks. Unset, it is
  the Vijayawada corridor, exactly as before.
- **Any real city, one command:** `city_from_osm.py` downloads the area
  (SUMO's `osmGet.py`; needs ordinary internet access, which the build
  sandbox does not have), converts it with the corridor's netconvert options,
  caps speeds at 50 km/h as the corridor does, places lights and builds the
  scenario:

  ```bash
  python scenarios/city_from_osm.py --bbox 78.4390,17.4300,78.4560,17.4420 \
      --name hyderabad_ameerpet --lefthand   # an example area; not run here
  python scenarios/city_from_osm.py --osm area.osm.xml --name area --lefthand
  ```

  OpenStreetMap marks few signals in Indian cities (one in the whole
  Vijayawada extract; netconvert's own guess adds three), so a junction also
  gets a light where three or more of the roads entering it are tertiary or
  above (`--signal-class`, `--signal-approaches`). `scenario.json` records
  the source, the netconvert command and the rule.
  SUMO also ships real-city networks, and `build_scenario.py --net` takes
  them as they are (gzipped too):

  ```bash
  S=$SUMO_HOME/tools/game
  python data/scenarios/build_scenario.py --net $S/DRT/osm.net.xml --name berlin_adlershof \
      --out data/scenarios/generated/berlin_adlershof --mix cars --no-cameras
  python data/scenarios/build_scenario.py --net $S/fkk_in/ingolstadt.net.xml.gz --name ingolstadt \
      --out data/scenarios/generated/ingolstadt --mix cars --no-cameras
  ```
- **The web map** starts on the Vijayawada corridor. For another city, start
  it with `VITE_MAP_CENTER="<lat>,<lon>"` — the builder writes the value as
  `map_center` in `scenario.json` (null for a generated network, which is not
  on the globe).

### What had to change for other networks

Nothing in the controller was retuned. What broke on other networks was how
a network was *read*; each fix leaves the corridor's configuration and results
unchanged (checked bit-for-bit):

- **A road cut into several edges** (a turn bay, a lane-count change, an
  OpenStreetMap tag change) was measured only on its last edge before the
  stop line — 4 m on the turn-bay grid, where the controller then did 2.2x
  Webster's delay. `itms_domain.lane_chains` measures the road back to the
  previous real junction (simulator sampler, camera estimator, live services).
- **Signal programs** list more than phases. `itms_domain.signal_program`
  skips change intervals (any amber or red+amber, even while one movement
  stays green), the pedestrian clearance inside a stage, and repeats.
- **Link numbering**: a light over several junctions (`--tls.join`), or one
  edited to number its links its own way, takes its conflicts from its own
  program instead of a junction's `<request>` rows.
