# SPDX-License-Identifier: Unlicense
import yaml
import json
from pathlib import Path
from unittest.mock import patch
from mcp_stdio_bridge.logging_utils import configure_logging

def test_logging_configuration(tmp_path: Path) -> None:
    """Test that custom logging configuration (YAML) is correctly identified."""
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"test": {"format": "%(message)s"}},
        "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "test"}},
        "root": {"level": "DEBUG", "handlers": ["console"]}
    }
    config_file = tmp_path / "logging.yaml"
    config_file.write_text(yaml.dump(log_config))

    with patch("logging.config.dictConfig") as mock_dict_config:
        success = configure_logging("INFO", str(config_file))
        assert success is True
        mock_dict_config.assert_called_once()

def test_logging_configuration_json(tmp_path: Path) -> None:
    """Test that custom logging configuration (JSON) is correctly identified."""
    log_config = {
        "version": 1,
        "handlers": {"console": {"class": "logging.StreamHandler"}},
        "root": {"level": "INFO", "handlers": ["console"]}
    }
    config_file = tmp_path / "logging.json"
    config_file.write_text(json.dumps(log_config))

    with patch("logging.config.dictConfig") as mock_dict_config:
        success = configure_logging("INFO", str(config_file))
        assert success is True
        mock_dict_config.assert_called_once()

def test_logging_configuration_ini(tmp_path: Path) -> None:
    """Test that custom logging configuration (INI/Fallback) is correctly identified."""
    config_file = tmp_path / "logging.ini"
    config_file.write_text("[loggers]\nkeys=root\n[handlers]\nkeys=console\n[formatters]\nkeys=generic\n[logger_root]\nlevel=INFO\nhandlers=console\n[handler_console]\nclass=StreamHandler\nargs=(sys.stdout,)\nformatter=generic\n[formatter_generic]\nformat=%(message)s")

    with patch("logging.config.fileConfig") as mock_file_config:
        success = configure_logging("INFO", str(config_file))
        assert success is True
        mock_file_config.assert_called_once()

def test_logging_configuration_invalid(tmp_path: Path) -> None:
    """Test behavior with missing logging file."""
    success = configure_logging("INFO", "non_existent_file.yaml")
    assert success is False

def test_logging_configuration_invalid_format(tmp_path: Path) -> None:
    """Test behavior with malformed logging file."""
    config_file = tmp_path / "logging.yaml"
    config_file.write_text("invalid: yaml: :")
    success = configure_logging("INFO", str(config_file))
    assert success is False
