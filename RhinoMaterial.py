#! python 3
"""RhinoMaterial.py - the .vrmat file for a render list.

Gives the full path of the render list's material, ready for the hidden text input
on V-Ray's "Material from File" component (drag the wire onto its left edge).
Nothing in the Rhino file is changed.

Grasshopper "Script" component (Python 3).

Inputs
    camera_output    RhinoRender's `camera_output` output   (set to List Access)
    scripts_folder   optional - the repo's scripts folder; the .vrmat files are in its materials
                     folder. Empty: the folder this .gh file is saved in.
    materials_folder optional - folder holding the .vrmat files, if they're somewhere else
                     (overrides scripts_folder)

Outputs
    path             full path of the render list's .vrmat, e.g.
                     <scripts_folder>\\materials\\default.vrmat
                     (one item - every camera in a render list uses the same material)
    material         .vrmat file name for each camera, in the same order as RhinoCamera
"""
import ast
import json
import os



def find_scripts_folder(value=None, needs="materials"):
    """The scripts folder: the `scripts_folder` input, else the folder the .gh file is saved in
    (else this file's own folder when run outside Grasshopper)."""
    if value is not None and str(value).strip():
        folder, source = str(value).strip().strip('"'), "the scripts_folder input"
    else:
        folder, source = None, None
        gh = globals().get("ghenv")
        if gh is not None:
            doc = gh.Component.OnPingDocument()
            if doc is not None and doc.FilePath:
                folder, source = os.path.dirname(doc.FilePath), "the .gh file's folder"
        elif "__file__" in globals():
            folder, source = os.path.dirname(os.path.abspath(__file__)), "this script's folder"
        if folder is None:
            raise ValueError("Connect scripts_folder (your copy of the repo's scripts folder), "
                             "or save this .gh file into that folder")
    if not os.path.exists(os.path.join(folder, needs)):
        raise ValueError(f"{needs} isn't in {folder} (from {source}) - "
                         "point scripts_folder at the repo's scripts folder")
    return os.path.normpath(folder)


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


entries = read_entries(globals().get("camera_output"))
material = [e["material"] for e in entries]

folder = globals().get("materials_folder")
if folder and str(folder).strip():
    folder = str(folder).strip().strip('"')
else:
    folder = os.path.join(find_scripts_folder(globals().get("scripts_folder")), "materials")

names = sorted(set(material))
if not names:
    path = None
elif len(names) > 1:
    raise ValueError(f"This render list mixes materials ({', '.join(names)}) - expected one per list")
else:
    path = os.path.join(folder, names[0])
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{names[0]} isn't in {folder} - check materials_folder or the file name")
