from cryptography.fernet import Fernet

from ..config import settings


def _fernet() -> Fernet:
    return Fernet(settings.fernet_key.encode())


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    return _fernet().decrypt(data)


def encrypt_file(path: str) -> None:
    with open(path, "rb") as f:
        data = f.read()
    with open(path, "wb") as f:
        f.write(encrypt_bytes(data))


def decrypt_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return decrypt_bytes(f.read())
