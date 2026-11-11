#! python 3
"""RhinoCameraOutput.py - unpack RhinoRender's `camera_output` list into Grasshopper wires.

Grasshopper "Script" component (Python 3). Nothing in the Rhino file is changed.

Input   (set to List Access)
    camera_output    RhinoRender's `camera_output` output

Outputs - one item per camera (same order as RhinoCamera), except `image`:
    image            data tree, branch {i} = camera i's image names, one per light condition
                     (Camera3_Img0.jpg, Camera3_Img1.jpg, ... or Camera3_UVW.jpg)
    width            image width in pixels
    height           image height in pixels
    extension        .jpg / .jpeg / .png
    render_type      default / uvw / objectid
    source           the render list CSV it came from
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


entries = read_entries(globals().get("camera_output"))
image_groups = [list(e["images"]) if "images" in e else [e["image"]] for e in entries]
image = by_camera([{"camera_index": i} for i, group in enumerate(image_groups) for _ in group],
                  [name for group in image_groups for name in group])
width = [int(e["width"]) for e in entries]
height = [int(e["height"]) for e in entries]
extension = [e["extension"] for e in entries]
render_type = [e["render_type"] for e in entries]
source = [e["source"] for e in entries]
