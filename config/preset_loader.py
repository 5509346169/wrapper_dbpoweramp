"""config/preset_loader.py: Load and validate presets.yaml into PresetConfig objects."""

from pathlib import Path
from typing import Any

import yaml

from exceptions import ConfigError, PresetNotFoundError
from models.types import (
    Backend,
    BackendPresetArgs,
    CoverPolicy,
    PresetConfig,
    SidecarPolicy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raise(msg: str) -> None:
    raise ConfigError(msg)


def _get(data: dict[str, Any], key: str, path: str) -> Any:
    try:
        return data[key]
    except KeyError:
        _raise(f"Missing required key '{path}' in presets.yaml")


def _str(data: dict[str, Any], key: str, path: str, allow_empty: bool = True) -> str:
    val = _get(data, key, path)
    if not isinstance(val, str):
        _raise(f"'{path}' must be a string, got {type(val).__name__}")
    if not allow_empty and not val:
        _raise(f"'{path}' must be a non-empty string")
    return val


def _bool(data: dict[str, Any], key: str, path: str) -> bool:
    val = _get(data, key, path)
    if not isinstance(val, bool):
        _raise(f"'{path}' must be a boolean, got {type(val).__name__}")
    return val


def _list_str(data: dict[str, Any], key: str, path: str) -> list[str]:
    val = _get(data, key, path)
    if not isinstance(val, list):
        _raise(f"'{path}' must be a list, got {type(val).__name__}")
    for i, item in enumerate(val):
        if not isinstance(item, str):
            _raise(f"'{path}[{i}]' must be a string, got {type(item).__name__}")
    return val


def _optional_str(data: dict[str, Any], key: str, path: str) -> str | None:
    try:
        return _str(data, key, path, allow_empty=False)
    except ConfigError:
        return None


def _build_sidecar_policy(data: dict[str, Any] | None) -> SidecarPolicy | None:
    if data is None:
        return None
    return SidecarPolicy(
        copy=_bool(data, "copy", "<sidecar>.copy"),
        extensions=_list_str(data, "extensions", "<sidecar>.extensions"),
        hide=_bool(data, "hide", "<sidecar>.hide"),
    )


def _build_cover_policy(data: dict[str, Any] | None) -> CoverPolicy | None:
    if data is None:
        return None
    return CoverPolicy(
        copy=_bool(data, "copy", "<cover>.copy"),
        patterns=_list_str(data, "patterns", "<cover>.patterns"),
        hide=_bool(data, "hide", "<cover>.hide"),
    )


def _build_backend_args(data: dict[str, Any] | None) -> BackendPresetArgs | None:
    if data is None:
        return None
    encoder = _optional_str(data, "encoder", "<backend>.encoder")
    tool = _optional_str(data, "tool", "<backend>.tool")
    args = _list_str(data, "args", "<backend>.args")
    requires_encoder = _optional_str(data, "requires_encoder", "<backend>.requires_encoder")
    return BackendPresetArgs(
        encoder=encoder,
        tool=tool,
        args=args,
        requires_encoder=requires_encoder,
    )


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_presets(path: Path | str) -> dict[str, PresetConfig]:
    """Parse and validate presets.yaml. Raises ConfigError on malformed or invalid config."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        _raise(f"Failed to parse presets.yaml: {e}")
    if not isinstance(raw, dict):
        _raise("presets.yaml must contain a YAML mapping at the top level")

    presets_data = _get(raw, "presets", "presets")
    if not isinstance(presets_data, dict):
        _raise("'presets' must be a YAML mapping of preset-name -> config")

    result: dict[str, PresetConfig] = {}

    for name, cfg in presets_data.items():
        if not isinstance(cfg, dict):
            _raise(f"Preset '{name}' must be a YAML mapping")

        ext = _str(cfg, "ext", f"presets.{name}.ext", allow_empty=False)
        if not ext.startswith("."):
            _raise(f"presets.{name}.ext must start with '.', got '{ext}'")

        backends_data = _get(cfg, "backends", f"presets.{name}.backends")
        if not isinstance(backends_data, dict):
            _raise(f"presets.{name}.backends must be a YAML mapping")

        if not backends_data:
            _raise(f"Preset '{name}' must have at least one backend block")

        backends: dict[Backend, BackendPresetArgs] = {}

        for backend_key in ("wine_dbpoweramp", "native_ffmpeg"):
            args = _build_backend_args(backends_data.get(backend_key))
            if args is not None:
                backends[Backend(backend_key)] = args

        sidecars_data = cfg.get("sidecars", {})
        if not isinstance(sidecars_data, dict):
            _raise(f"presets.{name}.sidecars must be a YAML mapping")

        lyrics = _build_sidecar_policy(sidecars_data.get("lyrics"))
        covers = _build_cover_policy(sidecars_data.get("covers"))

        result[name] = PresetConfig(
            name=name,
            ext=ext,
            backends=backends,
            lyrics=lyrics,
            covers=covers,
        )

    return result


def get_preset(presets: dict[str, PresetConfig], name: str) -> PresetConfig:
    """Look up a preset by name. Raises PresetNotFoundError with available names if not found."""
    if name not in presets:
        raise PresetNotFoundError(name, list(presets.keys()))
    return presets[name]
