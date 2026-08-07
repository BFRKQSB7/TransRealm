"""Credential resolvers for ``env:`` and ``wincred:`` references.

Secrets are never logged or persisted. Resolver error messages contain only
the referenced variable/target name or a Win32 error number, never the secret
value. The Windows resolver reads via the stdlib ``ctypes`` binding of
``advapi32.CredReadW``, so no third-party credential backend is required.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

from transrealm.adapters.errors import AdapterAuthenticationError
from transrealm.adapters.protocol import CredentialResolver

_CRED_TYPE_GENERIC = 1
_ERROR_NOT_FOUND = 1168


class EnvironmentResolver:
    """Resolve ``env:VAR_NAME`` against the current process environment."""

    async def resolve(self, reference: str) -> str:
        """Return the value of the referenced environment variable."""
        if not reference.startswith("env:"):
            raise AdapterAuthenticationError(
                f"Expected an env: credential reference, got {reference!r}.",
            )
        var_name = reference[len("env:"):]
        if var_name not in os.environ:
            raise AdapterAuthenticationError(
                f"Environment variable {var_name!r} is not set.",
            )
        return os.environ[var_name]


class WindowsCredentialResolver:
    """Resolve ``wincred:TARGET`` from the Windows Credential Manager.

    The target must name a generic credential (``CRED_TYPE_GENERIC``) whose
    blob is the secret text. Reads happen lazily at resolve time and the value
    stays in memory only for the lifetime of the request.
    """

    async def resolve(self, reference: str) -> str:
        """Return the secret stored under the referenced Windows credential."""
        if not reference.startswith("wincred:"):
            raise AdapterAuthenticationError(
                f"Expected a wincred: credential reference, got {reference!r}.",
            )
        target = reference[len("wincred:"):]
        blob = self._read_credential(target)
        if blob is None:
            raise AdapterAuthenticationError(
                f"Windows credential {target!r} was not found.",
            )
        try:
            return blob.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AdapterAuthenticationError(
                "Windows credential does not contain valid UTF-8 text.",
            ) from exc

    def _credential_exists(self, target: str) -> bool:
        """Return whether a non-empty generic credential exists for ``target``.

        Like :meth:`_read_credential` this checks the Windows Credential Manager
        lazily, but it never copies the credential blob into memory — only its
        size is examined. An absent or empty credential is ``False``.
        """
        if sys.platform != "win32":
            raise AdapterAuthenticationError(
                "Windows Credential Manager is only available on Windows.",
            )
        advapi32 = _load_advapi32()
        cred = ctypes.POINTER(_CREDENTIALW)()
        ok = advapi32.CredReadW(
            target,
            _CRED_TYPE_GENERIC,
            0,
            ctypes.byref(cred),
        )
        if not ok:
            error = ctypes.get_last_error()
            if error == _ERROR_NOT_FOUND:
                return False
            raise AdapterAuthenticationError(
                f"Failed to read Windows credential (Win32 error {error}).",
            )
        try:
            return int(cred.contents.CredentialBlobSize) > 0
        finally:
            advapi32.CredFree(cred)

    def _read_credential(self, target: str) -> bytes | None:
        """Read a generic credential blob by target name, or None when absent."""
        if sys.platform != "win32":
            raise AdapterAuthenticationError(
                "Windows Credential Manager is only available on Windows.",
            )
        advapi32 = _load_advapi32()
        cred = ctypes.POINTER(_CREDENTIALW)()
        ok = advapi32.CredReadW(
            target,
            _CRED_TYPE_GENERIC,
            0,
            ctypes.byref(cred),
        )
        if not ok:
            error = ctypes.get_last_error()
            if error == _ERROR_NOT_FOUND:
                return None
            raise AdapterAuthenticationError(
                f"Failed to read Windows credential (Win32 error {error}).",
            )
        try:
            size = cred.contents.CredentialBlobSize
            if size == 0:
                return b""
            return ctypes.string_at(cred.contents.CredentialBlob, size)
        finally:
            advapi32.CredFree(cred)


def build_resolver(credential_reference: str | None) -> CredentialResolver | None:
    """Return the resolver for a credential reference, or None when unset."""
    if credential_reference is None:
        return None
    if credential_reference.startswith("env:"):
        return EnvironmentResolver()
    if credential_reference.startswith("wincred:"):
        return WindowsCredentialResolver()
    raise ValueError(
        f"Unsupported credential reference scheme: {credential_reference!r}.",
    )


def credential_reference_is_available(reference: str | None) -> bool:
    """Return whether the referenced credential is present and non-empty here.

    Read-only and never returns the secret value; used to surface an actionable
    hint when an imported Project references a credential that is absent or
    empty on this machine (``04`` §7). ``env:`` references check the process
    environment and ``wincred:`` references check the Windows Credential
    Manager. ``None`` (no credential required) is always available.
    """
    if reference is None:
        return True
    if reference.startswith("env:"):
        var = reference[len("env:"):]
        return var in os.environ and os.environ[var] != ""
    if reference.startswith("wincred:"):
        try:
            return WindowsCredentialResolver()._credential_exists(
                reference[len("wincred:"):],
            )
        except AdapterAuthenticationError:
            return False
    return False


class _CREDENTIALW(ctypes.Structure):
    """Native layout of the Win32 ``CREDENTIALW`` structure."""

    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", wintypes.LPBYTE),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _load_advapi32() -> ctypes.WinDLL:
    """Load and prototype the advapi32 credential functions."""
    lib = ctypes.WinDLL("advapi32", use_last_error=True)
    lib.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
    ]
    lib.CredReadW.restype = wintypes.BOOL
    lib.CredFree.argtypes = [ctypes.c_void_p]
    lib.CredFree.restype = None
    return lib
