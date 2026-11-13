import io
import tarfile
import zipfile

import pytest
from test_pipeline_stage_post import make_ctx, make_state

from gorget.config.schema import BundledProvidesStep, PipelineSpec, PostSection
from gorget.dependencies.maven_provides import maven_provides
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.stages.post import PostStage


def _jar(coordinates=()):
    contents = io.BytesIO()
    with zipfile.ZipFile(contents, "w") as jar:
        jar.writestr("example.class", b"compiled bytecode")
        for group, artifact, version in coordinates:
            jar.writestr(f"META-INF/maven/{group}/{artifact}/pom.properties",
                         f"# generated\ngroupId={group}\nartifactId={artifact}\n"
                         f"version={version}\n")
    return contents.getvalue()


def _archive(path, jars):
    with tarfile.open(path, "w:gz") as archive:
        for name, contents in jars.items():
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            archive.addfile(member, io.BytesIO(contents))
    return path


@pytest.mark.parametrize("archive", [False, True])
@pytest.mark.parametrize("archive_repository", [False, True])
def test_only_shipped_jars_are_reported_with_repository_hash_fallback(
    tmp_path, archive, archive_repository,
):
    repository = tmp_path / "repository"
    asm = repository / "org/ow2/asm/asm/9.11.1/asm-9.11.1.jar"
    asm.parent.mkdir(parents=True)
    asm.write_bytes(_jar())  # ASM does not include Maven pom.properties.
    build_only = repository / "org/example/compiler/1.0/compiler-1.0.jar"
    build_only.parent.mkdir(parents=True)
    build_only.write_bytes(_jar([("org.example", "compiler", "1.0")]))
    jars = {"app/lib/asm.jar": asm.read_bytes(), "app/lib/shaded.jar": _jar([
        ("org.example", "first", "1.2"), ("org.example", "second", "2.0-jre"),
    ])}
    if archive:
        shipped = _archive(tmp_path / "distribution.tar.gz", jars)
    else:
        shipped = tmp_path / "shipped"
        for name, contents in jars.items():
            jar = shipped / name
            jar.parent.mkdir(parents=True, exist_ok=True)
            jar.write_bytes(contents)
    if archive_repository:
        repository = _archive(tmp_path / "vendor.tar.gz", {
            "vendor/" + str(jar.relative_to(repository)): jar.read_bytes()
            for jar in repository.rglob("*.jar")
        })
    assert maven_provides([shipped], repository) == [
        ("org.example:first", "1.2"), ("org.example:second", "2.0-jre"),
        ("org.ow2.asm:asm", "9.11.1"),
    ]


def test_unidentified_jar_fails_instead_of_silently_omitting_a_dependency(tmp_path):
    jar = tmp_path / "unidentified.jar"
    jar.write_bytes(_jar())
    with pytest.raises(GorgetConfigError, match="No Maven coordinates.*unidentified.jar"):
        maven_provides([jar])
    with pytest.raises(GorgetConfigError, match="No shipped Maven dependencies"):
        maven_provides([])


def test_maven_post_reads_artifacts_excludes_own_modules_and_writes_inc(tmp_path):
    archive = _archive(tmp_path / "distribution.tar.gz", {
        "app/lib/own.jar": _jar([("org.example.app", "core", "1.0")]),
        "app/lib/library.jar": _jar([("org.example", "lib", "2.0-jre")]),
    })
    state = make_state(tmp_path)
    state.artifacts.append(FetchedArtifact(
        path=archive, output_name=archive.name, source_description="assembled distribution",
        checksum=None,
    ))
    step = BundledProvidesStep(ecosystem="maven", artifacts=[archive.name],
                               exclude=["org.example.app:*"])
    PostStage().run(make_ctx(tmp_path), PipelineSpec(post=PostSection(steps=[step])), state)
    assert (tmp_path / "bundled-maven-provides.inc").read_text() == (
        "Provides:       bundled(mvn(org.example:lib)) = 2.0-jre\n"
    )
