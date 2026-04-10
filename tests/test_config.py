import pytest

from auto_reply_priv import load_config, validate_config


def test_load_config(tmp_path):
    config_path = tmp_path / "test_config.yaml"
    config_path.write_text(
        "ai:\n  api_url: http://localhost:8080\n  api_key: key\n  model_id: gemma4\nradio:\n  port: COM6\n",
        encoding="utf-8",
    )

    cfg = load_config(str(config_path))

    assert cfg["ai"]["model_id"] == "gemma4"
    assert cfg["radio"]["port"] == "COM6"


def test_validate_config_success():
    cfg = {
        "ai": {"api_url": "http://localhost:8080", "api_key": "token", "model_id": "gemma4"},
        "radio": {"port": "COM6"},
        "bot_behavior": {"chunk_chars": 145},
        "system": {"health_port": 8766},
    }

    validate_config(cfg)


def test_validate_config_missing_model_id():
    cfg = {
        "ai": {"api_url": "http://localhost:8080", "api_key": "token"},
        "radio": {"port": "COM6"},
    }

    with pytest.raises(SystemExit):
        validate_config(cfg)
