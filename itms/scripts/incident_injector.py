import random
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict
import xml.etree.ElementTree as ET

try:
    import traci
except ImportError:
    pass

@dataclass
class InjectionEvent:
    injection_type: str
    edge_id: str
    lane_id: Optional[str]
    start_tick: int
    end_tick: int
    duration_s: int
    vehicle_id: Optional[str]

class IncidentInjector:
    def __init__(self, net_path: str, rng: Optional[random.Random] = None):
        self.rng = rng or random.Random()
        self.net_path = net_path
        
        # Parse non-internal edges
        tree = ET.parse(net_path)
        root = tree.getroot()
        self.valid_edges = []
        for edge in root.findall("edge"):
            eid = edge.get("id")
            if eid and not eid.startswith(":"):
                self.valid_edges.append(eid)
                
        self.planned_events: List[InjectionEvent] = []
        self.active_events: List[InjectionEvent] = []
        self.used_edges = set()
        self.completed_events: List[InjectionEvent] = []

    def plan_injections(self, n_incidents: int = 3, sim_duration: int = 1800,
                        min_start: int = 300, max_start: int = 1500,
                        min_duration: int = 60, max_duration: int = 300) -> List[InjectionEvent]:
        self.planned_events = []
        for _ in range(n_incidents):
            start = self.rng.randint(min_start, max_start)
            duration = self.rng.randint(min_duration, max_duration)
            inj_type = self.rng.choice(["stalled_vehicle", "lane_obstruction"])
            event = InjectionEvent(
                injection_type=inj_type,
                edge_id="", # to be chosen at runtime
                lane_id=None,
                start_tick=start,
                end_tick=start + duration,
                duration_s=duration,
                vehicle_id=None
            )
            self.planned_events.append(event)
        
        self.planned_events.sort(key=lambda x: x.start_tick)
        return self.planned_events

    def apply_tick(self, tick: int) -> List[InjectionEvent]:
        state_changed = []
        
        # Check for ending events
        still_active = []
        for ev in self.active_events:
            if tick >= ev.end_tick:
                # restore
                if ev.injection_type == "stalled_vehicle" and ev.vehicle_id:
                    try:
                        traci.vehicle.setSpeed(ev.vehicle_id, -1)
                    except Exception:
                        pass # vehicle might have left
                elif ev.injection_type == "lane_obstruction" and ev.lane_id:
                    try:
                        traci.lane.setDisallowed(ev.lane_id, [])
                    except Exception:
                        pass
                state_changed.append(ev)
                self.completed_events.append(ev)
            else:
                still_active.append(ev)
                
        self.active_events = still_active
        
        # Check for starting events
        unstarted = []
        for ev in self.planned_events:
            if tick >= ev.start_tick and tick < ev.end_tick and ev.edge_id == "":
                # Try to apply now
                candidate_edges = [e for e in self.valid_edges if e not in self.used_edges]
                self.rng.shuffle(candidate_edges)
                
                applied = False
                for edge in candidate_edges:
                    vehs = traci.edge.getLastStepVehicleIDs(edge)
                    if not vehs:
                        continue
                        
                    ev.edge_id = edge
                    self.used_edges.add(edge)
                    
                    if ev.injection_type == "stalled_vehicle":
                        ev.vehicle_id = self.rng.choice(vehs)
                        ev.lane_id = traci.vehicle.getLaneID(ev.vehicle_id)
                        traci.vehicle.setSpeed(ev.vehicle_id, 0)
                        applied = True
                        break
                    elif ev.injection_type == "lane_obstruction":
                        lanes = []
                        for i in range(traci.edge.getLaneNumber(edge)):
                            lanes.append(f"{edge}_{i}")
                        if lanes:
                            ev.lane_id = self.rng.choice(lanes)
                            traci.lane.setDisallowed(ev.lane_id, ['passenger', 'motorcycle', 'bus', 'truck'])
                            applied = True
                            break
                            
                if applied:
                    self.active_events.append(ev)
                    state_changed.append(ev)
                else:
                    # push start time if we couldn't find an edge with traffic
                    ev.start_tick += 5
                    ev.end_tick += 5
                    unstarted.append(ev)
            else:
                unstarted.append(ev)
                
        self.planned_events = unstarted
        return state_changed

    def active_injections(self, tick: int) -> List[InjectionEvent]:
        return [ev for ev in self.active_events if ev.start_tick <= tick < ev.end_tick]

    @property
    def ground_truth(self) -> List[dict]:
        all_events = self.completed_events + self.active_events + [e for e in self.planned_events if e.edge_id != ""]
        return [asdict(e) for e in all_events]

if __name__ == "__main__":
    print("This module is meant to be imported or tested via TraCI.")
