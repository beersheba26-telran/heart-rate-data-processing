from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app_logger import logger
from routers.distribution import router as distribution_router
from routers.patients import router as patients_router

app = FastAPI(title="Dashboard Patient Info API")


@app.on_event("startup")
async def startup_event() -> None:
	logger.info("Dashboard Patient Info API started")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
	logger.warning("Validation error on {}: {}", request.url.path, exc.errors())
	return JSONResponse(status_code=400, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
	logger.exception("Unhandled error on {}", request.url.path)
	return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health() -> dict[str, str]:
	return {"status": "ok"}

app.include_router(patients_router)
app.include_router(distribution_router)
