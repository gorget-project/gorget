"""Compatibility exports for lockfile parsers and shared dependency inventory."""

from pathlib import Path

from gorget.dependencies import bundled_provides as parse_bundled_provides
from gorget.dependencies import read_inventory
from gorget.dependencies.lockfiles import (
    pnpm_provides as pnpm_provides,
)
from gorget.dependencies.lockfiles import (
    yarn_provides as yarn_provides,
)

__all__ = ["npm_provides", "pnpm_provides", "yarn_provides", "parse_bundled_provides"]


def npm_provides(lockfile: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    inventory = read_inventory("npm", lockfile.parent)
    return inventory.provides(production=True), inventory.provides()
