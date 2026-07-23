from gorget.pipeline.result import StageResult


def test_stage_result_to_dict_omits_details_when_none():
    result = StageResult(name="fetch", status="success")
    assert "details" not in result.to_dict()


def test_stage_result_to_dict_includes_details_when_present():
    detail = {"type": "gpg-signature", "target": "foo.tar.gz", "status": "passed", "reason": None}
    result = StageResult(name="verify", status="success", details=[detail])
    assert result.to_dict()["details"] == [detail]
