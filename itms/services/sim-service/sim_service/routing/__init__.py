"""Dynamic emergency routing [project direction: DYNAMIC EMERGENCY ROUTING].

    RoutePlanner
        -> RouteCostModel   (the ITMS-specific part: the alpha..zeta cost
                             framework from itms_domain.EmergencyRoutingConfig,
                             each component normalised, anomaly-impact-aware,
                             signal-delay-aware, explainable)
        -> GraphSearchEngine (a standard weighted shortest-path search over the
                              SUMO connection graph -- the search *mechanism*,
                              not a claimed contribution)

`routing/` takes plain data (a `RoadGraph` built once from the .net.xml, and a
per-edge `EdgeConditions` snapshot). Sampling live SUMO / active `Anomaly`
objects into `EdgeConditions` is the caller's job (`sim_service/live/`), so the
planner stays pure and unit-testable without SUMO.
"""

from sim_service.routing.cost import EdgeConditions, EdgeCostParts, RouteCostModel
from sim_service.routing.graph import EdgeInfo, RoadGraph
from sim_service.routing.planner import NoRouteError, RoutePlanner
from sim_service.routing.search import GraphSearchEngine, SearchResult

__all__ = [
    "EdgeConditions",
    "EdgeCostParts",
    "EdgeInfo",
    "GraphSearchEngine",
    "NoRouteError",
    "RoadGraph",
    "RouteCostModel",
    "RoutePlanner",
    "SearchResult",
]
