import math

class Camera():

    def __init__(self, name, startloc, FOV = 50.0, endloc = (0.000,0.000,0.000)):
        self.name = name
        self.startloc = startloc
        self.FOV = FOV
        self.endloc = endloc

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, name):
        if not name:
            raise ValueError("Name field is empty")
        self._name = name

    @property
    def startloc(self):
        return self._startloc

    @startloc.setter
    def startloc(self, startloc):
        if type(startloc) != tuple:
            raise ValueError("Start location is not a tuple")
        x,y,z = startloc
        if type(x) != float or type(y) != float or type(z) != float:
            raise ValueError("Start location tuple contains a non-float")
        self._startloc = startloc

    @property
    def FOV(self):
        return self._FOV

    @FOV.setter
    def FOV(self, FOV):
        if type(FOV) != float:
            raise ValueError("FOV is not a float")
        self._FOV = FOV

    @property
    def endloc(self):
        return self._endloc

    @endloc.setter
    def endloc(self, endloc):
        if type(endloc) != tuple:
            raise ValueError("End location is not a tuple")
        x,y,z = endloc
        if type(x) != float or type(y) != float or type(z) != float:
            raise ValueError("End location tuple contains a non-float")
        self._endloc = endloc

    def distance(self):
        x1, y1, z1 = self.startloc
        x2, y2, z2 = self.endloc
        return math.sqrt( (x1-x2) ** 2 + (y1-y2) ** 2 + (z1-z2) **2 )

    def direction(self):
        x1, y1, z1 = self.startloc
        x2, y2, z2 = self.endloc
        return (x1-x2),(y1-y2),(z1-z2)

    def longitude(self):
        dx = self.startloc[0] - self.endloc[0]
        dy = self.startloc[1] - self.endloc[1]
        return math.degrees(math.atan2(dy, dx))

    def latitude(self):
        dx = self.startloc[0] - self.endloc[0]
        dy = self.startloc[1] - self.endloc[1]
        dz = self.startloc[2] - self.endloc[2]
        return math.degrees(math.atan2(dz, math.hypot(dx, dy)))

    def __str__(self):
        start = ", ".join(f"{n:.3f}" for n in self.startloc)
        end = ", ".join(f"{n:.3f}" for n in self.endloc)
        return f"{self.name} : from {start} to {end} : FOV = {self.FOV:.3f}° : Distance = {self.distance():.3f}"

    def to_str(self):
        start = ",".join(f"{n:.3f}" for n in self.startloc)
        end = ",".join(f"{n:.3f}" for n in self.endloc)
        return f"{self.name};{start};{self.FOV:.2f};{end}"

    @classmethod
    def from_str(cls, text):
        name, start, fov, end = text.split(";")
        startloc = tuple(float(n) for n in start.split(","))
        endloc = tuple(float(n) for n in end.split(","))
        return cls(name, startloc, float(fov), endloc)

