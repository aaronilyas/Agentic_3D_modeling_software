"""Versioned project files. The feature graph is reloaded; B-rep is a cache."""

from __future__ import annotations

import base64
import io
import json
import re
import stat
import os
import zipfile
from pathlib import Path, PurePosixPath

from cad.assets import ReferenceImage, checksum, image_size, ROLES, calibrate
from cad.errors import InvalidArgument, ContractError
from cad.numbers import vec2, positive_number, finite_tree
from cad.operations import REPLAY
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
        "serials": dict(document._serials),
        "features": features,
        "names": document.names,
        "sketches": document.sketches,
        "assets": assets,
        "settings": document.settings,
        "domain": document.settings.get("domain"),
        "shape_cache": sorted(shape_files),
    }
    _validate_metadata(payload)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.json", json.dumps(payload, indent=2, allow_nan=False))
        for name, data in {**shape_files, **asset_files}.items():
            archive.writestr(name, data)
        _validate_archive(archive)
    publish_bytes(path, buffer.getvalue())
    return {"path": os.path.abspath(path), "format_version": VERSION, "revision": document.revision}


def load_project(path: str, backend) -> dict:
    try:
        return _load_project(path, backend)
    except InvalidArgument:
        raise
    except (OSError, ValueError, TypeError, KeyError, OverflowError, zipfile.BadZipFile,
            RuntimeError, RecursionError, ContractError) as exc:
        raise InvalidArgument(f"invalid project: {exc}") from exc


def _load_project(path: str, backend) -> dict:
    source = Path(path)
    if not source.is_file():
        raise InvalidArgument("project file does not exist")
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise InvalidArgument("project file is not a valid archive") from exc
    with archive:
        _validate_archive(archive)
        try:
            payload = json.loads(archive.read("project.json"))
        except KeyError as exc:
            raise InvalidArgument("project.json is missing") from exc
        except json.JSONDecodeError as exc:
            raise InvalidArgument("project.json is not valid JSON") from exc
        _require_version(payload)
        _validate_metadata(payload)
        features = []
        for raw in payload.get("features", []):
            params = dict(raw.get("params") or {})
            brep_file = params.pop("brep_file", None)
            if brep_file:
                params["brep"] = archive.read(brep_file)
            if "brep" in params and isinstance(params["brep"], str):
                params["brep"] = base64.b64decode(params["brep"], validate=True)
            features.append(Feature(
                id=raw["id"], op=raw["op"], params=params,
                output_ref=raw.get("output_ref"), name=raw.get("name") or "",
            ))
        _validate_history(features)
        solids, sketches = replay(features, backend)
        assets = []
        for meta in payload.get("assets", []):
            data = archive.read(meta["file"])
            media_type, width, height = image_size(data)
            if len(data) > 30 * 1024 * 1024:
                raise InvalidArgument("reference image is larger than 30 MB")
            if (media_type, width, height) != (meta.get("media_type"), meta.get("width"), meta.get("height")):
                raise InvalidArgument("reference image metadata does not match content")
            calibration = meta.get("calibration")
            if calibration is not None:
                if not isinstance(calibration, dict):
                    raise InvalidArgument("invalid calibration")
                calibration = calibrate(vec2(calibration["p1"], "p1"), vec2(calibration["p2"], "p2"),
                                        positive_number(calibration["distance_mm"], "distance_mm"))
            digest = checksum(data)
            if digest != meta.get("checksum"):
                raise InvalidArgument(f"checksum mismatch for {meta.get('id')}")
            assets.append(ReferenceImage(
                id=meta["id"], label=meta.get("label") or "", role=meta.get("role") or "other",
                filename=meta.get("filename") or "image", media_type=meta.get("media_type") or "",
                width=int(meta.get("width") or 0), height=int(meta.get("height") or 0),
                checksum=digest, notes=meta.get("notes") or "",
                camera_hint=meta.get("camera_hint"), calibration=calibration,
                data=data,
            ))
    return {
        "features": features,
        "solids": solids,
        "sketches": sketches,
        "names": dict(payload.get("names") or {}),
        "assets": assets,
        "settings": dict(payload.get("settings") or {"units": "mm", "axes": "right-handed-z-up"}),
        "serials": {key: max(value, payload.get("serials", {}).get(key, value))
                    for key, value in _serials(features, assets).items()},
        "format_version": VERSION,
    }


