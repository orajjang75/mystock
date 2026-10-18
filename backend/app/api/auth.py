import secrets

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    username: str


def _matches(given: str, expected: str) -> bool:
    return secrets.compare_digest(given.encode(), expected.encode())


@router.post("/login")
def login(body: LoginRequest, request: Request) -> UserResponse:
    settings = get_settings()
    # Evaluate both comparisons so timing does not reveal which field was wrong.
    user_ok = _matches(body.username, settings.app_username)
    password_ok = _matches(body.password, settings.app_password.get_secret_value())
    if not (user_ok and password_ok):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    request.session.clear()
    request.session["user"] = settings.app_username
    return UserResponse(username=settings.app_username)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
def me(user: CurrentUser) -> UserResponse:
    return UserResponse(username=user)
