from __future__ import annotations

from fastapi import APIRouter, Depends

from api_gateway.controllers import incidents
from api_gateway.core.security import operator_only, require_reviewer

router = APIRouter(prefix="/v1/incidents", tags=["incidents"])
reviewer_only = [Depends(require_reviewer)]
signed_in = [Depends(operator_only)]

router.add_api_route("", incidents.list_incidents, methods=["GET"], dependencies=signed_in)
router.add_api_route("/{incident_id}", incidents.get_incident, methods=["GET"],
                     dependencies=signed_in)
router.add_api_route("/{incident_id}/confirm", incidents.confirm_incident, methods=["POST"],
                     dependencies=reviewer_only)
router.add_api_route("/{incident_id}/reject", incidents.reject_incident, methods=["POST"],
                     dependencies=reviewer_only)
