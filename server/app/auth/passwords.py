"""Argon2id password hashing with enumeration-resistant verification."""

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

# Public, non-secret hash used only to equalize unknown-user verification cost.
DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$wagCPXjifGVmRjZ4aHFIZXc$"
    "CYaIb8sB+wtD+Vu/P4uod1+Qof8h+1g7bbDlBID48Rc"
)


class PasswordService:
    def __init__(self) -> None:
        self._password_hash = PasswordHash.recommended()

    def hash(self, password: str) -> str:
        return self._password_hash.hash(password)

    def verify(self, password: str, password_hash: str | None) -> bool:
        candidate_hash = password_hash or DUMMY_PASSWORD_HASH
        try:
            return self._password_hash.verify(password, candidate_hash)
        except UnknownHashError:
            return False
