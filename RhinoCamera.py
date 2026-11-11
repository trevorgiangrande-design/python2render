#! python 3
"""RhinoCamera.py - unpack RhinoRender's `camera` list into Grasshopper wires.

Grasshopper "Script" component (Python 3). Nothing in the Rhino file is changed.

Input   (set to List Access)
    camera     RhinoRender's `camera` output

Outputs - one item per camera (each camera once), so item i matches branch {i} of RhinoLight
    name       camera name (Camera0, Camera1, ...)
    location   camera position     (Rhino Point3d)
    target     point it looks at   (Rhino Point3d)
    fov        field of view in degrees
"""
import ast
import json

try:
    import Rhino.Geometry as rg
except ImportError:                 # outside Rhino (testing) - keep plain tuples
    rg = None


def to_point(value):
    """Rhino Point3d from a Point3d, an (x, y, z) tuple/list, or text like '1, 2, 3'."""
    if value is None:
        return None
    if rg is not None and isinstance(value, rg.Point3d):
        return value
    if isinstance(value, str):
        value = [float(v) for v in value.strip("()[]{} ").split(",")]
    x, y, z = (float(v) for v in value)
    return rg.Point3d(x, y, z) if rg is not None else (x, y, z)


def to_entry(value):
    """One entry as a dict - JSON text from RhinoRender, a Python/.NET dictionary, or dict-like text."""
    if isinstance(value, dict):
        return value
    if hasattr(value, "Keys"):                          # a .NET dictionary
        return {str(key): value[key] for key in value.Keys}
    text = str(value).strip()
    try:
        entry = json.loads(text)
    except ValueError:
        try:
            entry = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            entry = None
    if isinstance(entry, dict):
        return entry
    raise ValueError(unreadable(text))


def unreadable(text):
    """Say what arrived instead of a RhinoRender entry, and the likely fix."""
    shown = text if len(text) <= 120 else text[:117] + "..."
    if "Render lists in" in text or "images from" in text:
        hint = ("This is RhinoRender's printed log (its 'out' output). "
                "Connect RhinoRender's data output (camera / light / light_output / camera_output) instead.")
    elif "Rhino.Geometry" in text or "object at 0x" in text:
        hint = ("This comes from an older RhinoRender that sent Rhino points inside dictionaries. "
                "Paste the latest RhinoRender.py into that component - it now sends JSON text.")
    elif len(text) <= 1:
        hint = "Only a single character arrived - set this input to List Access."
    else:
        hint = 'Expected one RhinoRender entry, JSON text like {"name": "Camera0", ...}.'
    return f"Can't read this input: {shown!r}. {hint}"


def read_entries(value):
    """Accept a whole list (List Access) or a single entry (Item Access) - never split text into letters."""
    if value is None:
        return []
    if isinstance(value, (str, dict)) or hasattr(value, "Keys"):
        value = [value]
    return [to_entry(v) for v in value if v is not None and str(v).strip()]


entries = read_entries(globals().get("camera"))
name = [e["name"] for e in entries]
location = [to_point(e["location"]) for e in entries]
target = [to_point(e["target"]) for e in entries]
fov = [float(e["fov"]) for e in entries]
