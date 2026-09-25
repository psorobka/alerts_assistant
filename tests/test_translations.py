"""Keep Home Assistant translations complete for every supported language."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

INTEGRATION_DIR = Path(__file__).parents[1] / "custom_components" / "alerts_assistant"


def _leaf_paths(value: Any, prefix: str = "") -> set[str]:
    """Return paths for all leaf values in a nested translation dictionary."""
    if isinstance(value, dict):
        return {
            path
            for key, child in value.items()
            for path in _leaf_paths(child, f"{prefix}.{key}".strip("."))
        }
    return {prefix}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_translations_include_every_string() -> None:
    """English and Polish translations should match strings.json structure."""
    source = _load_json(INTEGRATION_DIR / "strings.json")
    source_paths = _leaf_paths(source)
    assert (
        source["config_subentries"]["alert"]["error"]["no_entities"]
        == "Select at least one entity or label."
    )

    for language in ("en", "pl"):
        translation = _load_json(INTEGRATION_DIR / "translations" / f"{language}.json")

        assert _leaf_paths(translation) == source_paths
        assert all(value.strip() for value in _leaf_values(translation))
        assert (
            "no_entities"
            not in translation["config_subentries"]["alert"]["step"]["user_target"]
        )
        assert "no_entities" in translation["config_subentries"]["alert"]["error"]


def _leaf_values(value: Any):
    """Yield every translated string in a nested dictionary."""
    if isinstance(value, dict):
        for child in value.values():
            yield from _leaf_values(child)
    else:
        yield value


@pytest.mark.parametrize("language", ["en", "pl"])
def test_translation_json_is_valid(language: str) -> None:
    """Each supported locale should be valid JSON."""
    translation = _load_json(INTEGRATION_DIR / "translations" / f"{language}.json")

    assert isinstance(translation, dict)
