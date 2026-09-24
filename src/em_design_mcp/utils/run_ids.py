from __future__ import annotations

from hashlib import sha256


def make_run_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"run_{digest}"
