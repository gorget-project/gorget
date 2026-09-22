import pytest

from gorget.config.schema import PublishSection
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.publication import build_artifact_plan, select_publications


def make_artifact(name):
    return FetchedArtifact(
        path=None,
        output_name=name,
        source_description=name,
        checksum="abc",
    )


def test_explicit_publications_follow_declared_order():
    source = make_artifact("source.tar.gz")
    signature = make_artifact("source.tar.gz.asc")
    vendor = make_artifact("vendor.tar.gz")

    selected = select_publications(
        [source, signature, vendor],
        PublishSection(files=["vendor.tar.gz", "source.tar.gz"]),
    )

    assert selected == [vendor, source]


def test_explicit_empty_publication_selects_nothing():
    selected = select_publications(
        [make_artifact("source.tar.gz")], PublishSection(files=[])
    )

    assert selected == []


def test_implicit_publication_preserves_all_artifacts_and_warns(caplog):
    artifacts = [make_artifact("source.tar.gz"), make_artifact("signature.asc")]

    with caplog.at_level("WARNING", logger="gorget.pipeline"):
        selected = select_publications(artifacts, None)

    assert selected == artifacts
    assert "Deprecated implicit publication" in caplog.text


def test_missing_publication_raises_config_error():
    with pytest.raises(GorgetConfigError, match="was not produced"):
        select_publications([], PublishSection(files=["missing.tar.gz"]))


def test_dry_run_selects_planned_publication(tmp_path):
    plan = build_artifact_plan(
        tmp_path, "run", ["generated.tar.gz"], "run:generate"
    )

    selected = select_publications(
        [],
        PublishSection(files=["generated.tar.gz"]),
        artifact_plans=[plan],
    )

    assert [artifact.output_name for artifact in selected] == ["generated.tar.gz"]


def test_dry_run_rejects_both_names_from_one_alternative_plan(tmp_path):
    plan = build_artifact_plan(
        tmp_path, "run", ["dist", "dist.tar.gz"], "run:generate"
    )

    with pytest.raises(GorgetConfigError, match="cannot be produced together"):
        select_publications(
            [],
            PublishSection(files=["dist", "dist.tar.gz"]),
            artifact_plans=[plan],
        )


def test_duplicate_publication_raises_config_error():
    artifact = make_artifact("source.tar.gz")

    with pytest.raises(GorgetConfigError, match="Duplicate filename"):
        select_publications(
            [artifact], PublishSection(files=["source.tar.gz", "source.tar.gz"])
        )
