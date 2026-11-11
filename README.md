# python2render

Generates V-Ray render datasets of an object from Rhino 8 + Grasshopper: camera sweeps around the
object, three light conditions per camera, plus UVW and Object ID passes. Each run ends with a
`<test_name>_Vray_CameraData.xlsx` manifest describing every image.

This repository holds **code only**. Render sets, renders, Rhino models and manifests live in the
team's shared cloud folder.

## Requirements

- Rhino 8 with V-Ray 7 for Rhino (Grasshopper components included)
- For the visualizer only: Python 3.10+ with `PyQt6`, `pyvista`, `numpy`, `imageio`
  ```
  pip install PyQt6 pyvista numpy imageio
  ```

## Setup

1. Clone the repository anywhere:
   ```
   git clone https://github.com/trevorgiangrande-design/python2render.git
   ```
2. Open `python2render.gh` from your clone. The components find the scripts from where the `.gh`
   file is saved. If you open a `.gh` saved somewhere else, connect a Panel with the path to your
   clone to the `scripts_folder` input of **RhinoRender**, **RhinoRenderRunner** and **RhinoMaterial**.
3. Point the `directory` panel at a render set folder in the shared cloud folder.

The visualizer saves new render sets to a `render_data` folder next to the clone
(`<clone>/../render_data/<folder>`), outside the repository.

## Workflow

1. **Measure the model** (optional) - run `RhinoSceneInfo.py` from Rhino's ScriptEditor.
   It writes `<model>_scene.json` next to the `.3dm` (units, bounding box, centroid).
2. **Plan the cameras** - `python RenderVisualizer.py path/to/model.obj` previews camera
   sweeps and writes a render set: `<test_name>_default.csv`, `_uvw.csv`, `_objectid.csv`.
3. **Render** - in Grasshopper, press **run** on RhinoRenderRunner. It renders every list in order
   (Render -> UVW -> ObjectID), waiting for each list's last image before starting the next.
4. **Manifest** - when the last list finishes, the runner calls `RenderManifest.py`, which removes
   V-Ray's frame numbers from the image names and writes the Excel manifest.
   It can also be run on its own:
   ```
   python RenderManifest.py path/to/render_set
   ```

## Render set layout

```
<render set>/                         e.g. cup
    <test>_default.csv                render lists (one row per camera)
    <test>_uvw.csv
    <test>_objectid.csv
    render_logs/run_<date>_<time>.json   timing per list, Rhino file, units
    <test>/
        Renders/   UVW/   ObjectID/   images, e.g. Camera0_Img0.jpg
        <test>_Vray_CameraData.xlsx
```

## Scripts

| File | Where it runs | What it does |
|---|---|---|
| `RenderElements.py` | anywhere | Camera, Light, Light_Qualities, Camera_Output classes |
| `RenderPackage.py` | anywhere | Render class, reads/writes the render list CSVs |
| `RenderLocations.py` | Python 3.10+ | camera sweep points (presets: full, front, global) |
| `RenderVisualizer.py` | Python 3.10+ | camera sweep preview, simulation, saves render sets |
| `RenderManifest.py` | anywhere | strips frame numbers, writes the Excel manifest |
| `RhinoRender.py` | Grasshopper | reads one render list for the V-Ray components |
| `RhinoCamera.py`, `RhinoLight.py`, `RhinoLightQualities.py`, `RhinoCameraOutput.py` | Grasshopper | unpack RhinoRender's outputs |
| `RhinoMaterial.py` | Grasshopper | `.vrmat` path for V-Ray's Material from File |
| `RhinoRenderRunner.py` | Grasshopper | runs every render list unattended, then the manifest |
| `RhinoSceneInfo.py` | Rhino ScriptEditor | measures the model into `<model>_scene.json` |
| `materials/*.vrmat` | V-Ray | default, UVW and Object ID materials |
