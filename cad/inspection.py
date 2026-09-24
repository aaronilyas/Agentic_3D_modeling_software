"""Read-only topology and rendering service; selections belong to callers."""

from cad.errors import InvalidArgument, StaleSelection
from cad.numbers import vec3, positive_int, positive_number
from cad.render import VIEWS, render_meshes
from cad.topology import adjacent_ids, assign_ids


def require_current_selection(revision: int, arguments: dict, ids) -> None:
    if ids is not None and (not isinstance(ids, list) or any(not isinstance(item, str) for item in ids)):
        raise InvalidArgument("topology ids must be a list of strings")
    if not ids:
        return
    selected_revision = arguments.get("selection_revision")
    if type(selected_revision) is not int or selected_revision != revision:
        raise StaleSelection(
            f"selection revision {selected_revision} does not match document revision {revision}"
        )


class InspectionService:
    def __init__(self, document, backend):
        self.document = document
        self.backend = backend

    def query(self, ref: str, kind: str, arguments: dict) -> dict:
        point = vec3(arguments["nearest"], "nearest") if arguments.get("nearest") is not None else None
        raw = self.backend.query(self.document.resolve(ref), point)
        faces = assign_ids("face", raw["faces"])
        edges = assign_ids("edge", raw["edges"])
        adjacent_ids(faces, edges)
        records = faces if kind == "faces" else edges
        geom = arguments.get("geom")
        if geom not in {None, "any", "plane", "cylinder", "sphere", "torus", "cone", "line", "circle"}:
            raise InvalidArgument("geom filter is not supported")
        if geom not in {None, "any"}:
            records = [record for record in records if record["geom"] == geom]
        order = arguments.get("order")
        if order not in {None, "largest", "smallest"}:
            raise InvalidArgument("order must be largest or smallest")
        if order == "largest":
            records = sorted(records, key=lambda item: item.get("area", item.get("length", 0.0)), reverse=True)
        elif order == "smallest":
            records = sorted(records, key=lambda item: item.get("area", item.get("length", 0.0)))
        elif arguments.get("nearest") is not None:
            records = sorted(records, key=lambda item: item.get("distance", 0.0))
        limit = arguments.get("limit")
        if limit is not None:
            records = records[: positive_int(limit, "limit")]
        for record in records:
            record.pop("index", None)
            record.pop("face_indices", None)
        return {
            "ref": ref,
            "revision": self.document.revision,
            "units": "mm",
            kind: records,
        }

    def render(self, arguments: dict, *, highlight: bool) -> dict:
        if highlight and not arguments.get("ref"):
            raise InvalidArgument("render_selection requires a ref")
        width = positive_int(arguments.get("width", 160), "width")
        height = positive_int(arguments.get("height", 120), "height")
        if width < 32 or height < 32 or width > 512 or height > 512:
            raise InvalidArgument("render size must be between 32 and 512")
        views = arguments.get("views", ["isometric"] if highlight else list(VIEWS))
        if not isinstance(views, list) or not views:
            raise InvalidArgument("views must be a nonempty list")
        if any(not isinstance(view, str) or view not in VIEWS for view in views):
            raise InvalidArgument("unsupported render view")
        refs = [arguments["ref"]] if arguments.get("ref") else list(self.document.references())
        for ref in refs:
            self.document.resolve(ref)
        chord = positive_number(arguments.get("chord_tolerance", 0.25), "chord_tolerance")
        meshes = []
        for ref in refs:
            mesh = self.backend.tessellate(self.document.resolve(ref), chord)
            meshes.append(mesh)
        if highlight:
            face_ids = arguments.get("face_ids") or []
            edge_ids = arguments.get("edge_ids") or []
            if edge_ids:
                raise InvalidArgument("edge highlighting is not supported; use face_ids")
            if not face_ids:
                raise InvalidArgument("render_selection requires face_ids")
            require_current_selection(self.document.revision, arguments, face_ids)
            if face_ids:
                if len(refs) != 1:
                    raise InvalidArgument("render_selection needs a ref")
                selected = self.backend.tessellate_faces(self.document.resolve(refs[0]), face_ids, chord)
                selected["highlight"] = True
                meshes.append(selected)
        images = render_meshes(meshes, views, width, height)
        return {"revision": self.document.revision, "units": "mm", "views": images}
