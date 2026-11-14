"""Sign up / log in / log out with an httpOnly session cookie."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from jobscout.config import get_settings
from jobscout.db.models import User
from jobscout.db.session import new_session
from jobscout.security import users
from jobscout.security.ratelimit import LOGIN_PER_ACCOUNT, LOGIN_PER_IP, REGISTER_PER_IP, limiter

COOKIE = "jobscout_session"
router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class SignUp(Credentials):
    name: str | None = Field(default=None, max_length=120)


def user_dict(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "is_paid": u.is_paid,
            "plan": "paid" if u.is_paid else "free"}


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=users.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=get_settings().cookie_secure, path="/")  # COOKIE_SECURE=true in production (https)


def current_user(request: Request) -> User:
    with new_session() as s:
        user = users.user_for_token(s, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(401, "Please log in.")
    return user


def client_ip(request: Request) -> str:
    """The browser's IP. X-Forwarded-For is trusted only when the API is private behind the Next.js
    server (INTERNAL_API_KEY set), which overwrites it; otherwise anyone could fake it."""
    if get_settings().internal_api_key:
        fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if fwd:
            return fwd
    return request.client.host if request.client else "unknown"


def _throttle(key: str, rule: tuple[int, int]) -> None:
    wait = limiter.hit(key, *rule)
    if wait:
        minutes = max(1, round(wait / 60))
        raise HTTPException(429, f"Too many attempts. Try again in {minutes} minute{'s' if minutes > 1 else ''}.",
                            headers={"Retry-After": str(int(wait))})


@router.post("/register", status_code=201)
def register(body: SignUp, request: Request, response: Response):
    _throttle(f"register:{client_ip(request)}", REGISTER_PER_IP)
    with new_session() as s:
        try:
            user = users.create_user(s, body.email, body.password, body.name)
        except users.AuthError as e:
            raise HTTPException(400, str(e))
        _set_cookie(response, users.start_session(s, user))
        return user_dict(user)


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    ip = client_ip(request)
    account_key = f"login:{users.normalise_email(body.email)}:{ip}"
    _throttle(f"login-ip:{ip}", LOGIN_PER_IP)
    _throttle(account_key, LOGIN_PER_ACCOUNT)
    with new_session() as s:
        try:
            user = users.authenticate(s, body.email, body.password)
        except users.AuthError as e:
            raise HTTPException(401, str(e))
        limiter.reset(account_key)  # a correct password clears this email's failed attempts
        _set_cookie(response, users.start_session(s, user))
        return user_dict(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    with new_session() as s:
        users.end_session(s, request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=get_settings().cookie_secure)


def paid_user(user: User = Depends(current_user)) -> User:
    """RBAC: features that cost money (LLM + email sending) are for paid users only."""
    if not user.is_paid:
        raise HTTPException(403, "Email outreach is available on the paid plan.")
    return user


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_dict(user)


profile_router = APIRouter(prefix="/api", tags=["auth"])


@profile_router.get("/profile")
def profile(user: User = Depends(current_user)):
    """The logged-in user's profile, including their plan (is_paid)."""
    return user_dict(user)
