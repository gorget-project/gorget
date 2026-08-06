"""`SpecFile`: reads and mutates an RPM spec file by shelling out to `rpmspec`/`rpm`
rather than reimplementing RPM macro semantics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from gorget.config.schema import MacroSubstitution
from gorget.config.substitution import SubstitutionVars, substitute_string
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.util.subprocess_run import run

_SOURCE_RE = re.compile(r"^Source(\d*)\s*:\s*(\S+)\s*$", re.MULTILINE)
_PATCH_RE = re.compile(r"^Patch(\d*)\s*:\s*(\S+)\s*$", re.MULTILINE)
_VERSION_RE = re.compile(r"^(Version:\s*)\S+", re.MULTILINE)
_RELEASE_RE = re.compile(r"^(Release:\s*)(\S+?)(%\{[^}]*\}.*)?$", re.MULTILINE)


@dataclass(frozen=True, kw_only=True)
class SpecSourceEntry:
    index: int
    url: str
    raw: str | None = None


@dataclass(frozen=True, kw_only=True)
class SpecPatchEntry:
    index: int
    filename: str


class SpecFile:
    def __init__(self, path: Path, sourcedir: Path | None = None):
        self.path = path
        # Defaults to the spec's own directory, correct when `path` sits
        # alongside its sources (the common case, and every existing caller
        # except the pipeline runner's scratch copy). A spec that
        # `%{load:%{_sourcedir}/...}`s a sibling macro file needs this pointed
        # at the real --package-dir instead, since only the spec itself gets
        # copied into gorget's scratch work dir for editing.
        self._sourcedir = sourcedir if sourcedir is not None else path.parent

    def _base_defines(self) -> list[str]:
        return ["--define", f"_sourcedir {self._sourcedir}"]

    def _rpmspec_expand(self, spec_path: Path) -> str:
        result = run(["rpmspec", "-P", *self._base_defines(), str(spec_path)])
        if result.returncode != 0:
            raise GorgetTransientError(
                f"rpmspec failed to parse {spec_path}: {result.stderr.strip()}"
            )
        return result.stdout

    def _rpmspec_query(self, queryformat: str) -> str:
        result = run(
            [
                "rpmspec",
                "-q",
                "--queryformat",
                queryformat,
                *self._base_defines(),
                "--srpm",
                str(self.path),
            ]
        )
        if result.returncode != 0:
            raise GorgetTransientError(
                f"rpmspec query failed for {self.path}: {result.stderr.strip()}"
            )
        return result.stdout.strip()

    def macro_expanded_text(self) -> str:
        return self._rpmspec_expand(self.path)

    def name(self) -> str:
        return self._rpmspec_query("%{NAME}")

    def version(self) -> str:
        return self._rpmspec_query("%{VERSION}")

    def release(self) -> str:
        return self._rpmspec_query("%{RELEASE}")

    def sources(self) -> list[SpecSourceEntry]:
        expanded = self.macro_expanded_text()
        raw_text = self.path.read_text()

        entries: dict[int, str] = {}
        for match in _SOURCE_RE.finditer(expanded):
            index = int(match.group(1)) if match.group(1) else 0
            if index in entries:
                raise GorgetConfigError(
                    f"Duplicate Source{index} declaration in {self.path}"
                )
            entries[index] = match.group(2)

        raw_lines: dict[int, str] = {}
        for match in _SOURCE_RE.finditer(raw_text):
            index = int(match.group(1)) if match.group(1) else 0
            raw_lines.setdefault(index, match.group(0).strip())

        return [
            SpecSourceEntry(index=index, url=url, raw=raw_lines.get(index))
            for index, url in sorted(entries.items())
        ]

    def patches(self) -> list[SpecPatchEntry]:
        """Return declared PatchN: entries in index order.

        Unlike sources(), this reads the raw spec text rather than macro-expanded
        output: a patch filename is a plain literal in every spec seen so far, and
        the raw text also preserves patches inside %if blocks that rpmspec -P
        would otherwise resolve away for the current build target -- callers here
        care about what's *declared*, not what applies to any one arch/condition.
        """
        entries: dict[int, str] = {}
        for match in _PATCH_RE.finditer(self.path.read_text()):
            index = int(match.group(1)) if match.group(1) else 0
            entries.setdefault(index, match.group(2))
        return [
            SpecPatchEntry(index=index, filename=filename)
            for index, filename in sorted(entries.items())
        ]

    def set_version(self, version: str) -> None:
        text = self.path.read_text()
        new_text, count = _VERSION_RE.subn(rf"\g<1>{version}", text, count=1)
        if count == 0:
            raise GorgetConfigError(f"No Version: tag found in {self.path}")
        self._rewrite_and_validate(new_text)

    def reset_release(self, value: str = "1") -> None:
        text = self.path.read_text()

        def _replace(match: re.Match[str]) -> str:
            suffix = match.group(3) or ""
            return f"{match.group(1)}{value}{suffix}"

        new_text, count = _RELEASE_RE.subn(_replace, text, count=1)
        if count == 0:
            raise GorgetConfigError(f"No Release: tag found in {self.path}")
        self._rewrite_and_validate(new_text)

    def apply_substitution(self, sub: MacroSubstitution, variables: SubstitutionVars) -> None:
        text = self.path.read_text()
        replacement = substitute_string(sub.replacement, variables)
        new_text, count = re.subn(sub.pattern, replacement, text, flags=re.MULTILINE)
        if count == 0:
            raise GorgetConfigError(
                f"Substitution pattern {sub.pattern!r} matched nothing in {self.path}"
            )
        self._rewrite_and_validate(new_text)

    def _rewrite_and_validate(self, new_text: str) -> None:
        tmp_path = self.path.with_name(self.path.name + ".gorget-tmp")
        tmp_path.write_text(new_text)
        try:
            self._rpmspec_expand(tmp_path)
        except GorgetTransientError as exc:
            raise GorgetTransientError(
                f"Spec file edit produced an invalid spec (left for inspection at "
                f"{tmp_path}): {exc}"
            ) from exc
        tmp_path.replace(self.path)
