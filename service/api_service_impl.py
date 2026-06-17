from dotenv import load_dotenv
import json
import os
from datetime import date, datetime
from statistics import median

import boto3
from pymongo import MongoClient
from psycopg_pool import ConnectionPool

from model.service_types import HeartRateData, InputData, JumpData, LlmInputData, PatientData
from service.api_service import APIService

load_dotenv()


class _ApiServiceImpl(APIService):
    def __init__(self, dsn: str | None = None):
        self._dsn = dsn or self._load_dsn_from_secrets_manager()
        self._pool = ConnectionPool(conninfo=self._dsn, min_size=1, max_size=10, open=True)
        mongo_client = MongoClient(os.getenv("MONGO_URI"))
        self._heart_rate_collection = mongo_client[os.getenv("MONGO_DB_NAME")][os.getenv("REDUCED_VALUES_COLLECTION")]
        self._jumps_collection = mongo_client[os.getenv("MONGO_DB_NAME")][os.getenv("JUMPS_VALUES_COLLECTION")]

    def _load_dsn_from_secrets_manager(self) -> str:
        secret_id = os.getenv("DB_SECRET_ID")
        region_name = os.getenv("AWS_REGION") or "us-east-1"

        client = boto3.client("secretsmanager", region_name=region_name)
        secret_response = client.get_secret_value(SecretId=secret_id)
        return json.loads(secret_response["SecretString"])["URI"]

    @staticmethod
    def _calculate_age(birthdate: date | None) -> int:
        if birthdate is None:
            return 0

        today = date.today()
        return today.year - birthdate.year - (
            (today.month, today.day) < (birthdate.month, birthdate.day)
        )

    def _get_device_id_by_patient_id(self, patient_id: str) -> str | None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM public.devices WHERE patient_id = %s LIMIT 1",
                    (patient_id,),
                )
                row = cur.fetchone()

        if row is None:
            return None

        return row[0]

    def _get_heart_rate_documents(self, device_id: str, inputData: InputData) -> list[dict]:
        return list(
            self._heart_rate_collection.find(
                {
                    "device_id": device_id,
                    "date": {"$gte": inputData.startDateTime, "$lte": inputData.endDateTime},
                },
                {"pulse_value": 1, "date": 1, "_id": 0},
            ).sort("date", 1)
        )

    @staticmethod
    def _build_heart_rate_data(
        pulse_value: float,
        timestamp_start: float,
        interval_duration: int,
    ) -> HeartRateData:
        return HeartRateData(
            heartRateMedium=pulse_value,
            timestampStart=timestamp_start,
            intervalDuration=interval_duration,
        )

    def _build_heart_rate_data_from_document(
        self,
        document: dict,
        interval_duration: int,
    ) -> HeartRateData:
        return self._build_heart_rate_data(
            pulse_value=float(document["pulse_value"]),
            timestamp_start=datetime.fromisoformat(document["date"]).timestamp(),
            interval_duration=interval_duration,
        )

    @staticmethod
    def _get_source_interval_duration(documents: list[dict]) -> float:
        first_document_time = datetime.fromisoformat(documents[0]["date"])
        second_document_time = datetime.fromisoformat(documents[1]["date"])
        return (second_document_time - first_document_time).total_seconds()

    def _aggregate_heart_rate_documents(
        self,
        documents: list[dict],
        interval_duration: int,
    ) -> list[HeartRateData]:
        heart_rate_data: list[HeartRateData] = []
        bucket_start = datetime.fromisoformat(documents[0]["date"])
        bucket_values: list[float] = []

        for document in documents:
            document_time = datetime.fromisoformat(document["date"])
            if bucket_values and (document_time - bucket_start).total_seconds() >= interval_duration:
                heart_rate_data.append(
                    self._build_heart_rate_data(
                        pulse_value=float(median(bucket_values)),
                        timestamp_start=bucket_start.timestamp(),
                        interval_duration=interval_duration,
                    )
                )
                bucket_start = document_time
                bucket_values = []

            bucket_values.append(float(document["pulse_value"]))

        heart_rate_data.append(
            self._build_heart_rate_data(
                pulse_value=float(median(bucket_values)),
                timestamp_start=bucket_start.timestamp(),
                interval_duration=interval_duration,
            )
        )

        return heart_rate_data

    def _get_jump_documents(self, device_id: str, inputData: InputData) -> list[dict]:
        return list(
            self._jumps_collection.find(
                {
                    "device_id": device_id,
                    "date": {"$gte": inputData.startDateTime, "$lte": inputData.endDateTime},
                },
                {"current_pulse_value": 1, "previous_pulse_value": 1, "date": 1, "_id": 0},
            ).sort("date", 1)
        )

    @staticmethod
    def _compute_jump_percent(document: dict) -> float:
        return abs(document["current_pulse_value"] - document["previous_pulse_value"]) / document["previous_pulse_value"] * 100

    def _build_jump_data(
        self,
        jump_percent_avg: float,
        timestamp_start: float,
        interval_duration: int,
    ) -> JumpData:
        return JumpData(
            jumpPercentAvg=round(jump_percent_avg),
            timestampStart=timestamp_start,
            intervalDuration=interval_duration,
        )

    def _build_jump_data_from_document(self, document: dict, interval_duration: int) -> JumpData:
        return self._build_jump_data(
            jump_percent_avg=self._compute_jump_percent(document),
            timestamp_start=datetime.fromisoformat(document["date"]).timestamp(),
            interval_duration=interval_duration,
        )

    def _aggregate_jump_documents(self, documents: list[dict], interval_duration: int) -> list[JumpData]:
        jump_data: list[JumpData] = []
        bucket_start = datetime.fromisoformat(documents[0]["date"])
        bucket_values: list[float] = []

        for document in documents:
            document_time = datetime.fromisoformat(document["date"])
            if bucket_values and (document_time - bucket_start).total_seconds() >= interval_duration:
                jump_data.append(
                    self._build_jump_data(
                        jump_percent_avg=float(median(bucket_values)),
                        timestamp_start=bucket_start.timestamp(),
                        interval_duration=interval_duration,
                    )
                )
                bucket_start = document_time
                bucket_values = []

            bucket_values.append(self._compute_jump_percent(document))

        jump_data.append(
            self._build_jump_data(
                jump_percent_avg=float(median(bucket_values)),
                timestamp_start=bucket_start.timestamp(),
                interval_duration=interval_duration,
            )
        )

        return jump_data

    def getPatientData(self, patientId: str) -> PatientData:
        query = """
            SELECT id, name, email, weight, height, birthdate
            FROM public.patients
            WHERE id = %s
        """

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (patientId,))
                row = cur.fetchone()

        if row is None:
            raise ValueError(f"Patient with id '{patientId}' was not found")

        patient_id, name, email, weight, height, birthdate = row
        return PatientData(
            patientId=patient_id,
            name=name or "",
            email=email or "",
            weight=float(weight) if weight is not None else 0.0,
            height=float(height) if height is not None else 0.0,
            age=self._calculate_age(birthdate),
        )

    def getPatientsOfDoctor(self, doctorId: str) -> list[PatientData]:
        query = """
            SELECT p.id, p.name, p.email, p.weight, p.height, p.birthdate
            FROM public.patients p
            JOIN public.doctor_patient dp ON dp.patient_id = p.id
            WHERE dp.doctor_id = %s
        """

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (doctorId,))
                rows = cur.fetchall()

        return [
            PatientData(
                patientId=row[0],
                name=row[1] or "",
                email=row[2] or "",
                weight=float(row[3]) if row[3] is not None else 0.0,
                height=float(row[4]) if row[4] is not None else 0.0,
                age=self._calculate_age(row[5]),
            )
            for row in rows
        ]

    def getDataForHeartRateDistribution(self, inputData: InputData) -> list[HeartRateData]:
        device_id = self._get_device_id_by_patient_id(inputData.patientId)
        documents = [] if device_id is None else self._get_heart_rate_documents(device_id, inputData)

        if not documents:
            heart_rate_data = []
        elif len(documents) == 1:
            heart_rate_data = [
                self._build_heart_rate_data_from_document(
                    documents[0],
                    inputData.intervalDuration,
                )
            ]
        elif inputData.intervalDuration <= self._get_source_interval_duration(documents):
            heart_rate_data = [
                self._build_heart_rate_data_from_document(doc, inputData.intervalDuration)
                for doc in documents
            ]
        else:
            heart_rate_data = self._aggregate_heart_rate_documents(
                documents,
                inputData.intervalDuration,
            )

        return heart_rate_data

    def getDataForJumpDistribution(self, inputData: InputData) -> list[JumpData]:
        device_id = self._get_device_id_by_patient_id(inputData.patientId)
        documents = [] if device_id is None else self._get_jump_documents(device_id, inputData)

        if not documents:
            jump_data = []
        elif len(documents) == 1:
            jump_data = [self._build_jump_data_from_document(documents[0], inputData.intervalDuration)]
        elif inputData.intervalDuration <= self._get_source_interval_duration(documents):
            jump_data = [
                self._build_jump_data_from_document(doc, inputData.intervalDuration)
                for doc in documents
            ]
        else:
            jump_data = self._aggregate_jump_documents(documents, inputData.intervalDuration)

        return jump_data

    def getLlmResponse(self, inputData: LlmInputData):
        # Implementation to retrieve response from LLM based on the input data
        pass


api_service: APIService = _ApiServiceImpl()