def _require_version(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise InvalidArgument("project metadata must be an object")
    if payload.get("format") != FORMAT:
        raise InvalidArgument("not an agentic CAD project")
    version = payload.get("format_version")
    if type(version) is not int or version != VERSION:
        raise InvalidArgument(f"unsupported project format version {version}")
    if payload.get("units") != "mm":
        raise InvalidArgument("project units must be millimetres")


def _serials(features: list[Feature], assets: list[ReferenceImage]) -> dict:
    return {
        "feature": _next(feature.id for feature in features),
        "body": _next([*(feature.output_ref for feature in features if feature.output_ref),
                       *(feature.params["ref"] for feature in features if feature.op == "delete")]),
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


MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024


def _member_name(name, prefix=None):
    if not isinstance(name, str) or not name or "\\" in name:
        raise InvalidArgument("invalid archive member path")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or ":" in name or str(path) != name.rstrip("/"):
        raise InvalidArgument("unsafe archive member path")
    if prefix and not name.startswith(prefix + "/"):
        raise InvalidArgument(f"expected {prefix}/ member")


def _validate_archive(archive):
    entries = archive.infolist()
    if len(entries) > 4096 or sum(info.file_size for info in entries) > MAX_ARCHIVE_BYTES:
        raise InvalidArgument("project archive exceeds size limits")
    names = set()
    for info in entries:
        _member_name(info.filename)
        if info.filename in names or stat.S_ISLNK(info.external_attr >> 16):
            raise InvalidArgument("duplicate or symbolic link archive member")
        names.add(info.filename)
        if info.file_size > MAX_MEMBER_BYTES or info.flag_bits & 1:
            raise InvalidArgument("oversized or encrypted archive member")


def _identifier(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(prefix + r"-[1-9][0-9]*", value):
        raise InvalidArgument(f"invalid {prefix} identifier")


def _validate_metadata(payload):
    finite_tree(payload)
    if payload.get("axes", "right-handed-z-up") != "right-handed-z-up":
        raise InvalidArgument("unsupported project axes")
    for key in ("features", "assets"):
        if not isinstance(payload.get(key, []), list):
            raise InvalidArgument(f"{key} must be an array")
    for key in ("names", "settings", "serials"):
        if not isinstance(payload.get(key, {}), dict):
            raise InvalidArgument(f"{key} must be an object")
    if any(not isinstance(value, str) for value in payload.get("names", {}).values()):
        raise InvalidArgument("names must be strings")
    for key, value in payload.get("serials", {}).items():
        if key not in {"feature", "body", "asset"} or type(value) is not int or value < 1:
            raise InvalidArgument("invalid identifier counters")
    settings = payload.get("settings", {})
    if settings.get("units", "mm") != "mm" or settings.get("axes", "right-handed-z-up") != "right-handed-z-up":
        raise InvalidArgument("inconsistent project settings")
    seen = set()
    for raw in payload.get("features", []):
        if not isinstance(raw, dict) or not isinstance(raw.get("params"), dict):
            raise InvalidArgument("feature must have a parameter object")
        _identifier(raw.get("id"), "feature")
        if raw["id"] in seen:
            raise InvalidArgument("duplicate feature id")
        seen.add(raw["id"])
        op = raw.get("op")
        if not isinstance(op, str) or op not in {*REPLAY, "sketch", "rename", "delete"}:
            raise InvalidArgument("unsupported feature operation")
        if not isinstance(raw.get("name", ""), str):
            raise InvalidArgument("feature name must be a string")
        if op in REPLAY:
            _identifier(raw.get("output_ref"), "body")
        elif raw.get("output_ref") is not None:
            raise InvalidArgument("non-solid feature cannot produce a body")
        params = raw["params"]
        if op != "duplicate" and ("brep_file" in params or "brep" in params):
            raise InvalidArgument("only baked duplicates may load B-Rep bytes")
        if "brep_file" in params and "brep" in params:
            raise InvalidArgument("duplicate feature has conflicting B-Rep sources")
        if op == "rename":
            _identifier(params.get("ref"), "body")
            if not isinstance(params.get("name"), str):
                raise InvalidArgument("rename requires a string name")
        if "brep_file" in params:
            _member_name(params["brep_file"], "shapes")
    seen = set()
    for meta in payload.get("assets", []):
        if not isinstance(meta, dict):
            raise InvalidArgument("asset metadata must be an object")
        _identifier(meta.get("id"), "asset")
        if meta["id"] in seen:
            raise InvalidArgument("duplicate asset id")
        seen.add(meta["id"])
        _member_name(meta.get("file"), "assets")
        if meta.get("role") not in ROLES:
            raise InvalidArgument("invalid image role")
        for key in ("label", "filename", "notes", "checksum", "media_type"):
            if not isinstance(meta.get(key, ""), str):
                raise InvalidArgument(f"asset {key} must be a string")
        if meta.get("camera_hint") is not None and not isinstance(meta["camera_hint"], dict):
            raise InvalidArgument("camera_hint must be an object")
        for key in ("width", "height"):
            if type(meta.get(key)) is not int or meta[key] <= 0:
                raise InvalidArgument("image dimensions must be positive integers")


def _validate_history(features):
    bodies, sketches = set(), set()
    modifiers = {"transform", "fillet", "chamfer", "shell", "hole", "mirror"}
    for feature in features:
        for ref in feature.input_refs:
            if ref not in bodies:
                raise InvalidArgument("feature refers to a missing or forward body dependency")
        for feature_id in feature.input_features:
            if feature_id not in sketches:
                raise InvalidArgument("feature refers to a missing or forward sketch dependency")
        if feature.op == "sketch":
            sketches.add(feature.id)
        if feature.output_ref:
            if feature.op in modifiers:
                if feature.params.get("target") != feature.output_ref:
                    raise InvalidArgument("modifier output must match its target")
            elif feature.output_ref in bodies:
                raise InvalidArgument("duplicate body producer")
            bodies.add(feature.output_ref)
        if feature.op == "delete":
            _identifier(feature.params.get("ref"), "body")
            bodies.discard(feature.params["ref"])
