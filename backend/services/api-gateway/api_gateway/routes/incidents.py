from __future__ import annotations

from fastapi import APIRouter, Depends

from api_gateway.controllers import incidents
from api_gateway.core.security import require_api_key

router = APIRouter(prefix="/v1/incidents", tags=["incidents"])
operator_only = [Depends(require_api_key)]

router.add_api_route("", incidents.list_incidents, methods=["GET"])
router.add_api_route("/{incident_id}", incidents.get_incident, methods=["GET"])
router.add_api_route("/{incident_id}/confirm", incidents.confirm_incident, methods=["POST"],
                     dependencies=operator_only)
router.add_api_route("/{incident_id}/reject", incidents.reject_incident, methods=["POST"],
                     dependencies=operator_only)
