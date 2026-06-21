import os
import base64
import binascii
import json
from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app_exceptions import NotFoundException
from app_logger import logger
from routers.distribution import router as distribution_router
from routers.patients import router as patients_router

app = FastAPI(title="Dashboard Patient Info API")

# Explicit list of path prefixes that require user context in request scope.
# Current behavior: protect all existing API routes except /health.
AUTH_REQUIRED_PATH_PREFIXES: tuple[str, ...] = (
	"/patients",
	"/distribution",
)


class AuthorizationDecisionException(Exception):
	def __init__(self, status_code: int, detail: str):
		super().__init__(detail)
		self.status_code = status_code
		self.detail = detail


def _decode_jwt_payload(token: str) -> dict:
	parts = token.split(".")
	if len(parts) != 3:
		return {}

	payload_segment = parts[1]
	padding = "=" * (-len(payload_segment) % 4)
	try:
		decoded_payload = base64.urlsafe_b64decode(payload_segment + padding)
		payload = json.loads(decoded_payload.decode("utf-8"))
	except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
		return {}

	if not isinstance(payload, dict):
		return {}

	return payload


def _extract_user_context_from_jwt(request: Request) -> dict[str, str] | None:
	user_context: dict[str, str] | None = None
	authorization = request.headers.get("authorization")
	if not authorization:
		logger.debug("No Authorization header present")
	elif not authorization.lower().startswith("bearer "):
		logger.debug("Authorization header is not Bearer")
	else:
		token = authorization.split(" ", 1)[1].strip()
		if not token:
			logger.debug("Bearer token is empty")
		else:
			payload = _decode_jwt_payload(token)
			if not payload:
				logger.debug("JWT payload could not be decoded")
			else:
				# Cognito contract:
				# - username -> user_id
				# - cognito:groups contains DOCTOR -> role DOCTOR, otherwise PATIENT
				user_id = payload.get("username")
				if not isinstance(user_id, str) or not user_id.strip():
					logger.debug("JWT payload missing valid username claim")
				else:
					groups = payload.get("cognito:groups")
					group_names: list[str] = []
					if isinstance(groups, list):
						group_names = [str(group).strip().upper() for group in groups if str(group).strip()]

					role = "DOCTOR" if "DOCTOR" in group_names else "PATIENT"
					user_context = {"user_id": user_id.strip(), "role": role}
					logger.debug("User context extracted from JWT for user_id={}, role={}", user_context["user_id"], role)

	return user_context


def _is_auth_protected_endpoint(request: Request, protected_paths: tuple[str, ...]) -> bool:
	path = request.url.path
	is_options_request = request.method == "OPTIONS"
	is_protected_by_prefix = any(path == prefix or path.startswith(f"{prefix}/") for prefix in protected_paths)
	should_protect = (not is_options_request) and is_protected_by_prefix
	return should_protect

app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=False,
	allow_methods=["*"],
	allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
	logger.info("Dashboard Patient Info API started")


@app.middleware("http")
async def role_authorization_middleware(request: Request, call_next: Callable):
	response = None
	try:
		if _is_auth_protected_endpoint(request, AUTH_REQUIRED_PATH_PREFIXES):
			user_id = request.scope.get("user_id")
			role = request.scope.get("role")
			if not user_id or not role:
				raise AuthorizationDecisionException(status_code=401, detail="Missing user context")

			role = str(role).upper()
			if role != "DOCTOR":
				raise AuthorizationDecisionException(status_code=403, detail="Forbidden")

		response = await call_next(request)
	except AuthorizationDecisionException as exc:
		response = await authorization_decision_exception_handler(request, exc)
	return response


@app.middleware("http")
async def user_context_middleware(request: Request, call_next: Callable):
	user_context = _extract_user_context_from_jwt(request)

	if user_context:
		request.scope["user_id"] = user_context["user_id"]
		request.scope["role"] = user_context["role"].upper()

	return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
	logger.warning("Validation error on {}: {}", request.url.path, exc.errors())
	return JSONResponse(status_code=400, content={"detail": exc.errors()})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
	logger.warning("HTTP error on {}: {}", request.url.path, exc.detail)
	return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(AuthorizationDecisionException)
async def authorization_decision_exception_handler(request: Request, exc: AuthorizationDecisionException) -> JSONResponse:
	logger.warning("Authorization decision error on {}: {}", request.url.path, exc.detail)
	return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(NotFoundException)
async def not_found_exception_handler(request: Request, exc: NotFoundException) -> JSONResponse:
	logger.warning("Not found on {}: {}", request.url.path, exc.detail)
	return JSONResponse(status_code=404, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
	logger.exception("Unhandled error on {}", request.url.path)
	return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health() -> dict[str, str]:
	return {"status": "ok"}

app.include_router(patients_router)
app.include_router(distribution_router)
