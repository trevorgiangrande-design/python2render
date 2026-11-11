#! python 3
"""RhinoRender.py - read one render list (CSV) from a render set folder, for Rhino 8.

Use it in a Grasshopper "Script" component (Python 3), or run it from Rhino 8's ScriptEditor.

Inputs
    directory  folder that holds a render set, e.g. ...\\Pipeline\\render_data\\cup
    render  which CSV in that folder to read (an int):
                0 = default, 1 = uvw, 2 = objectid
            If the folder holds several tests they follow on in name order:
                3, 4, 5 = the next test's default, uvw, objectid, and so on.
    scripts_folder  optional - the repo's scripts folder (RenderElements.py, RenderPackage.py, ...).
            Empty: the folder this .gh file is saved in.

Outputs - cameras are listed once each; lights are listed once per light condition:
    camera         one entry per camera
                   {"name", "location", "target", "fov"}
    camera_output  one entry per camera (same order as camera)
                   {"images", "width", "height", "extension", "material", "render_type", "source"}
                   "images" holds that camera's image names, one per light condition
    light          one entry per light condition, grouped camera by camera
                   {"name", "camera_index", "image", "on", "condition", "location", "target",
                    "distance", "elevation"}
    light_output   one entry per light condition (same order as light)
                   {"camera_index", "rgb", "intensity", "shadow_softness"}   (the light's qualities)
    test_name      the render list's test name as plain text, e.g. cup_test_simple
                   (the CSV name without _default / _uvw / _objectid)
"camera_index" says which camera a light belongs to; RhinoLight / RhinoLightQualities use it to
group the lights into one Grasshopper branch per camera, so camera i pairs with branch {i}.
A default render has 3 lights (images) per camera; uvw / objectid have 1 (switched off).

Each entry is JSON text (readable in a Panel), because Grasshopper turns Python dictionaries
into text on the wire anyway. Locations are [x, y, z]; the RhinoCamera / RhinoLight / ...
components read this text and turn the locations into Rhino Point3d values.
"""
import importlib
import json
import os
import sys

DEFAULT_RENDER = 0                      # used when run from the ScriptEditor without inputs
TYPE_ORDER = ["default", "uvw", "objectid"]


def find_scripts_folder(value=None, needs="RenderPackage.py"):
    """Where RenderElements.py and RenderPackage.py live: the `scripts_folder` input, else the folder
    the .gh file is saved in (else this file's own folder when run outside Grasshopper)."""
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
    if not os.path.isfile(os.path.join(folder, needs)):
        raise ValueError(f"{needs} isn't in {folder} (from {source}) - "
                         "point scripts_folder at the repo's scripts folder")
    return os.path.normpath(folder)


SCRIPTS_FOLDER = find_scripts_folder(globals().get("scripts_folder"))
if SCRIPTS_FOLDER in sys.path:
    sys.path.remove(SCRIPTS_FOLDER)
sys.path.insert(0, SCRIPTS_FOLDER)      # first, so this copy's modules win over any other copy
import RenderElements
import RenderPackage

# Grasshopper keeps imported modules between runs - reload so edits to these files are picked up
importlib.reload(RenderElements)
importlib.reload(RenderPackage)

def to_point(xyz):
    """[x, y, z] for the JSON text - the Rhino* components turn these into Point3d."""
    return [float(v) for v in xyz]


def as_text(entry):
    return json.dumps(entry)


def render_type_of(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    for render_type in TYPE_ORDER:
        if stem.endswith("_" + render_type):
            return render_type
    return None


def test_name_of(path):
    """cup_test_simple_default.csv -> cup_test_simple"""
    return os.path.basename(path)[:-len(f"_{render_type_of(path)}.csv")]


def list_render_files(folder):
    """The render list CSVs in a folder, ordered test by test as default, uvw, objectid."""
    if not os.path.isdir(folder):
        raise ValueError(f"'{folder}' is not a folder")
    files = [os.path.join(folder, name) for name in os.listdir(folder)
             if name.lower().endswith(".csv") and render_type_of(name)]
    if not files:
        raise ValueError(f"No render list CSVs (*_default.csv, *_uvw.csv, *_objectid.csv) in '{folder}'")

    def order(path):
        return test_name_of(path).lower(), TYPE_ORDER.index(render_type_of(path))

    return sorted(files, key=order)


def read_render_list(path):
    """Cameras once each (camera, camera_output) and lights once per condition (light,
    light_output), with every light tagged with the index of its camera."""
    render_type = render_type_of(path)
    cameras, lights, light_outputs, camera_outputs = [], [], [], []
    for camera_index, row in enumerate(RenderPackage.read_renders(path)):
        cam, lamp, output = row.camera, row.light, row.output
        qualities = lamp.qualities
        images = output.name_list()                    # one per light condition
        light_locations = lamp.locations()[0]          # one per light condition, in image order
        width, height = output.dimensions

        cameras.append(as_text({
            "name": cam.name,
            "location": to_point(cam.startloc),
            "target": to_point(cam.endloc),
            "fov": cam.FOV,
        }))
        camera_outputs.append(as_text({
            "images": images,
            "width": width,
            "height": height,
            "extension": output.extension,
            "material": row.material,
            "render_type": render_type,
            "source": os.path.basename(path),
        }))

        for condition, image in enumerate(images):
            location = light_locations[condition] if condition < len(light_locations) else None
            lights.append(as_text({
                "name": f"{cam.name}_L{condition}",
                "camera_index": camera_index,
                "image": image,
                "on": lamp.on,
                "condition": condition,
                "location": to_point(location) if location is not None else None,
                "target": to_point(cam.endloc),
                "distance": lamp.distance,
                "elevation": lamp.azimuth,
            }))
            light_outputs.append(as_text({
                "camera_index": camera_index,
                "rgb": list(qualities.rgb),
                "intensity": qualities.intensity,
                "shadow_softness": qualities.shadowsoftness,
            }))
    return cameras, lights, light_outputs, camera_outputs


# ---- run -------------------------------------------------------------------------------
# In Grasshopper, "directory" and "render" are the component inputs. Run on its own (no inputs),
# fall back to the newest render set folder instead.
directory = globals().get("directory")
if isinstance(directory, str) and directory.strip():
    folder = directory.strip().strip('"')
else:
    sets = [os.path.join(RenderPackage.RENDER_DATA_FOLDER, d) for d in os.listdir(RenderPackage.RENDER_DATA_FOLDER)
            if os.path.isdir(os.path.join(RenderPackage.RENDER_DATA_FOLDER, d)) and d != "previews"] \
        if os.path.isdir(RenderPackage.RENDER_DATA_FOLDER) else []
    if not sets:
        raise ValueError("Give 'directory' a render set folder (none found in render_data)")
    folder = max(sets, key=os.path.getmtime)

index = globals().get("render")
index = DEFAULT_RENDER if index is None else int(index)

render_files = list_render_files(folder)
print(f"Render lists in {folder}:")
for i, path in enumerate(render_files):
    print(f"  {i}: {os.path.basename(path)}{'   <- render' if i == index else ''}")
if not 0 <= index < len(render_files):
    raise IndexError(f"render = {index}, but this folder only has {len(render_files)} render lists (0-{len(render_files) - 1})")

camera, light, light_output, camera_output = read_render_list(render_files[index])
test_name = test_name_of(render_files[index])
print(f"{len(camera)} cameras, {len(light)} images from {os.path.basename(render_files[index])}")
