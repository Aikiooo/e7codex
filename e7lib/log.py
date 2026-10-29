"""The shared progress logger: `[HH:MM:SS] message` on stdout, flushed.

The two ingest scripts (`extract_pack`, `extract_ssra`) each carried this exact
function (same format, same stream, same flush); it lives here once now. Tools
whose logger differs keep their own — the illust batch baker also appends to a
log file and stamps the date, so it is deliberately not merged.
"""
from __future__ import annotations

import time

__all__ = ["log"]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
