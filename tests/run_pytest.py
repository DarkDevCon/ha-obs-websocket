"""Runner wrapper for tests on HA >= 2026.11.

HA 2026.11 replaced httpx with httpx2 and aliases it at `homeassistant`
import time. PHACC's pytest entry-point imports httpx-dependent modules
BEFORE any conftest runs, so the alias has to be installed even earlier —
this wrapper does exactly that, then hands off to pytest.

Usage: PYTHONPATH=<env> python3 tests/run_pytest.py [-q tests/]
"""
import os
import sys

# Make repo root importable (tests/ package) regardless of invocation cwd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx2

httpx2.alias_httpx()


def _compat_shims() -> None:
    """Version shims for PHACC (targeting HA 2026.10.4) running on newer HA.

    2026.11 relocated `_clear_logger_overwrites` from the logger component's
    __init__ into logger.helpers; alias it back so PHACC's import works.
    Hasattr-guarded: a no-op on versions where the symbol already exists.
    """
    import homeassistant.components.logger as logger_component
    from homeassistant.components.logger import helpers

    if not hasattr(logger_component, "_clear_logger_overwrites"):
        logger_component._clear_logger_overwrites = helpers._clear_logger_overwrites


_compat_shims()

import pytest


if __name__ == "__main__":
    args = sys.argv[1:] or ["-q", "tests/"]
    sys.exit(pytest.main(args))
