import csv
import os
from RenderElements import Camera, Light, Camera_Output

# Pipeline\render_data - found from this file's location, so it works from any terminal folder
RENDER_DATA_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render_data")

class Render():

    HEADER = ["camera", "light", "output", "material"]

    def __init__(self, camera, light, output, material = "default.vrmat"):
        self.camera = camera
        self.light = light
        self.output = output
        self.material = material

    @property
    def camera(self):
        return self._camera

    @camera.setter
    def camera(self, camera):
        if not isinstance(camera, Camera):
            raise ValueError("Render did not recieve a camera object")
        self._camera = camera

    @property
    def light(self):
        return self._light

    @light.setter
    def light(self, light):
        if not isinstance(light, Light):
            raise ValueError("Render did not recieve a light object")
        if light.refcamera is not self.camera:
            raise ValueError("Light does not belong to this camera")
        self._light = light

    @property
    def output(self):
        return self._output

    @output.setter
    def output(self, output):
        if not isinstance(output, Camera_Output):
            raise ValueError("Render did not recieve a Camera_Output")
        if output.reflighting is not self.light:
            raise ValueError("Output does not belong to this light")
        self._output = output

    @property
    def material(self):
        return self._material

    @material.setter
    def material(self, material):
        materials = ["default.vrmat","objectid.vrmat","uvwtexture.vrmat"]
        if material not in materials:
            raise ValueError(f"{material} is not a valid material")
        self._material = material

    @classmethod
    def default_render(cls, name, point):
        camera = Camera(name, tuple(float(n) for n in point))
        light = Light(camera)
        output = Camera_Output(light)
        return cls(camera, light, output)

    @classmethod
    def uvw_render(cls, name, point):
        camera = Camera(name, tuple(float(n) for n in point))
        light = Light(camera, conditions = 1, on = False)
        output = Camera_Output(light, itname = "_UVW")
        return cls(camera, light, output, material = "uvwtexture.vrmat")

    @classmethod
    def objectid_render(cls, name, point):
        camera = Camera(name, tuple(float(n) for n in point))
        light = Light(camera, conditions = 1, on = False)
        output = Camera_Output(light, itname = "_ObjectID")
        return cls(camera, light, output, material = "objectid.vrmat")

    def to_row(self):
        return [self.camera.to_str(), self.light.to_str(), self.output.to_str(), self.material]

    @classmethod
    def from_row(cls, row):
        camera = Camera.from_str(row[0])
        light = Light.from_str(row[1], camera)
        output = Camera_Output.from_str(row[2], light)
        return cls(camera, light, output, row[3])

RENDER_TYPES = {
    "default": Render.default_render,
    "uvw": Render.uvw_render,
    "objectid": Render.objectid_render,
}

def main():
    points = [
        (10, 10, 10),
        (-20, 5, 30),
        (0, 40, 15),
    ]

    paths = write_all_renders(points, folder="test_output", prefix="test")

    for path, render_type in zip(paths, RENDER_TYPES):
        print(f"\n=== {render_type} -> {path}")

        renders = read_renders(path)
        originals = build_renders(points, render_type)

        for original, render in zip(originals, renders):
            match = original.to_row() == render.to_row()
            print(f"{render.camera.name} : {render.material} : {render.output.name_str()} : round trip ok = {match}")

        if len(renders) != len(points):
            print(f"WARNING: expected {len(points)} rows, read {len(renders)}")

def build_renders(points, render_type):
    if render_type not in RENDER_TYPES:
        raise ValueError(f"{render_type} is not a render type")
    make = RENDER_TYPES[render_type]
    return [make(f"Camera{i}", point) for i, point in enumerate(points)]

def write_renders(renders, path):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(Render.HEADER)
        for render in renders:
            writer.writerow(render.to_row())

def read_renders(path):
    with open(path, newline="") as f:
        reader = csv.reader(f)
        next(reader)
        return [Render.from_row(row) for row in reader]

def write_all_renders(points, folder=".", prefix="renders", types=None):
    os.makedirs(folder, exist_ok=True)
    paths = []
    for render_type in types or RENDER_TYPES:
        path = os.path.join(folder, f"{prefix}_{render_type}.csv")
        write_renders(build_renders(points, render_type), path)
        paths.append(path)
    return paths

def create_render_set(test_name, directory, points, overwrite = False, types = None):
    """Write the default, UVW and ObjectID CSVs for one test (or only the types given).
    Files go to Pipeline\\render_data\\<directory>\\<test_name>_<type>.csv
    and the list of file paths is returned.
    """
    types = list(types or RENDER_TYPES)
    for render_type in types:
        if render_type not in RENDER_TYPES:
            raise ValueError(f"{render_type} is not a render type")
    if not test_name or type(test_name) != str:
        raise ValueError("Test name must be a non-empty str")
    if any(char in test_name for char in '\\/:*?"<>|'):
        raise ValueError(f"'{test_name}' contains characters that can't be in a file name")
    if not directory or type(directory) != str:
        raise ValueError("Directory must be a non-empty str")
    if not points:
        raise ValueError("No points were given")

    folder = os.path.join(RENDER_DATA_FOLDER, directory)
    planned = [os.path.join(folder, f"{test_name}_{render_type}.csv") for render_type in types]
    existing = [path for path in planned if os.path.exists(path)]
    if existing and not overwrite:
        raise FileExistsError(f"'{test_name}' already exists in {folder} - use a new test name or overwrite = True")

    paths = write_all_renders(points, folder = folder, prefix = test_name, types = types)
    print(f"{test_name}: {len(points)} cameras x {len(paths)} render types -> {folder}")
    return paths

if __name__ == "__main__":
    main()
