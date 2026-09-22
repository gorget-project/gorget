from gorget.pipeline.artifact import build_derived_artifact, build_input_artifact


def test_build_input_artifact_records_acquisition(tmp_path):
    path = tmp_path / "source.tar.gz"
    path.write_bytes(b"input")

    artifact = build_input_artifact(path, path.name, "https://example.com/source", False)

    assert artifact.kind == "input"
    assert artifact.parents == ()


def test_build_derived_artifact_records_parent_identity(tmp_path):
    input_path = tmp_path / "source.tar.gz"
    input_path.write_bytes(b"input")
    parent = build_input_artifact(input_path, input_path.name, "upstream", False)
    derived_path = tmp_path / "stripped.tar.gz"
    derived_path.write_bytes(b"derived")

    artifact = build_derived_artifact(
        derived_path,
        derived_path.name,
        "strip-tarball",
        False,
        parents=[parent],
    )

    assert artifact.kind == "derived"
    assert artifact.parents == (parent.ref(),)
