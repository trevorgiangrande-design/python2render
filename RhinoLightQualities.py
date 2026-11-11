#! python 3
"""RhinoLightQualities.py - unpack RhinoRender's `light_output` list into Grasshopper wires.

Grasshopper "Script" component (Python 3). Nothing in the Rhino file is changed.

Input   (set to List Access)
    light_output     RhinoRender's `light_output` output (the light's qualities)

Outputs - data trees with one branch per camera: branch {i} holds the qualities of
camera i's lights, in the same order as RhinoLight's branch {i}.
    rgb              light colour as (r, g, b), each 0-255
    intensity        0.0 - 1.0
    shadow_softness  0.0 - 1.0
"""
import ast
import json


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


entries = read_entries(globals().get("light_output"))
rgb = by_camera(entries, [tuple(int(c) for c in e["rgb"]) for e in entries])
intensity = by_camera(entries, [float(e["intensity"]) for e in entries])
shadow_softness = by_camera(entries, [float(e["shadow_softness"]) for e in entries])
