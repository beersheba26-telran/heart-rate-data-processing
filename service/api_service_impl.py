from dotenv import load_dotenv
import json
import os
from datetime import date, datetime
from statistics import mean, median, pstdev

import boto3
from pymongo import MongoClient
from psycopg_pool import ConnectionPool
from app_logger import logger
from model.service_types import HeartRateData, InputData, JumpData,  PatientData
from service.api_service import APIService
import openai

try:
    load_dotenv()
except UnicodeDecodeError:
    # Support UTF-16 .env files that may be saved by some editors on Windows.
    load_dotenv(encoding="utf-16")


class _ApiServiceImpl(APIService):
    def __init__(self, dsn: str | None = None):
        secret_values = self._load_secret_values_from_secrets_manager()
        self._dsn = dsn or secret_values["URI"]
        self._pool = ConnectionPool(conninfo=self._dsn, min_size=1, max_size=10, open=True)
        mongo_client = MongoClient(secret_values["MONGO_URI"])
        self._heart_rate_collection = mongo_client[secret_values["MONGO_DB_NAME"]][secret_values["REDUCED_VALUES_COLLECTION"]]
        self._jumps_collection = mongo_client[secret_values["MONGO_DB_NAME"]][secret_values["JUMPS_VALUES_COLLECTION"]]
        self.openai_client = openai.OpenAI()
        self.model_name = os.getenv("MODEL_NAME", "openai.gpt-oss-20b")
    def _load_secret_values_from_secrets_manager(self) -> dict:
        secret_id = os.getenv("DB_SECRET_ID")
        region_name = os.getenv("AWS_REGION") or "us-east-1"

        client = boto3.client("secretsmanager", region_name=region_name)
        secret_response = client.get_secret_value(SecretId=secret_id)
        return json.loads(secret_response["SecretString"])

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

    @staticmethod
    def _set_current_user_id_for_rls(cur, currentUserId: str) -> None:
        cur.execute(
            "SELECT set_config('app.current_user_id', %s, true)",
            (currentUserId,),
        )

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

    def _get_latest_pulse_values(self, device_id: str, nValues: int) -> list[float]:
        if nValues <= 0:
            return []

        latest_values = list(
            self._heart_rate_collection.find(
                {"device_id": device_id},
                {"pulse_value": 1, "date": 1, "_id": 0},
            ).sort("date", -1).limit(nValues)
        )

        latest_values.reverse()
        return [float(lv["pulse_value"]) for lv in latest_values]

    def _get_latest_jump_percent_values(self, device_id: str, nValues: int) -> list[float]:
        if nValues <= 0:
            return []

        latest_values = list(
            self._jumps_collection.find(
                {"device_id": device_id},
                {"current_pulse_value": 1, "previous_pulse_value": 1, "date": 1, "_id": 0},
            ).sort("date", -1).limit(nValues)
        )

        latest_values.reverse()
        jump_percents: list[float] = []
        for value in latest_values:
            previous_pulse_value = float(value["previous_pulse_value"])
            if previous_pulse_value == 0:
                continue
            jump_percents.append(
                self._round_metric(
                    self._compute_jump_percent(value)
                )
            )

        return jump_percents

    @staticmethod
    def _compute_jump_percent(document: dict) -> float:
        return _ApiServiceImpl._compute_jump_percent_values(
            float(document["current_pulse_value"]),
            float(document["previous_pulse_value"]),
        )

    @staticmethod
    def _compute_jump_percent_values(current_pulse_value: float, previous_pulse_value: float) -> float:
        return abs(current_pulse_value - previous_pulse_value) / previous_pulse_value * 100

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

    def getPatientData(self, patientId: str, currentUserId: str) -> PatientData:
        query = """
            SELECT p.id, p.name, p.email, p.weight, p.height, p.birthdate
            FROM public.patients p
            JOIN public.doctor_patient dp ON dp.patient_id = p.id
            WHERE p.id = %s
              AND dp.doctor_id = %s
        """

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                self._set_current_user_id_for_rls(cur, currentUserId)
                cur.execute(query, (patientId, currentUserId))
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

    def getPatientsOfDoctor(self, currentUserId: str) -> list[PatientData]:
        query = """
            SELECT p.id, p.name, p.email, p.weight, p.height, p.birthdate
            FROM public.patients p
            JOIN public.doctor_patient dp ON dp.patient_id = p.id
            WHERE dp.doctor_id = %s
        """

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                self._set_current_user_id_for_rls(cur, currentUserId)
                cur.execute(query, (currentUserId,))
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
        else:
            jump_data = self._aggregate_jump_documents(documents, inputData.intervalDuration)

        return jump_data

    @staticmethod
    def _round_metric(value: float) -> float:
        return round(value, 2)

    def _build_pulse_statistics(self, device_id: str,inputData: InputData) -> dict[str, float | int]:
       
        documents = [] if device_id is None else self._get_heart_rate_documents(device_id, inputData)

        if not documents:
            return {
                "measurements_count": 0,
                "min_pulse": 0,
                "max_pulse": 0,
                "avg_pulse": 0.0,
                "std_deviation": 0.0,
            }

        pulse_values = [float(document["pulse_value"]) for document in documents]

        return {
            "measurements_count": len(pulse_values),
            "min_pulse": min(pulse_values),
            "max_pulse": max(pulse_values),
            "avg_pulse": self._round_metric(mean(pulse_values)),
            "std_deviation": self._round_metric(pstdev(pulse_values)) if len(pulse_values) > 1 else 0.0,
        }

    def _build_jump_statistics(self, device_id: str, inputData: InputData) -> dict[str, float | int]:
        documents = self._get_jump_documents(device_id, inputData)
        jump_percents: list[float] = []

        for document in documents:
            previous_pulse_value = float(document["previous_pulse_value"])
            if previous_pulse_value == 0:
                continue
            jump_percents.append(self._compute_jump_percent(document))

        if not jump_percents:
            return {
                "avg_jump_in_percents": 0.0,
                "count_jumps_percent_gt_40": 0,
                "jumps_std_deviation": 0.0,
            }

        return {
            "avg_jump_in_percents": self._round_metric(mean(jump_percents)),
            "count_jumps_percent_gt_40": sum(1 for value in jump_percents if value > 40),
            "jumps_std_deviation": self._round_metric(pstdev(jump_percents)) if len(jump_percents) > 1 else 0.0,
        }
    def _call_llm_api(self, summary: dict) -> str:
        try:
            completion = self.openai_client.chat.completions.create(
                model=self.model_name,
                temperature=0.2,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a cardiology data analyst. Analyze heart-rate patterns,\
                                identify trends, anomalies, possible data-quality issues,\
                                    and provide explanations. "
                            
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "short response not more than 100 words about behavior pattern based on this telemetry payload (JSON):\n"
                            f"{json.dumps(summary, ensure_ascii=True)}"
                        ),
                    },
                ],
            )

            message = completion.choices[0].message.content
            return message.strip() if message else ""
        except Exception:
            logger.exception("Failed to get LLM response from OpenAI API")
            raise (RuntimeError("Failed to get LLM response from OpenAI API") )
        
    def getLlmResponse(self, inputData: InputData) -> str:
        device_id = self._get_device_id_by_patient_id(inputData.patientId)
        if device_id is None:
            logger.warning(f"No device found for patient {inputData.patientId}")
            return ""
        pulseValuesStatistics = self._build_pulse_statistics(device_id, inputData)
        logger.debug(f"LLM response requested for patient {inputData.patientId} with pulse statistics: {pulseValuesStatistics}")
        jumps_statistics = self._build_jump_statistics(device_id, inputData)
        logger.debug(f"LLM response requested for patient {inputData.patientId} with jump statistics: {jumps_statistics}")   
        lastPulseValues = self._get_latest_pulse_values(device_id, nValues=5)
        lastJumpValues = self._get_latest_jump_percent_values(device_id, nValues=5)
        summary = {
            "pulse_values_statistics": pulseValuesStatistics,
            "instant_jumps_statistics": jumps_statistics,
            "last_pulse_values": lastPulseValues,
            "last_instant_jump_values": lastJumpValues
        }
        logger.debug(f"LLM response summary for patient {inputData.patientId}: {summary}")
        response = self._call_llm_api(summary)
        logger.debug(f"LLM response for patient {inputData.patientId}: {response}")
        return response


api_service: APIService = _ApiServiceImpl()