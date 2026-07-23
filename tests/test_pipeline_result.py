import json

from gorget.pipeline.result import StageResult, write_report_json


def test_stage_result_to_dict_omits_details_when_none():
    result = StageResult(name="fetch", status="success")
    assert "details" not in result.to_dict()


def test_stage_result_to_dict_includes_details_when_present():
    detail = {"type": "gpg-signature", "target": "foo.tar.gz", "status": "passed", "reason": None}
    result = StageResult(name="verify", status="success", details=[detail])
    assert result.to_dict()["details"] == [detail]


def test_write_report_json_creates_output_dir_if_missing(tmp_path):
    output_dir = tmp_path / "nested" / "output"
    write_report_json(output_dir, {"package": "foo"})
    assert output_dir.is_dir()


def test_write_report_json_writes_valid_indented_json(tmp_path):
    write_report_json(tmp_path, {"package": "foo", "stages": []})
    text = (tmp_path / "report.json").read_text()
    assert text.endswith("\n")
    assert json.loads(text) == {"package": "foo", "stages": []}
