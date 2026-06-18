from dataclasses import asdict
from typing import Any

from fastapi import Body, FastAPI, HTTPException

from model.service_types import InputData
from service import api_service

app = FastAPI(title="Dashboard Patient Info API")


def _build_input_data(payload: dict[str, Any]) -> InputData:
    try:
        return InputData(
            patientId=str(payload["patientId"]),
            startDateTime=str(payload["startDateTime"]),
            endDateTime=str(payload["endDateTime"]),
            intervalDuration=int(payload["intervalDuration"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid input payload") from exc


@app.get("/patients/{id}")
def get_patient_by_id(id: str) -> dict[str, Any]:
    try:
        patient = api_service.getPatientData(id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return asdict(patient)


@app.get("/patients/doctor/{id}")
def get_patients_of_doctor(id: str) -> list[dict[str, Any]]:
    patients = api_service.getPatientsOfDoctor(id)
    return [asdict(patient) for patient in patients]


@app.post("/distribution/heart_rate")
def get_heart_rate_distribution(payload: dict[str, Any] = Body(...)) -> list[dict[str, Any]]:
    input_data = _build_input_data(payload)
    heart_rate_data = api_service.getDataForHeartRateDistribution(input_data)
    return [asdict(item) for item in heart_rate_data]


@app.post("/distribution/jumps")
def get_jump_distribution(payload: dict[str, Any] = Body(...)) -> list[dict[str, Any]]:
    input_data = _build_input_data(payload)
    jump_data = api_service.getDataForJumpDistribution(input_data)
    return [asdict(item) for item in jump_data]
