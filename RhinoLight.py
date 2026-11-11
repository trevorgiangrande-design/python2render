#! python 3
"""RhinoLight.py - unpack RhinoRender's `light` list into Grasshopper wires.

Grasshopper "Script" component (Python 3). Nothing in the Rhino file is changed.

Input   (set to List Access)
    light      RhinoRender's `light` output

Outputs - data trees with one branch per camera: branch {i} holds camera i's lights
(3 for a default render, 1 switched-off light for uvw / objectid), so camera i from
RhinoCamera pairs with branch {i}. Items within a branch are in light-condition order.
    name       light name (Camera3_L0, Camera3_L1, ...)
    image      the image this light condition produces (Camera3_Img0, ...)
    on         True if the light is on for that image (False for UVW / Object ID)
    condition  light condition number (0, 1, 2, ... - matches _Img0, _Img1, ...)
    location   light position      (Rhino Point3d, at its true distance)
    target     point it shines at  (Rhino Point3d)
    distance   distance from the target
    elevation  angle above the ground plane, in degrees
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


try:                                # Grasshopper data trees: one branch per camera
    from Grasshopper import DataTree
    from Grasshopper.Kernel.Data import GH_Path
except ImportError:                 # outside Grasshopper (testing) - nested lists instead
    DataTree = None


def by_camera(entries, values):
    """Group values into one branch per camera: branch {i} holds camera i's items
    (its lights / images), so camera i from RhinoCamera pairs with branch {i}."""
    groups = {}
    for i, (entry, value) in enumerate(zip(entries, values)):
        groups.setdefault(int(entry.get("camera_index", i)), []).append(value)
    count = max(groups) + 1 if groups else 0
    if DataTree is None:
        return [groups.get(i, []) for i in range(count)]
    tree = DataTree[object]()
    for i in range(count):
        path = GH_Path(i)
        tree.EnsurePath(path)
        for value in groups.get(i, []):
            tree.Add(value, path)
    return tree


def read_entries(value):
    """Accept a whole list (List Access) or a single entry (Item Access) - never split text into letters."""
    if value is None:
        return []
    if isinstance(value, (str, dict)) or hasattr(value, "Keys"):
        value = [value]
    return [to_entry(v) for v in value if v is not None and str(v).strip()]


entries = read_entries(globals().get("light"))
name = by_camera(entries, [e["name"] for e in entries])
image = by_camera(entries, [e.get("image") for e in entries])
on = by_camera(entries, [bool(e["on"]) for e in entries])
condition = by_camera(entries, [int(e["condition"]) for e in entries])
location = by_camera(entries, [to_point(e["location"]) for e in entries])
target = by_camera(entries, [to_point(e["target"]) for e in entries])
distance = by_camera(entries, [float(e["distance"]) for e in entries])
elevation = by_camera(entries, [float(e["elevation"]) for e in entries])
