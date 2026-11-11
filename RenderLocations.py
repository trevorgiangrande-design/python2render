import math

def main():
    print(point_sweep("full", 100))

def angle_startdir(direction = "south"):
    if direction not in ["north", "east", "south", "west"]:
        raise ValueError(f"{direction} is not a valid direction")
    match direction:
        case "east": return 0
        case "north": return 90
        case "west": return 180
        case "south": return 270

def angle_sweep(sweep = "full"):
    if sweep not in ["front", "left", "right", "back", "full"]:
        raise ValueError(f"{sweep} is not a valid sweep")
    match sweep:
        case "front": return (-90,90)
        case "left": return (-180,0)
        case "right": return (0,180)
        case "back" : return (90,270)
        case "full" : return (0,360)

def angle_tilt(tilt = "above"):
    if tilt not in ["above", "below", "full"]:
        raise ValueError(f"{tilt} is not a valid tilt")
    match tilt:
        case "above": return (0,90)
        case "below": return (-90,0)
        case "full": return (-90,90)
    
def angle_range(center, dir_range):
    low, high = dir_range
    low += center
    high += center
    return low, high

def angles(angle_range, angle_increment, endcull = 0):
    min_angle, max_angle = angle_range
    if angle_increment <= 0:
        raise ValueError("Angle increment must be positive")
    if (max_angle-min_angle) % angle_increment != 0:
        raise ValueError("Angle range is not divisible by angle increment")
    if endcull < 0:
        raise ValueError("End cull must be a positive integer")
    angles = []
    if max_angle > 360:
        min_angle = min_angle - 360
        max_angle = max_angle - 360
    while min_angle <= max_angle:
        angles.append(min_angle)
        min_angle += angle_increment
    if endcull != 0:
        if endcull * 2 >= len(angles):
            raise ValueError("End cull removes every angle")
        angles = angles[endcull:len(angles) - endcull]
    if angles[0] == angles[-1] - 360:
        angles.pop(-1)
    return angles

def transformations(longitudes, latitudes):
    for latitude in latitudes:
        if not -90 <= latitude <= 90:
            raise ValueError(f"{latitude} is not a valid latitude")

    result = []
    for longitude in longitudes:
        for latitude in latitudes:
            if abs(latitude) != 90:
                result.append((longitude, latitude))

    for latitude in latitudes:
        if abs(latitude) == 90:
            result.append((longitudes[0], latitude))
    return result
    
def point_sphere(transformations, dist, startpoint = (0,0,0)):
    points = []
    for t in transformations:
        x = startpoint[0] + dist * math.cos(math.radians(t[1])) * math.cos(math.radians(t[0]))
        y = startpoint[1] + dist * math.cos(math.radians(t[1])) * math.sin(math.radians(t[0]))
        z = startpoint[2] + dist * math.sin(math.radians(t[1]))
        points.append((round(x,3),round(y,3),round(z,3)))
    return points

# Named starting points for a sweep. Any value can be overridden per call,
# e.g. point_sweep("full", 250, lon_step=30, direction="north")
SWEEP_PRESETS = {
    "full":   {"direction": "south", "sweep": "full",  "tilt": "above", "lon_step": 15, "lat_step": 30, "lon_cull": 0, "lat_cull": 0},
    "front":  {"direction": "south", "sweep": "front", "tilt": "full",  "lon_step": 15, "lat_step": 30, "lon_cull": 0, "lat_cull": 1},
    "global": {"direction": "south", "sweep": "full",  "tilt": "full",  "lon_step": 30, "lat_step": 30, "lon_cull": 0, "lat_cull": 0},
}

def sweep_angles(direction = "south", sweep = "full", tilt = "above",
                 lon_step = 15, lat_step = 30, lon_cull = 0, lat_cull = 0):
    longitudes = angles(angle_range(angle_startdir(direction), angle_sweep(sweep)), lon_step, lon_cull)
    latitudes = angles(angle_tilt(tilt), lat_step, lat_cull)
    return transformations(longitudes, latitudes)

def sweep_points(distances, center = (0,0,0), **settings):
    """Points for one sweep at one or more distances (a number or a list of numbers)."""
    if type(distances) in (int, float):
        distances = [distances]
    if not distances:
        raise ValueError("No distances given")
    for distance in distances:
        if type(distance) != float and type(distance) != int:
            raise ValueError("Distance must be either a float or int")
        if distance <= 0:
            raise ValueError("Distance must be greater than 0")
    pairs = sweep_angles(**settings)
    points = []
    for distance in distances:
        points += point_sphere(pairs, distance, center)
    return points

def full_sweep(distance):
    return point_sweep("full", distance)

def front_sweep(distance):
    return point_sweep("front", distance)

def global_sweep(distance):
    return point_sweep("global", distance)

def point_sweep(kind, distance, **overrides):
    if not kind:
        raise ValueError("Kind field is empty")
    if type(kind) != str:
        raise ValueError("Kind is not a str")
    if kind.casefold() not in SWEEP_PRESETS:
        raise ValueError(f"'{kind}' is not a valid sweep type")
    settings = {**SWEEP_PRESETS[kind.casefold()], **overrides}
    return sweep_points(distance, **settings)
if __name__ == "__main__":
    main()
