from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException

from service import api_service

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("/{id}")
def get_patient_by_id(id: str) -> dict[str, Any]:
    try:
        patient = api_service.getPatientData(id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return asdict(patient)


@router.get("/doctor/{id}")
def get_patients_of_doctor(id: str) -> list[dict[str, Any]]:
    patients = api_service.getPatientsOfDoctor(id)
    return [asdict(patient) for patient in patients]
