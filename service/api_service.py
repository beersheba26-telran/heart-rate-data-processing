from abc import ABC, abstractmethod

from model.service_types import HeartRateData, InputData, JumpData, LlmInputData, PatientData
class APIService(ABC):
    @abstractmethod
    def getPatientData(self, patientId: str) -> PatientData:
        '''
        Get patient data by patient ID.
        '''
    @abstractmethod
    def getPatientsOfDoctor(self, doctorId: str) -> list[PatientData]:
        '''
        Get a list of patients associated with a doctor.
        '''
    @abstractmethod
    def getDataForHeartRateDistribution(self, inputData: InputData) -> list[HeartRateData]:
        '''
        Get data for heart rate distribution.
        '''
    @abstractmethod    
    def getDataForJumpDistribution(self, inputData: InputData) -> list[JumpData]:
        '''
        Get data for jump distribution.
        ''' 
    @abstractmethod    
    def getLlmResponse(self, inputData: LlmInputData) -> str:
        '''
        Get response from LLM based on the input data.
        '''    
        