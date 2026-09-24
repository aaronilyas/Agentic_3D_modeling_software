"""Versioned project files. The feature graph is reloaded; B-rep is a cache."""

from __future__ import annotations

import base64
import io
import json
import os
import zipfile
from pathlib import Path

from cad.assets import ReferenceImage, checksum
from cad.errors import InvalidArgument
from cad.exporting import publish_bytes
from cad.features import Feature
from cad.replay import replay

FORMAT = "agentic-cad-project"
VERSION = 1


def save_project(document, path: str) -> dict:
    features = []
    shape_files = {}
    for feature in document.features:
        public = feature.to_public()
        params = dict(feature.params)
        if isinstance(params.get("brep"), (bytes, bytearray)):
            name = f"shapes/{feature.id}.brep"
            shape_files[name] = bytes(params["brep"])
            params["brep_file"] = name
            params.pop("brep", None)
        public["params"] = _jsonable(params)
        features.append(public)
    assets = []
    asset_files = {}
    for asset in document.assets:
        filename = f"assets/{asset.id}-{_safe(asset.filename)}"
        asset_files[filename] = asset.data
        meta = asset.public()
        meta["file"] = filename
        meta.pop("bytes", None)
        assets.append(meta)
    payload = {
        "format": FORMAT,
        "format_version": VERSION,
        "units": "mm",
        "axes": "right-handed-z-up",
        "revision": document.revision,
        "features": features,
        "names": document.names,
        "sketches": document.sketches,
        "assets": assets,
        "settings": document.settings,
        "domain": document.settings.get("domain"),
        "shape_cache": sorted(shape_files),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.json", json.dumps(payload, indent=2, allow_nan=False))
        for name, data in {**shape_files, **asset_files}.items():
            archive.writestr(name, data)
    publish_bytes(path, buffer.getvalue())
    return {"path": os.path.abspath(path), "format_version": VERSION, "revision": document.revision}


def load_project(path: str, backend) -> dict:
    source = Path(path)
    if not source.is_file():
        raise InvalidArgument("project file does not exist")
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise InvalidArgument("project file is not a valid archive") from exc
    with archive:
        try:
            payload = json.loads(archive.read("project.json"))
        except KeyError as exc:
            raise InvalidArgument("project.json is missing") from exc
        except json.JSONDecodeError as exc:
            raise InvalidArgument("project.json is not valid JSON") from exc
        _require_version(payload)
        features = []
        for raw in payload.get("features", []):
            params = dict(raw.get("params") or {})
            brep_file = params.pop("brep_file", None)
            if brep_file:
                params["brep"] = archive.read(brep_file)
            if "brep" in params and isinstance(params["brep"], str):
                params["brep"] = base64.b64decode(params["brep"])
            features.append(Feature(
                id=raw["id"], op=raw["op"], params=params,
                output_ref=raw.get("output_ref"), name=raw.get("name") or "",
            ))
        solids, sketches = replay(features, backend)
        assets = []
        for meta in payload.get("assets", []):
            data = archive.read(meta["file"])
            digest = checksum(data)
            if digest != meta.get("checksum"):
                raise InvalidArgument(f"checksum mismatch for {meta.get('id')}")
            assets.append(ReferenceImage(
                id=meta["id"], label=meta.get("label") or "", role=meta.get("role") or "other",
                filename=meta.get("filename") or "image", media_type=meta.get("media_type") or "",
                width=int(meta.get("width") or 0), height=int(meta.get("height") or 0),
                checksum=digest, notes=meta.get("notes") or "",
                camera_hint=meta.get("camera_hint"), calibration=meta.get("calibration"),
                data=data,
            ))
    return {
        "features": features,
        "solids": solids,
        "sketches": sketches or payload.get("sketches") or {},
        "names": dict(payload.get("names") or {}),
        "assets": assets,
        "settings": dict(payload.get("settings") or {"units": "mm", "axes": "right-handed-z-up"}),
        "serials": _serials(features, assets),
        "format_version": VERSION,
    }


def _require_version(payload: dict) -> None:
    if payload.get("format") != FORMAT:
        raise InvalidArgument("not an agentic CAD project")
    version = payload.get("format_version")
    if version != VERSION:
        raise InvalidArgument(f"unsupported project format version {version}")
    if payload.get("units") != "mm":
        raise InvalidArgument("project units must be millimetres")


def _serials(features: list[Feature], assets: list[ReferenceImage]) -> dict:
    return {
        "feature": _next(feature.id for feature in features),
        "body": _next(feature.output_ref for feature in features if feature.output_ref),
        "asset": _next(asset.id for asset in assets),
    }


def _next(values) -> int:
    highest = 0
    for value in values:
        if not isinstance(value, str) or "-" not in value:
            continue
        try:
            highest = max(highest, int(value.rsplit("-", 1)[1]))
        except ValueError:
            continue
    return highest + 1


def _jsonable(value):
    if isinstance(value, (bytes, bytearray)):
        return {"base64_bytes": len(value)}
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _safe(name: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "._-" else "_" for character in name)
    return cleaned or "image"
