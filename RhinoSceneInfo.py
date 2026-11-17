#! python 3
"""RhinoSceneInfo.py - measure the open Rhino model and save it as <model>_scene.json.

Run from Rhino 8's ScriptEditor with the model open (and saved). The .json is written next to the
.3dm (cup.3dm -> cup_scene.json in the same folder): units, bounding box and area centroid,
in total and per mesh. It is reference data - nothing in the render pipeline reads it.
"""
import json
import os

import Rhino
import scriptcontext as sc

DECIMALS = 3


def r(value):
    return round(value, DECIMALS)


def point_to_list(point):
    return [r(point.X), r(point.Y), r(point.Z)]


def bbox_info(bbox):
    return {
        "min": point_to_list(bbox.Min),
        "max": point_to_list(bbox.Max),
        "center": point_to_list(bbox.Center),
        "size": [r(bbox.Max.X - bbox.Min.X), r(bbox.Max.Y - bbox.Min.Y), r(bbox.Max.Z - bbox.Min.Z)],
        "radius": r(bbox.Diagonal.Length / 2),
    }


def centroid_info(area, centroid, bbox):
    # radius = distance from the centroid to the farthest bounding box corner,
    # so a sphere this size around the centroid encloses the whole object
    radius = max(centroid.DistanceTo(corner) for corner in bbox.GetCorners())
    return {
        "area": r(area),
        "centroid": point_to_list(centroid),
        "radius": r(radius),
    }


def mesh_objects(doc):
    settings = Rhino.DocObjects.ObjectEnumeratorSettings()
    settings.ObjectTypeFilter = Rhino.DocObjects.ObjectType.Mesh
    settings.NormalObjects = True
    settings.LockedObjects = True
    settings.HiddenObjects = False
    return list(doc.Objects.GetObjectList(settings))


def main():
    doc = sc.doc

    if not doc.Path:
        print("Save the Rhino file first - the .json is named after the .3dm.")
        return

    meshes = mesh_objects(doc)
    if not meshes:
        print("No visible mesh objects found in this file.")
        return

    total = None
    total_area = 0.0
    weighted = [0.0, 0.0, 0.0]
    objects = []
    for obj in meshes:
        bbox = obj.Geometry.GetBoundingBox(True)
        total = bbox if total is None else Rhino.Geometry.BoundingBox.Union(total, bbox)

        # same calculation as Grasshopper's Area component
        props = Rhino.Geometry.AreaMassProperties.Compute(obj.Geometry)
        if props is None:
            print(f"Could not compute the area centroid of {obj.Id} - skipped in the centroid.")
            area_centroid = None
        else:
            area_centroid = centroid_info(props.Area, props.Centroid, bbox)
            total_area += props.Area
            weighted[0] += props.Centroid.X * props.Area
            weighted[1] += props.Centroid.Y * props.Area
            weighted[2] += props.Centroid.Z * props.Area

        objects.append({
            "id": str(obj.Id),
            "name": obj.Attributes.Name or "",
            "layer": doc.Layers[obj.Attributes.LayerIndex].FullPath,
            "bounding_box": bbox_info(bbox),
            "area_centroid": area_centroid,
        })

    # combined centroid of all meshes, each weighted by its surface area
    if total_area > 0:
        combined = Rhino.Geometry.Point3d(weighted[0] / total_area,
                                          weighted[1] / total_area,
                                          weighted[2] / total_area)
        total_centroid = centroid_info(total_area, combined, total)
    else:
        total_centroid = None

    units = doc.ModelUnitSystem
    data = {
        "source_file": os.path.basename(doc.Path),
        "units": units.ToString(),
        "unit_scale_to_meters": Rhino.RhinoMath.UnitScale(units, Rhino.UnitSystem.Meters),
        "up_axis": "Z",
        "mesh_count": len(meshes),
        "bounding_box": bbox_info(total),
        "area_centroid": total_centroid,
        "objects": objects,
    }

    name = os.path.splitext(os.path.basename(doc.Path))[0]
    path = os.path.join(os.path.dirname(doc.Path), name + "_scene.json")      # next to the .3dm
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Wrote {path}")
    print(f"{len(meshes)} mesh(es), units = {data['units']}, bbox radius = {data['bounding_box']['radius']:.3f}")
    if total_centroid:
        c = total_centroid["centroid"]
        print(f"area centroid = ({c[0]:.3f}, {c[1]:.3f}, {c[2]:.3f}), centroid radius = {total_centroid['radius']:.3f}")


if __name__ == "__main__":
    main()
