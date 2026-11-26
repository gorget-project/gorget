"""Identify shipped Maven coordinates from JARs, with repository hash fallback."""

import io
import re
import tarfile
import zipfile
from collections.abc import Iterator, Sequence
from hashlib import sha256
from pathlib import Path

from gorget.exceptions import GorgetConfigError

_PROPERTY = re.compile(r"^\s*([^#!:=\s]+)\s*[:=]\s*(.*?)\s*$")


def _jars(path: Path) -> Iterator[tuple[str, bytes]]:
    if path.is_dir():
        for jar in sorted(path.rglob("*.jar")):
            yield str(jar.relative_to(path)), jar.read_bytes()
    elif path.suffix == ".jar":
        yield path.name, path.read_bytes()
    else:
        with tarfile.open(path) as archive:
            for member in archive:
                if member.isfile() and member.name.endswith(".jar"):
                    stream = archive.extractfile(member)
                    assert stream is not None
                    yield member.name, stream.read()


def maven_provides(
    paths: Sequence[Path], repository: Path | None = None,
) -> list[tuple[str, str]]:
    index: dict[bytes, set[tuple[str, str]]] = {}
    if repository is not None:
        for name, contents in _jars(repository):
            parts = Path(name).parts
            if not repository.is_dir() and parts[0] == "vendor":
                parts = parts[1:]
            if len(parts) >= 4:
                artifact, version = parts[-3:-1]
                if parts[-1].startswith(f"{artifact}-{version}"):
                    coordinate = f"{'.'.join(parts[:-3])}:{artifact}"
                    index.setdefault(sha256(contents).digest(), set()).add((coordinate, version))
    provides = set()
    for path in paths:
        for name, contents in _jars(path):
            coordinates = index.get(sha256(contents).digest(), set()).copy()
            if not coordinates:
                with zipfile.ZipFile(io.BytesIO(contents)) as jar:
                    for member in jar.namelist():
                        if (member.startswith("META-INF/maven/")
                                and member.endswith("/pom.properties")):
                            values = {
                                match[1]: match[2]
                                for line in jar.read(member).decode().splitlines()
                                if (match := _PROPERTY.match(line))
                            }
                            if all(values.get(key) for key in ("groupId", "artifactId", "version")):
                                coordinates.add((f"{values['groupId']}:{values['artifactId']}",
                                                 values["version"]))
            if not coordinates:
                raise GorgetConfigError(f"No Maven coordinates found for shipped JAR: {name}")
            provides.update(coordinates)
    if not provides:
        raise GorgetConfigError("No shipped Maven dependencies found")
    return sorted(provides)
