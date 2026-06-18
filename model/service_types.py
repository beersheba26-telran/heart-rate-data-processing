from dataclasses import dataclass


@dataclass
class InputData:
    patientId: str
    startDateTime: str # ISO String
    endDateTime: str # ISO String
    intervalDuration: int # Duration of the time interval in seconds

@dataclass
class PatientData:
    patientId: str
    name: str
    email: str
    weight: float
    height: float
    age: int

@dataclass
class HeartRateData:
    heartRateMedium: float # medium pulse value at the given time interval
    timestampStart: float # Epoch time in seconds   
    intervalDuration: int # Duration of the time interval in seconds
    
@dataclass
class JumpData:
    jumpPercentAvg: int # average percentage of jumps at the given time interval
    timestampStart: float # Epoch time in seconds   
    intervalDuration: int # Duration of the time interval in seconds    
    
