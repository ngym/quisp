from __future__ import annotations

import pytest

from scripts.dashboard.backend.app.runner_config_builder import build_run_ini, validate_run_spec_overrides


def test_build_run_ini_creates_derived_config_and_extends(tmp_path):
    template = tmp_path / "template.ini"
    template.write_text("[Config Base]\n**.foo = bar\n", encoding="utf-8")
    output = tmp_path / "run.ini"
    log_path = tmp_path / "run.jsonl"

    created_path, effective_config = build_run_ini(
        template_path=template,
        output_path=output,
        log_file_path=log_path,
        config_name="Base",
        sim_time_limit=12.5,
        overrides={"sim-time-limit": "20", "**.logger.enabled_log": "false", "Network[0].x": 1},
    )

    assert created_path == output
    assert effective_config == "Dashboard_Base"
    text = output.read_text(encoding="utf-8")
    assert "[Config Dashboard_Base]" in text
    assert "extends = Base" in text
    assert '**.logger.log_filename = "' + str(log_path) + '"' in text
    assert "**.logger.enabled_log = false" in text
    assert "sim-time-limit = \"20s\"" not in text
    assert "sim-time-limit = 20s" in text
    assert 'Network[0].x = 1' in text


def test_validate_overrides_rejects_unsupported_key():
    with pytest.raises(ValueError, match="unsupported override key"):
        validate_run_spec_overrides({"invalid key": "bad"})


def test_validate_overrides_accepts_wildcard_keys():
    overrides = validate_run_spec_overrides({"**.logger.enabled_log": "true"})
    assert overrides["**.logger.enabled_log"] == "true"


def test_build_run_ini_rejects_unsupported_override_key(tmp_path):
    template = tmp_path / "template.ini"
    template.write_text("[Config Base]\\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported override key"):
        build_run_ini(
            template_path=template,
            output_path=tmp_path / "run.ini",
            log_file_path=tmp_path / "run.jsonl",
            config_name="Base",
            overrides={"bad key": "x"},
        )


def test_build_run_ini_enables_logger_and_normalizes_numeric_time_limit(tmp_path):
    template = tmp_path / "template.ini"
    template.write_text("[Config Base]\n", encoding="utf-8")

    build_run_ini(
        template_path=template,
        output_path=tmp_path / "run.ini",
        log_file_path=tmp_path / "run.jsonl",
        config_name="Base",
        sim_time_limit=9,
        overrides={},
    )

    text = (tmp_path / "run.ini").read_text(encoding="utf-8")
    assert "**.logger.enabled_log = true" in text
    assert "sim-time-limit = 9s" in text
