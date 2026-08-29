from __future__ import annotations

import pytest

from blair.config import BlairConfig


@pytest.mark.parametrize(
    "field,value",
    [
        ("voice", "../native-library"),
        ("voice", 123),
        ("language", "en-gb/../../"),
        ("speed", True),
        ("speed", 2.1),
        ("max_words", True),
        ("max_words", 19),
        ("keep_audio_files", False),
        ("keep_audio_files", 0),
    ],
)
def test_configuration_rejects_invalid_runtime_values(field: str, value: object) -> None:
    config = BlairConfig()
    setattr(config, field, value)

    with pytest.raises(ValueError):
        config.validate()


def test_default_configuration_is_valid() -> None:
    BlairConfig().validate()
