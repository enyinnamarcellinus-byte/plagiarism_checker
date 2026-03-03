from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from .services.crypto import decrypt_bytes, encrypt_bytes


class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_bytes(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_bytes(value.encode()).decode()
