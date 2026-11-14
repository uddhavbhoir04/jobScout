from cryptography.fernet import Fernet, InvalidToken

from jobscout.config import get_settings


def generate_key() -> str:
    return Fernet.generate_key().decode()


def _fernet() -> Fernet:
    key = get_settings().fernet_key
    if not key:
        raise RuntimeError("FERNET_KEY is not set in .env. Run `jobscout keygen` and paste the key.")
    return Fernet(key.encode())


def encrypt(plain: str) -> bytes:
    return _fernet().encrypt(plain.encode())


def decrypt(token: bytes) -> str:
    try:
        return _fernet().decrypt(bytes(token)).decode()
    except InvalidToken as e:
        raise RuntimeError("Could not decrypt password: FERNET_KEY changed since the account was added.") from e
