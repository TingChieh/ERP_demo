from dataclasses import dataclass
from secrets import token_urlsafe
from threading import Lock
from time import time

from flask import current_app

from services.exports import ExportFile


EXPORT_TOKEN_TTL_SECONDS = 10 * 60
MAX_EXPORT_ARTIFACTS = 50
_registry_lock = Lock()


@dataclass(frozen=True)
class _StoredExport:
    export_file: ExportFile
    expires_at: float


def _registry():
    return current_app.extensions.setdefault("erp_export_artifacts", {})


def _remove_expired(exports, now):
    for token in [token for token, item in exports.items() if item.expires_at <= now]:
        exports.pop(token, None)


def store_export_artifact(export_file):
    now = time()
    expires_at = now + EXPORT_TOKEN_TTL_SECONDS
    with _registry_lock:
        exports = _registry()
        _remove_expired(exports, now)
        if len(exports) >= MAX_EXPORT_ARTIFACTS:
            earliest = min(exports, key=lambda token: exports[token].expires_at)
            exports.pop(earliest, None)
        token = token_urlsafe(32)
        while token in exports:
            token = token_urlsafe(32)
        exports[token] = _StoredExport(export_file=export_file, expires_at=expires_at)
    return token


def consume_export_artifact(token):
    now = time()
    with _registry_lock:
        exports = _registry()
        _remove_expired(exports, now)
        stored = exports.pop(token, None)
    if stored is None:
        return None
    return stored.export_file if stored.expires_at > now else None
