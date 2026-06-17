# FastAPI controller and uvicorn WEB service
## Add following endpoints calling appropriate API service methods
### /patients/:id
- GET request
- Path variable "id" is a patient ID
- calls getPatientData API service method
- returns PatientData by patient ID
### /patients/doctor/:id
- GET request
- Path variable "id" is a doctor ID
- calls getPatientsOfDctor API service method
- returns list of PatientData objects adhered to the doctor by doctor ID
### /distribution/heart_rate
- POST request
- body should be consistent with InputData (no validation is required at this step)
- based on body the object of InputData should be created
- calls getDataForHeartRateDistribution 
- returns list of HeartRateData objects
### /distribution/jumps
- POST request
- body should be consistent with InputData (no validation is required at this step)
- based on body the object of InputData should be created
- calls getDataForJumpDistribution 
- returns list of JumpData objects
## Test the existing functionality using Postman