class Light():

    def __init__(self, refcamera, conditions = 3, longitudinal_offsets=45.00, azimuth = 45.00, distance = 10000, on = True, qualities = None):
        self.refcamera = refcamera
        self.conditions = conditions
        self.longitudinal_offsets = longitudinal_offsets
        self.azimuth = azimuth
        self.distance = distance
        self.on = on
        self.qualities = qualities if qualities else Light_Qualities()

    @property
    def refcamera(self):
        return self._refcamera

    @refcamera.setter
    def refcamera(self, refcamera):
        if not isinstance(refcamera, Camera):
            raise ValueError("Did not pass a reference camera object")
        self._refcamera = refcamera

    @property
    def conditions(self):
        if not self.on:
            return 1
        return self._conditions

    @conditions.setter
    def conditions(self, conditions):
        if type(conditions) != int:
            raise ValueError("Did not pass int for number of light conditions")
        if conditions < 1:
            raise ValueError("Must have at least 1 light condition")
        self._conditions = conditions

    @property
    def longitudinal_offsets(self):
        return self._longitudinal_offsets

    @longitudinal_offsets.setter
    def longitudinal_offsets(self, longitudinal_offsets):
        if type(longitudinal_offsets) != float:
            raise ValueError("Longitudinal offets must be a float")
        self._longitudinal_offsets = longitudinal_offsets

    @property
    def azimuth(self):
        return self._azimuth

    @azimuth.setter
    def azimuth(self, azimuth):
        if type(azimuth) != float:
            raise ValueError("Azimuth is not a float")
        self._azimuth = azimuth

    @property
    def distance(self):
        return self._distance

    @distance.setter
    def distance(self, distance):
        if type(distance) != int:
            raise ValueError("Distance must be an int")
        if distance < 0:
            raise ValueError("Distance must be non-negative int")
        self._distance = distance

    @property
    def on(self):
        return self._on 

    @on.setter
    def on(self, on):
        if type(on) != bool:
            raise ValueError("On is not a bool")
        self._on = on

    @property
    def qualities(self):
        return self._qualities

    @qualities.setter
    def qualities(self, qualities):
        if not isinstance(qualities, Light_Qualities):
            raise ValueError("Did not pass a Light_Qualities object")
        self._qualities = qualities

    def longitudinal_list(self):
        offset_list = []
        longitudinal_list = []
        start_longitude = self.refcamera.longitude()
        if self.conditions % 2 != 0:
            length = self.conditions - 1
        else:
            length = self.conditions
        angle = 0.00
        for i in range(int(length/2)):
            angle += self.longitudinal_offsets
            offset_list.append(angle)
        for i in range(int(length/2)):
            offset_list.append(-1 * offset_list[i])
        if self.conditions % 2 != 0:
                offset_list.append(0.00) 
        for j in range(len(offset_list)):
            longitudinal_list.append(math.radians(start_longitude + offset_list[j]))
        return sorted(longitudinal_list)

    def locations(self):
        startlocs = []
        endlocs = []
        lons = self.longitudinal_list()
        lat = math.radians(self.azimuth)
        for i in range(len(lons)):
            x = self.refcamera.endloc[0] + self.distance * math.cos(lat) * math.cos(lons[i])
            y = self.refcamera.endloc[1] + self.distance * math.cos(lat) * math.sin(lons[i])
            z = self.refcamera.endloc[2] + self.distance * math.sin(lat)
            startlocs.append((x,y,z))
            endlocs.append((self.refcamera.endloc[0],self.refcamera.endloc[1],self.refcamera.endloc[2]))
        return startlocs, endlocs

    @staticmethod
    def fmt_points(point):
        return "(" + ", ".join(f"{n:.3f}" for n in point) + ")"
    
    def __str__(self):
        light_conditions = []
        startlocs, endlocs = self.locations()
        for i, (start, end) in enumerate(zip(startlocs, endlocs)):
            light_conditions.append(
                f"{self.refcamera.name} light_condition{i} : from {self.fmt_points(start)} to {self.fmt_points(end)}"
            )
        text = " | ".join(light_conditions)
        if self.on:
            text += f" : {self.qualities}"
        return text

    def to_str(self):
        light = f"{self.refcamera.name};{self._conditions};{self.longitudinal_offsets};{self.azimuth};{self.distance};{self.on}"
        return f"{light}|{self.qualities.to_str()}"

    @classmethod
    def from_str(cls, text, refcamera):
        light_text, qualities_text = text.split("|")
        camera_name, conditions, offset, elevation, distance, on = light_text.split(";")
        if camera_name != refcamera.name:
            raise ValueError(f"Light belongs to {camera_name}, not {refcamera.name}")
        qualities = Light_Qualities.from_str(qualities_text)
        return cls(refcamera, int(conditions), float(offset), float(elevation),
                   int(distance), on == "True", qualities)

