"""Shared code for the E7 Codex pipeline (refactor phase 2).

This package is PUBLIC: nothing here may hold a key, a secret, or code from the
private ingest path (`extract_ssra.py`, `extract_pack.py` decrypt routines). The
modules are keyless — importing them never requires a local `voice_keys.json`;
keys and paths are read lazily, on first use.

    config      data-dir resolution + the one voice_keys.json reader
    dbcrypto    YUNA/CDBM table reader, outer PLPcK XOR, cocos-XXTEA, text.db
    log         the shared `[HH:MM:SS] message` progress logger

Nothing in here imports from `private/` or from a builder module.
"""
