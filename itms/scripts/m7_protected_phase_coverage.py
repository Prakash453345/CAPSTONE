"""Did the protected-phase fix silently remove preemption anywhere?

`626e45e` made the live corridor count `protected_movements` instead of
`green_movements` when choosing which phase to preempt onto. Correct --
handing an emergency vehicle a permissive green tells the crew they hold
the junction when they have only been told to yield (D3/A5).

But `_phase_serving` returns None when no phase protects the wanted
movement, and `preemption_plan` then returns None **silently**. So the
question the change raises and nobody has answered: on this corridor, is
there any (junction, movement) an emergency vehicle actually uses that no
phase protects? If so, the fix did not only make preemption safer -- it
removed it there, and nothing says so.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path("/work/itms")
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scenarios" / "networks" / "vijayawada"))
sys.path.insert(0, str(ROOT / "services" / "sim-service"))

import m5_harness as H  # noqa: E402
from link_lanes import link_to_lane_map, link_to_receiving_lane_map  # noqa: E402
from sim_service.control.corridor.junction import protected_phase_for  # noqa: E402
from sim_service.signal_controller.ev_detection import build_movement_index  # noqa: E402

EV_ROUTE = (
    "219187869 350502993#0 350502993#1 350502993#2 350502993#4 "
    "350502993#6 350502993#7 -343269496 343269496"
).split()


def main() -> None:
    configs, _flows, _v, _p = H.scenario_inputs("medium")
    net = str(ROOT / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml")
    index = build_movement_index(link_to_lane_map(net), link_to_receiving_lane_map(net), configs)

    print("=== every junction: how many movements are protected vs merely green ===")
    for tls, cfg in configs.items():
        for pid in cfg.ring_order:
            ph = cfg.phases[pid]
            prot = ph.protected_movements
            perm = ph.green_movements - (prot if prot is not None else ph.green_movements)
            flag = "  <-- permissive present" if perm else ""
            print(f"  {tls[:30]:30s} {pid:3s} green={len(ph.green_movements):2d} "
                  f"protected={'None' if prot is None else len(prot):>4} "
                  f"permissive={len(perm):2d}{flag}")

    print("\n=== the EV route: does every junction have a phase protecting the EV movement? ===")
    lost = []
    for a, b in zip(EV_ROUTE, EV_ROUTE[1:], strict=False):
        hit = index.get((a, b))
        if hit is None:
            continue
        tls, movement = hit
        cfg = configs[tls]
        prot_phase = protected_phase_for(cfg, movement)
        # what the LIVE path would now choose, for the same movement
        wanted = frozenset({movement})
        best, best_overlap = None, 0
        for pid in cfg.ring_order:
            ph = cfg.phases[pid]
            prot = (
                ph.protected_movements
                if ph.protected_movements is not None
                else ph.green_movements
            )
            ov = len(prot & wanted)
            if ov > best_overlap:
                best, best_overlap = pid, ov
        # what the OLD (pre-fix) live path would have chosen
        old, old_overlap = None, 0
        for pid in cfg.ring_order:
            ov = len(cfg.phases[pid].green_movements & wanted)
            if ov > old_overlap:
                old, old_overlap = pid, ov
        status = "OK" if best else "*** NO PROTECTED PHASE -> preemption silently dropped ***"
        if not best:
            lost.append((tls, movement, old))
        print(f"  {tls[:30]:30s} mv={movement:4s} "
              f"benchmarked_path={str(prot_phase):5s} live_new={str(best):5s} "
              f"live_old={str(old):5s}  {status}")

    print(f"\n{'=' * 70}")
    if lost:
        print(f"{len(lost)} junction(s) on the EV route lose preemption under the fix:")
        for tls, mv, old in lost:
            print(f"   {tls}  movement {mv}  (old code would have used phase {old})")
    else:
        print("No junction on this EV route loses preemption: every movement the")
        print("emergency vehicle uses is protected by some phase. The fix is a")
        print("pure safety tightening here -- but that is a property of THIS")
        print("route on THIS network, not a guarantee, and nothing reports the")
        print("case if it ever does occur.")


if __name__ == "__main__":
    main()
