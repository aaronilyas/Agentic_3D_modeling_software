"""Provider-neutral image bytes and metadata, separate from tool JSON."""
from __future__ import annotations

import base64
import copy
import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageResource:
    uri: str
    media_type: str
    data: bytes
    metadata: dict

    def image_block(self) -> dict:
        return {"type": "image", "mimeType": self.media_type,
                "data": base64.b64encode(self.data).decode("ascii")}


def reference_resource(asset) -> ImageResource:
    return ImageResource(f"cad://references/{asset.id}/{asset.checksum}",
                         asset.media_type, asset.data, copy.deepcopy(asset.public()))


def split_images(value) -> tuple[dict, list[ImageResource]]:
    """Normalize existing render envelopes without changing execute's JSON API."""
    images = []

    def visit(item, revision=None):
        if isinstance(item, list):
            return [visit(child, revision) for child in item]
        if not isinstance(item, dict):
            return copy.deepcopy(item)
        revision = item.get("revision", revision)
        result = {key: visit(child, revision) for key, child in item.items() if key != "png_base64"}
        if "png_base64" in item:
            data = base64.b64decode(item["png_base64"], validate=True)
            uri = "cad://renders/" + hashlib.sha256(data).hexdigest()
            images.append(ImageResource(uri, "image/png", data, {**copy.deepcopy(result), "revision": revision}))
            result["image_uri"] = uri
        return result

    return visit(value), images
