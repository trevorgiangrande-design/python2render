#! python 3
"""RhinoRenderRunner.py - render every list in a render set, one after another, unattended.

Grasshopper "Script" component (Python 3). For each render list (default, uvw, objectid, ...):
  1. sets `render` (-> RhinoRender) and `frames` (-> V-Ray Timeline) for that list
  2. starts V-Ray's "Render Animation", exactly as the Render component's right-click menu does
  3. watches the output folder - <directory>\\<test_name>\\Renders, UVW or ObjectID, made by the
     output-folder script - until the list's LAST image has been written (after the start
     time, and no longer growing), then moves on to the next list
When every list is done it writes a run log (render_logs\\run_<date>_<time>.json) into the render
set folder and calls RenderManifest.make_manifest(directory, log_path).

Inputs
    directory     render set folder - the one RhinoRender reads (e.g. ...\\render_data\\cup)
    run           Button - start the run
    stop          Button - stop the run (also tells V-Ray to stop)
    renders       optional, List Access - which render indices to run (RhinoRender's numbering);
                  default: every render list in the folder. They always run in the order
                  Render (default) -> UVW -> ObjectID, test by test, however they are listed.
    frame_suffix  optional, default True - V-Ray appends the frame number to animation file names
                  (Camera0_Img0.00000.jpg); set False if that is switched off in V-Ray
    scripts_folder optional - the repo's scripts folder (RenderPackage.py, RenderManifest.py, ...).
                  Empty: the folder this .gh file is saved in.

The manifest's object name and units come from the active Rhino file (cup.3dm -> Cup, Millimeters -> mm),
read when run is pressed and saved in the run log.

Outputs
    render        -> RhinoRender's `render` input (instead of the slider)
    frames        -> the V-Ray Timeline's number of frames for the current list
    status        what the runner is doing
    progress      images written / images expected for the current list
    done          True once the whole run has finished
Live progress is also shown under the component while rendering.

Note: starting the render calls V-Ray's internal OnRenderAnimation method - it is what the menu
item runs, but it is not a documented V-Ray feature, so a V-Ray update could rename it.
"""
import datetime
import importlib
import json
import os
import re
import sys
import time

TYPE_ORDER = ["default", "uvw", "objectid"]
FOLDERS = {"default": "Renders", "uvw": "UVW", "objectid": "ObjectID"}    # output folder per render type
SECONDS_PER_IMAGE = {"default": 20, "uvw": 10, "objectid": 10}           # used only for the timeout
TIMEOUT_FACTOR = 3.0            # give up on a list after 3x its estimated time ...
TIMEOUT_MARGIN = 300            # ... plus 5 minutes
POLL_SECONDS = 2.0              # how often the output folder is checked
STABLE_CHECKS = 2               # the last image must keep the same size for this many checks
SETTLE_SECONDS = 3.0            # pause after switching lists so Grasshopper can update first


def find_scripts_folder(value=None, needs="RenderPackage.py"):
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

importlib.reload(RenderElements)
importlib.reload(RenderPackage)


# ---- planning (plain Python - no Rhino needed) ---------------------------------------------

