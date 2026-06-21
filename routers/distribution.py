from typing import Any

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, model_validator

from model.service_types import InputData
from service import api_service

router = APIRouter(prefix="/distribution", tags=["distribution"])


class DistributionRequest(BaseModel):
    patientId: str = Field(min_length=1)
    startDateTime: datetime
    endDateTime: datetime
    intervalDuration: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_date_range(self) -> "DistributionRequest":
        if self.startDateTime > self.endDateTime:
            raise ValueError("startDateTime must be before or equal to endDateTime")
        return self

    def to_input_data(self) -> InputData:
        return InputData(
            patientId=self.patientId,
            startDateTime=self.startDateTime.isoformat(),
            endDateTime=self.endDateTime.isoformat(),
            intervalDuration=self.intervalDuration,
        )


@router.post("/heart_rate")
def get_heart_rate_distribution(payload: DistributionRequest, request: Request) -> list[dict[str, Any]]:
    input_data = payload.to_input_data()
    current_user_id = str(request.scope.get("user_id", "")).strip()
    heart_rate_data = api_service.getDataForHeartRateDistribution(input_data, current_user_id)
    return [asdict(item) for item in heart_rate_data]


@router.post("/jumps")
def get_jump_distribution(payload: DistributionRequest, request: Request) -> list[dict[str, Any]]:
    input_data = payload.to_input_data()
    current_user_id = str(request.scope.get("user_id", "")).strip()
    jump_data = api_service.getDataForJumpDistribution(input_data, current_user_id)
    return [asdict(item) for item in jump_data]
@router.post("/llm_response")
def get_llm_response(payload: DistributionRequest, request: Request) -> dict[str, str]:
    input_data = payload.to_input_data()
    current_user_id = str(request.scope.get("user_id", "")).strip()
    llm_response = api_service.getLlmResponse(input_data, current_user_id)
    return {"llm_response": llm_response}   
