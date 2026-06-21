from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from service import api_service

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("/{id}")
def get_patient_by_id(id: str, request: Request) -> dict[str, Any]:
    current_user_id = str(request.scope.get("user_id", "")).strip()

    try:
        patient = api_service.getPatientData(id, current_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return asdict(patient)


@router.get("/doctor/{id}")
def get_patients_of_doctor(id: str, request: Request) -> list[dict[str, Any]]:
    current_user_id = str(request.scope.get("user_id", "")).strip()

    if id != current_user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    patients = api_service.getPatientsOfDoctor(current_user_id)
    return [asdict(patient) for patient in patients]
