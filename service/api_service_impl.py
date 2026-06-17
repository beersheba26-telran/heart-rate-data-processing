from model.service_types import InputData, LlmInputData
from service.api_service import APIService


class _ApiServiceImpl(APIService):
    def getPatientData(self, patientId: str):
        # Implementation to retrieve patient data by patient ID
        pass

    def getPatientsOfDoctor(self, doctorId: str):
        # Implementation to retrieve a list of patients associated with a doctor
        pass

    def getDataForHeartRateDistribution(self, inputData: InputData):
        # Implementation to retrieve data for heart rate distribution
        pass

    def getDataForJumpDistribution(self, inputData: InputData):
        # Implementation to retrieve data for jump distribution
        pass

    def getLlmResponse(self, inputData: LlmInputData):
        # Implementation to retrieve response from LLM based on the input data
        pass