def render_type_of(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    for render_type in TYPE_ORDER:
        if stem.endswith("_" + render_type):
            return render_type
    return None


def list_render_files(folder):
    """The render list CSVs, in the same order as RhinoRender: test by test, default/uvw/objectid."""
    if not os.path.isdir(folder):
        raise ValueError(f"'{folder}' is not a folder")
    files = [os.path.join(folder, n) for n in os.listdir(folder)
             if n.lower().endswith(".csv") and render_type_of(n)]
    if not files:
        raise ValueError(f"No render list CSVs in '{folder}'")

    def order(path):
        return test_name_of(path).lower(), TYPE_ORDER.index(render_type_of(path))

    return sorted(files, key=order)


def test_name_of(path):
    """cup_test_simple_default.csv -> cup_test_simple"""
    return os.path.basename(path)[:-len(f"_{render_type_of(path)}.csv")]


def expected_name(image, frame, frame_suffix=True):
    """A readable example of the file V-Ray writes for `image` at timeline `frame`
    (Camera0_Img0.jpg -> Camera0_Img0.00000.jpg). Matching uses image_key, so V-Ray's
    zero-padding (.0050, .00050, ...) doesn't matter."""
    if not frame_suffix:
        return image
    stem, ext = os.path.splitext(image)
    return f"{stem}.{frame:05d}{ext}"


FRAME_SUFFIX = re.compile(r"^(?P<stem>.+)\.(?P<frame>\d+)(?P<ext>\.[^.]+)$")


def image_key(file_name, frame_suffix=True):
    """What identifies an output file regardless of zero-padding: (name, frame number, extension).
    Camera16_Img2.0050.jpg and Camera16_Img2.00050.jpg both give ('camera16_img2', 50, '.jpg')."""
    if frame_suffix:
        match = FRAME_SUFFIX.match(file_name)
        if not match:
            return None
        return match["stem"].lower(), int(match["frame"]), match["ext"].lower()
    stem, ext = os.path.splitext(file_name)
    return stem.lower(), None, ext.lower()


def job_keys(job):
    """The job's image keys - worked out here if the job came from an older version of this script
    (Grasshopper keeps a running job list between code edits)."""
    if "keys" not in job:
        job.setdefault("frame_suffix", True)
        job["keys"] = [image_key(name, job["frame_suffix"]) for name in job["names"]]
    return job["keys"]


def scan_folder(job, since):
    """{image key: (path, size)} for files in the job's folder written after `since`."""
    found = {}
    if not os.path.isdir(job["folder"]):
        return found
    with os.scandir(job["folder"]) as entries:
        for entry in entries:
            key = image_key(entry.name, job.get("frame_suffix", True))
            if key is None:
                continue
            info = entry.stat()
            if info.st_mtime >= since:
                found[key] = (entry.path, info.st_size)
    return found


def plan_run(directory, renders=None, frame_suffix=True):
    """One job per render list: which folder its images go to, their expected names and the last one."""
    files = list_render_files(directory)
    # Always Render -> UVW -> ObjectID (test by test), whatever order `renders` lists them in;
    # the file list is already in that order, so sorting the indices is enough. Repeats are dropped.
    indices = list(range(len(files))) if not renders else sorted({int(i) for i in renders})
    jobs = []
    for index in indices:
        if not 0 <= index < len(files):
            raise IndexError(f"render {index} doesn't exist - this folder has {len(files)} render lists (0-{len(files) - 1})")
        path = files[index]
        render_type = render_type_of(path)
        images = [image for row in RenderPackage.read_renders(path) for image in row.output.name_list()]
        names = [expected_name(image, frame, frame_suffix) for frame, image in enumerate(images)]
        # images go to <directory>\<test_name>\Renders (UVW, ObjectID) - the folders the output-folder script makes
        folder = os.path.join(directory, test_name_of(path), FOLDERS.get(render_type, render_type))
        estimate = len(images) * SECONDS_PER_IMAGE.get(render_type, 20)
        jobs.append({
            "index": index,
            "csv": os.path.basename(path),
            "test_name": test_name_of(path),
            "render_type": render_type,
            "folder": folder,
            "frame_suffix": frame_suffix,
            "count": len(names),
            "names": names,
            "keys": [image_key(name, frame_suffix) for name in names],
            "last": os.path.join(folder, names[-1]) if names else None,
            "estimate_seconds": estimate,
            "timeout_seconds": estimate * TIMEOUT_FACTOR + TIMEOUT_MARGIN,
        })
    return jobs


def written_count(job, since):
    """How many of the job's expected images exist and were written after `since` (a timestamp)."""
    found = scan_folder(job, since)
    return sum(1 for key in job_keys(job) if key in found)


def last_image_size(job, since):
    """Size of the job's last image if it was written after `since`, else None.
    The real file name (whatever V-Ray's padding) is remembered in job['last_written']."""
    keys = job_keys(job)
    if not keys:
        return None
    hit = scan_folder(job, since).get(keys[-1])
    if hit is None or hit[1] <= 0:
        return None
    job["last_written"] = hit[0]
    return hit[1]


def as_index_list(value):
    """The `renders` input as a list of ints - nothing, one number, or a list of numbers."""
    if value is None:
        return []
    if isinstance(value, (int, float, str)):
        return [int(value)]
    return [int(v) for v in value if v is not None]


def write_run_log(directory, run):
    folder = os.path.join(directory, "render_logs")
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.datetime.fromtimestamp(run["started"]).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(folder, f"run_{stamp}.json")
    jobs = [{k: v for k, v in job.items() if k not in ("names", "keys")} for job in run["jobs"]]   # re-derivable
    with open(path, "w") as f:
        json.dump({"directory": directory, "started": run["started"], "finished": run.get("finished"),
                   "status": run["phase"], "message": run.get("message", ""),
                   "rhino_file": run.get("rhino_file"), "units": run.get("units"), "jobs": jobs}, f, indent=2)
    return path


def call_manifest(directory, log_path, object_name=None, units=None):
    """Run RenderManifest.make_manifest(directory, log_path, object_name, units) from the scripts folder.

    Loaded straight from its file (fresh every run) rather than with `import`: Python remembers which
    files were in a folder when it first imported from it, so a file added while Rhino is open
    isn't found by `import` until Rhino restarts."""
    import importlib.util
    path = os.path.join(SCRIPTS_FOLDER, "RenderManifest.py")
    if not os.path.isfile(path):
        return f"no RenderManifest.py in {SCRIPTS_FOLDER} - skipped the manifest"
    try:
        importlib.invalidate_caches()
        spec = importlib.util.spec_from_file_location("RenderManifest", path)
        RenderManifest = importlib.util.module_from_spec(spec)
        sys.modules["RenderManifest"] = RenderManifest
        spec.loader.exec_module(RenderManifest)
    except Exception as error:                       # show the real reason, not "not found"
        return f"RenderManifest.py couldn't be loaded ({type(error).__name__}: {error}) - skipped the manifest"
    make = getattr(RenderManifest, "make_manifest", None)
    if make is None:
        return "RenderManifest.py has no make_manifest() - skipped the manifest"
    result = make(directory, log_path, object_name, units)
    return f"manifest: {result}" if result else "manifest step ran"


# ---- Grasshopper / V-Ray glue ---------------------------------------------------------------

def find_renderer(doc):
    """The single V-Ray Render component on the canvas (not 'Render in Project')."""
    found = [obj for obj in doc.Objects
             if obj.GetType().Name.startswith("VRayRendererComponent") and "Doc" not in obj.GetType().Name
             and not getattr(obj, "Locked", False)]
    if len(found) != 1:
        raise RuntimeError(f"Expected one enabled V-Ray Render component on the canvas, found {len(found)}")
    return found[0]


def call_menu_action(component, method_name):
    """Run one of a component's right-click menu actions (e.g. OnRenderAnimation) by name."""
    import System
    from System.Reflection import BindingFlags
    flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly
    kind = component.GetType()
    method = None
    while kind is not None and method is None:              # the method may live on a base class
        method = kind.GetMethod(method_name, flags)
        kind = kind.BaseType
    if method is None:
        raise RuntimeError(f"{component.GetType().Name} has no {method_name} - V-Ray may have renamed it")
    args = [System.EventArgs.Empty if "EventArgs" in p.ParameterType.Name else None for p in method.GetParameters()]
    return method.Invoke(component, System.Array[System.Object](args))


def run_gh_component():
    import Rhino
    import scriptcontext as sc
    import Grasshopper
    from Grasshopper.Kernel import GH_ProcessStep

    component = ghenv.Component
    key = f"RhinoRenderRunner_{component.InstanceGuid}"
    run = sc.sticky.get(key)
    if run is None:
        run = {"phase": "idle", "message": "Press run to start", "jobs": [], "current": 0}
        sc.sticky[key] = run

    def detach():
        handler = run.pop("handler", None)
        if handler is not None:
            try:
                Rhino.RhinoApp.Idle -= handler
            except Exception:
                pass

    def finish(phase, message, recompute=True):
        """End the run. `recompute=False` when already inside a Grasshopper solution."""
        detach()
        run["phase"], run["message"], run["finished"] = phase, message, time.time()
        try:
            run["log"] = write_run_log(run["directory"], run)
            if phase == "done":
                name = os.path.splitext(run["rhino_file"])[0] if run.get("rhino_file") else None
                result = call_manifest(run["directory"], run["log"], name, run.get("units"))
                run["message"] = f"{message} - {result}"
                write_run_log(run["directory"], run)     # same file again, now with the manifest result
        except Exception as error:                       # never lose the result over the log
            run["message"] = f"{message} (log/manifest failed: {error})"
        component.Message = phase
        if recompute:
            component.ExpireSolution(True)

    def on_idle(sender, event):
        try:
            now = time.time()
            if now - run.get("last_poll", 0) < POLL_SECONDS:
                return
            run["last_poll"] = now
            doc = component.OnPingDocument()
            if doc is None:
                detach()
                return
            if doc.SolutionState == GH_ProcessStep.Process or now < run.get("settle_until", 0):
                return                                    # let Grasshopper finish updating first
            job = run["jobs"][run["current"]]

            if run["phase"] == "starting":
                run["phase"] = "rendering"
                job["started"] = time.time()
                run["stable"], run["last_size"] = 0, None
                component.Message = f"rendering {job['render_type']}"
                Grasshopper.Instances.RedrawCanvas()
                call_menu_action(find_renderer(doc), "OnRenderAnimation")
                return

            if run["phase"] == "rendering":
                written = written_count(job, job["started"])
                component.Message = f"{job['render_type']} {written}/{job['count']}"
                Grasshopper.Instances.RedrawCanvas()
                size = last_image_size(job, job["started"])
                if size is not None and size == run.get("last_size"):
                    run["stable"] += 1
                else:
                    run["stable"] = 0
                run["last_size"] = size
                if size is not None and run["stable"] >= STABLE_CHECKS:      # last image fully written
                    job["finished"] = time.time()
                    job["seconds"] = round(job["finished"] - job["started"], 1)
                    job["written"] = written_count(job, job["started"])
                    job["seconds_per_image"] = round(job["seconds"] / max(job["written"], 1), 2)
                    job["status"] = "done"
                    if run["current"] + 1 < len(run["jobs"]):
                        run["current"] += 1
                        run["phase"] = "starting"
                        run["settle_until"] = time.time() + SETTLE_SECONDS
                        component.ExpireSolution(True)     # new render / frames outputs -> RhinoRender, Timeline
                    else:
                        finish("done", f"Finished {len(run['jobs'])} render lists")
                elif time.time() - job["started"] > job["timeout_seconds"]:
                    job["status"] = "timed out"
                    finish("failed", f"Timed out waiting for {os.path.basename(job['last'])}")
        except Exception as error:
            finish("failed", f"{type(error).__name__}: {error}")

    # -- this solution --------------------------------------------------------------------------
    active = run["phase"] in ("starting", "rendering")
    if globals().get("stop") and active:
        try:
            call_menu_action(find_renderer(component.OnPingDocument()), "OnStop")
        except Exception:
            pass
        if run["jobs"]:
            run["jobs"][run["current"]]["status"] = "stopped"
        finish("stopped", "Stopped by user", recompute=False)
        active = False
    elif globals().get("run") and not active:
        directory = str(globals().get("directory") or "").strip().strip('"')
        renders = as_index_list(globals().get("renders"))
        frame_suffix = globals().get("frame_suffix")
        detach()
        jobs = plan_run(directory, renders or None, True if frame_suffix is None else bool(frame_suffix))
        run.clear()
        run.update({"phase": "starting", "directory": directory, "jobs": jobs, "current": 0,
                    "rhino_file": Rhino.RhinoDoc.ActiveDoc.Name if Rhino.RhinoDoc.ActiveDoc else None,
                    "units": Rhino.RhinoDoc.ActiveDoc.ModelUnitSystem.ToString() if Rhino.RhinoDoc.ActiveDoc else None,
                    "started": time.time(), "settle_until": time.time() + SETTLE_SECONDS,
                    "message": f"Starting {len(jobs)} render lists"})
        run["handler"] = on_idle
        Rhino.RhinoApp.Idle += on_idle
        active = True
    elif active:                                          # mid-run: always watch with THIS version of the code
        detach()                                          # (after an edit, the old watcher would keep old logic)
        run["handler"] = on_idle
        Rhino.RhinoApp.Idle += on_idle

    job = run["jobs"][run["current"]] if run["jobs"] else None
    outputs = {
        "render": job["index"] if job else None,
        "frames": job["count"] if job else None,
        "status": run["message"] if not active else
                  f"List {run['current'] + 1}/{len(run['jobs'])}: {job['csv']} ({run['phase']})",
        "progress": f"{written_count(job, job['started'])}/{job['count']}" if job and job.get("started") else None,
        "done": run["phase"] == "done",
    }
    return outputs


if "ghenv" in globals():
    _out = run_gh_component()
    render, frames, status, progress, done = (_out["render"], _out["frames"], _out["status"],
                                              _out["progress"], _out["done"])
