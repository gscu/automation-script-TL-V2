"""
Storage helper for the eHealth portal password.

The password is encrypted with Windows DPAPI (CryptProtectData) before it
is written into the report scripts, and decrypted again at run time.
DPAPI encryption is tied to the current Windows user on the current
machine, which means:

  - No plain-text password sits in the .py files anymore.
  - Scheduled tasks can still decrypt it (they run as the same user).
  - A copied folder on another machine/user CANNOT decrypt it - re-run
    setup.bat (or the app's Options window) there to store it again.

Encrypted values are stored as "ENC:<base64>". Values without that prefix
are passed through unchanged, so a hand-edited plain-text password keeps
working exactly like before.
"""

import base64

ENC_PREFIX = "ENC:"


def _win32crypt():
    """win32crypt is imported lazily so this module still loads before
    pywin32 has been installed (e.g. at the very start of a fresh setup)."""
    try:
        import win32crypt
        return win32crypt
    except ImportError:
        return None


def dpapi_available() -> bool:
    return _win32crypt() is not None


def protect(plain_password: str) -> str:
    """Returns the value to store inside the report scripts.

    Encrypts with DPAPI when available; otherwise returns the password
    unchanged (legacy plain-text behavior) so setup never dead-ends.
    Values that already carry the ENC: prefix are returned as-is.
    """
    if not plain_password or plain_password.startswith(ENC_PREFIX):
        return plain_password

    crypt = _win32crypt()
    if crypt is None:
        return plain_password

    blob = crypt.CryptProtectData(
        plain_password.encode("utf-8"),
        "eHealth portal password",
        None, None, None, 0,
    )
    return ENC_PREFIX + base64.b64encode(blob).decode("ascii")


def reveal(stored_value: str) -> str:
    """Returns the plain password from a stored value.

    Values without the ENC: prefix are returned as-is. A value that cannot
    be decrypted (different machine/user, corrupted blob) raises a
    RuntimeError with instructions, so the failure is obvious instead of
    the portal just rejecting a wrong password.
    """
    if not stored_value or not stored_value.startswith(ENC_PREFIX):
        return stored_value

    crypt = _win32crypt()
    if crypt is None:
        raise RuntimeError(
            "The saved eHealth password is encrypted but pywin32 is not "
            "installed. Run setup.bat to install the required packages."
        )

    try:
        _description, plain = crypt.CryptUnprotectData(
            base64.b64decode(stored_value[len(ENC_PREFIX):]),
            None, None, None, 0,
        )
        return plain.decode("utf-8")
    except Exception as error:
        raise RuntimeError(
            "The saved eHealth password could not be decrypted on this "
            "machine/user account. Re-enter it by running setup.bat or "
            "the manager app's Options window."
        ) from error


def try_reveal(stored_value: str) -> str:
    """Like reveal(), but returns "" instead of raising - used to pre-fill
    the Options window without crashing on a foreign machine."""
    try:
        return reveal(stored_value)
    except RuntimeError:
        return ""