class Light_Qualities():

    def __init__(self, rgb = (255,255,255), intensity = 0.500, shadowsoftness = 0.080):
        self.rgb = rgb
        self.intensity = intensity
        self.shadowsoftness = shadowsoftness

    @property
    def rgb(self):
        return self._rgb

    @rgb.setter
    def rgb(self, rgb):
        if type(rgb) != tuple:
            raise ValueError("RGB is not a tuple")
        r, g, b = rgb
        if type(r) != int or type(g) != int or type(b) != int:
            raise ValueError("Value in RGB tuple is not an int")
        if not 0 <= r <= 255 or not 0 <= g <= 255 or not 0 <= b <=255:
            raise ValueError("RGB must be between 0-255 inclusive")
        self._rgb = rgb

    @property
    def intensity(self):
        return self._intensity

    @intensity.setter
    def intensity(self, intensity):
        if type(intensity) != float:
            raise ValueError("Intensity is not a float")
        if not 0.000 <= intensity <= 1.000:
            raise ValueError("Intensity must be between 0.000 and 1.000 inclusive")
        self._intensity = intensity

    @property
    def shadowsoftness(self):
        return self._shadowsoftness

    @shadowsoftness.setter
    def shadowsoftness(self, shadowsoftness):
        if type(shadowsoftness) != float:
            raise ValueError("Shadow softness is not a float")
        if not 0.000 <= shadowsoftness <= 1.000:
            raise ValueError("Shadow softness must be between 0.000 and 1.000 inclusive")
        self._shadowsoftness = shadowsoftness

    def __str__(self):
        return f"RGB = {self.rgb} : Light Intensity = {self.intensity:.3f} : Shadow Softness = {self.shadowsoftness:.3f}"

    def to_str(self):
        values = ",".join(f"{n}" for n in self.rgb)
        return f"{values};{self.intensity:.3f};{self.shadowsoftness:.3f}"

    @classmethod
    def from_str(cls, text):
        rgb, intensity, shadowsoftness = text.split(";")
        values = tuple(int(n) for n in rgb.split(","))
        return cls(values, float(intensity), float(shadowsoftness))

class Camera_Output():

    def __init__(self, reflighting, dimensions = (1024,1024), itname = "_Img", extension = ".jpg"):
        self.reflighting = reflighting
        self.dimensions = dimensions
        self.itname = itname
        self.extension = extension

    @property
    def reflighting(self):
        return self._reflighting

    @reflighting.setter
    def reflighting(self, reflighting):
        if not isinstance(reflighting, Light):
            raise ValueError("Did not pass a reference lighting condition")
        self._reflighting = reflighting

    @property
    def dimensions(self):
        return self._dimensions

    @dimensions.setter
    def dimensions(self, dimensions):
        if type(dimensions) != tuple:
            raise ValueError("Image dimensions is not a tuple")
        w, h = dimensions
        if type(w) != int or type(h) != int:
            raise ValueError("A dimension passed a non int")
        if w < 0 or h < 0:
            raise ValueError("Passed a negative dimension")
        self._dimensions = dimensions

    @property
    def itname(self):
        return self._itname

    @itname.setter
    def itname(self, itname):
        if type(itname) != str:
            raise ValueError("Itteration name is not a str")
        self._itname = itname

    @property
    def extension(self):
        return self._extension

    @extension.setter
    def extension(self, extension):
        valid = [".png",".jpg",".jpeg"]
        if type(extension) != str:
            raise ValueError("Extension must be a str")
        if not extension in valid:
            raise ValueError(f"{extension} is not a valid extension type")
        self._extension = extension

    def camera_name(self):
        camera = self.reflighting.refcamera
        return camera.name

    def name_list(self):
        names = []
        if self.reflighting.on:
            prefix = f"{self.camera_name()+self.itname}"
            for i in range(self.reflighting.conditions):
                names.append(f"{prefix+str(i)+self.extension}")
            return names
        else:
            names.append(f"{self.camera_name()+self.itname+self.extension}")
            return names

    def name_str(self):
        names = self.name_list()
        if len(names) > 1:
            return f"{' | '.join(names)}"
        else:
            return f"{names[0]}"
            
    def __str__(self):
        return f"Referance camera = {self.camera_name()} : Camera IDs - {len(self.name_list())} [ {self.name_str()} ] : Output size = {self.dimensions[0]}px x {self.dimensions[1]}px : Extension type = {self.extension}"

    def to_str(self):
        dims = ",".join(str(n) for n in self.dimensions)
        return f"{self.camera_name()};{dims};{self.itname};{self.extension}"

    @classmethod
    def from_str(cls, text, reflighting):
        camera_name, dims, itname, extension = text.split(";")
        if camera_name != reflighting.refcamera.name:
            raise ValueError(f"Output belongs to {camera_name}, not {reflighting.refcamera.name}")
        dimensions = tuple(int(n) for n in dims.split(","))
        return cls(reflighting, dimensions, itname, extension)

def main():
    camera20 = Camera("Camera20", (10.0, 10.0 ,10.0))
    light20 = Light(camera20)
    print(camera20)
    print(light20)
    print(Camera_Output(light20))
    
if __name__ == "__main__":
    main()

