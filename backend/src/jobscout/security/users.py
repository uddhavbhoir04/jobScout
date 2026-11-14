"""App users: password hashing (stdlib scrypt), sign-up, login sessions."""
import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from jobscout.db.models import Account, Contact, Post, ScrapeRun, User, UserSession
from jobscout.extract.dates import now

SESSION_DAYS = 30
MIN_PASSWORD = 8
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=64)
    b64 = lambda b: base64.b64encode(b).decode()
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        check = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                               dklen=len(base64.b64decode(digest)))
        return hmac.compare_digest(check, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


class AuthError(ValueError):
    pass


def normalise_email(email: str) -> str:
    return email.strip().lower()


def create_user(session: Session, email: str, password: str, name: str | None = None) -> User:
    email = normalise_email(email)
    if "@" not in email:
        raise AuthError("Enter a valid email address.")
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.")
    if session.scalar(select(User).where(User.email == email)):
        raise AuthError("An account with this email already exists.")
    first_user = not session.scalar(select(func.count()).select_from(User))
    user = User(email=email, name=(name or "").strip() or None, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    if first_user:
        adopt_orphans(session, user.id)
    session.commit()
    return user


def adopt_orphans(session: Session, user_id: int) -> None:
    """Data created before users existed (user_id NULL) goes to the first user."""
    for model in (Account, ScrapeRun, Post, Contact):
        session.execute(update(model).where(model.user_id.is_(None)).values(user_id=user_id))


def authenticate(session: Session, email: str, password: str) -> User:
    user = session.scalar(select(User).where(User.email == normalise_email(email)))
    if not user or not verify_password(password, user.password_hash):
        raise AuthError("Wrong email or password.")
    return user


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(session: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    session.add(UserSession(user_id=user.id, token_hash=_token_hash(token),
                            expires_at=now() + timedelta(days=SESSION_DAYS)))
    session.commit()
    return token


def user_for_token(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    return session.scalar(
        select(User).join(UserSession, UserSession.user_id == User.id)
        .where(UserSession.token_hash == _token_hash(token), UserSession.expires_at > now())
    )


def end_session(session: Session, token: str | None) -> None:
    if token:
        row = session.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
        if row:
            session.delete(row)
            session.commit()
