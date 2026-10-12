from __future__ import annotations

from itms_domain.incident import IncidentClass
from pydantic import BaseModel


class ConfirmRequest(BaseModel):
    actor: str
    classification: str = IncidentClass.UNKNOWN.value
    detail: str = ""


class RejectRequest(BaseModel):
    actor: str
    detail: str = ""
