"""Exception hierarchy mapping directly to process exit codes.

Exit codes (per the container interface): 0 success, 1 transient error, 2 policy
violation. `cli.main()` is the sole place these are caught and translated.
"""

from __future__ import annotations


class GorgetError(Exception):
    """Base class for all errors gorget deliberately raises."""

    exit_code: int = 1


class GorgetConfigError(GorgetError):
    """Invalid pipeline YAML, spec file, or CLI arguments. Exit 1."""

    exit_code = 1


class GorgetTransientError(GorgetError):
    """Download failure, missing external tool, subprocess failure, network error.

    Exit 1. Retrying the same invocation may succeed.
    """

    exit_code = 1


class GorgetPolicyViolation(GorgetError):
    """A policy or verification rule was violated. Exit 2."""

    exit_code = 2
