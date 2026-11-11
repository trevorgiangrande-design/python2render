"""RenderManifest.py - camera manifest for a finished render set.

RhinoRenderRunner calls make_manifest(directory, log_path) once every render list has finished.
It can also be run by itself afterwards:

    python RenderManifest.py "C:\\...\\Pipeline\\render_data\\cup"

Exposure_Value and White_Balance are fixed defaults (EXPOSURE_VALUE / WHITE_BALANCE below) until the
render lists carry their own. The Object ID name (cup.3dm -> Cup) and the distance units come from the
Rhino file: the runner passes the active file's; run by itself, they come from the newest run log in
<directory>\\render_logs (else the folder name and mm).

Each test's images are in <directory>\\<test_name>\\Renders, UVW and ObjectID (the folders the
output-folder script makes). What it does, for each test (cup_test_simple_default.csv / _uvw / _objectid):
    1. strips V-Ray's frame numbers from the image names
           Renders\\Camera0_Img0.0000.jpg  ->  Renders\\Camera0_Img0.jpg
    2. writes <directory>\\<test_name>\\<test_name>_Vray_CameraData.xlsx in the same layout as the team's
       CameraData.xlsx (Render_Metadata, Render_Manifest, UVW_Manifest, ObjectID_Manifest);
       the manifest sheets' Exact column is the file on disk (Camera0_Img0.jpg)

Everything comes from the render set folder (the CSVs, image folders and run logs) and the .vrmat files.

Standard library only, so it also runs inside Rhino 8 (Python 3.9, no openpyxl there).
"""
import csv
import glob
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from xml.sax.saxutils import escape

SCRIPTS_FOLDER = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_FOLDER not in sys.path:
    sys.path.insert(0, SCRIPTS_FOLDER)

from RenderPackage import read_renders  # noqa: E402

MATERIALS_FOLDER = os.path.join(SCRIPTS_FOLDER, "materials")
FOLDERS = {"default": "Renders", "uvw": "UVW", "objectid": "ObjectID"}

# Not in the render lists yet - every render uses these (the team's CameraData.xlsx values).
EXPOSURE_VALUE = 10
WHITE_BALANCE = (255, 255, 255)

UVW_FORMULA = ("The UV is derrived per image - where Red / 255 = U value and Green / 255  = V value - "
               "Texture is globally eliminated to remove any changes caused by scene lighting")

UNIT_ABBREVIATIONS = {"millimeters": "mm", "centimeters": "cm", "meters": "m", "inches": "in", "feet": "ft"}

FRAME_SUFFIX = re.compile(r"^(?P<stem>.+)\.(?P<frame>\d+)(?P<ext>\.[^.]+)$")

# Column layout and widths copied from the team's CameraData.xlsx
METADATA_COLUMNS = [
    ("File_Name", 32.13), ("Scene_Camera", 13.6), ("Camera_Data", 99.27), ("Distance_Class", 18.27),
    ("Distance_to_Target(camera to centroid)", 35.86), ("Lighting_Condition_ID", 20.13),
    ("Light_Postion(X,Y,Z)", 35.13), ("Light_Target(X,Y,Z)", 33.6), ("Corresponding_UVW", 19.73),
    ("ObjectID", 19.0), ("White_Balance", 18.27), ("Exposure_Value", 15.73),
]
MANIFEST_SHEETS = [  # sheet, render type, header prefix, column widths
    ("Render_Manifest", "default", "Render", (25.86, 22.86)),
    ("UVW_Manifest", "uvw", "UVW", (25.0, 21.73)),
    ("ObjectID_Manifest", "objectid", "ObjectID", (24.6, 24.0)),
]


# ---- the render set --------------------------------------------------------------------------

def find_tests(directory):
    """{test_name: {render_type: csv path}} for every *_default/_uvw/_objectid.csv in the folder."""
    tests = {}
    for render_type in FOLDERS:
        for path in glob.glob(os.path.join(directory, f"*_{render_type}.csv")):
            test = os.path.basename(path)[:-len(f"_{render_type}.csv")]
            tests.setdefault(test, {})[render_type] = path
    return dict(sorted(tests.items()))


def expected_names(renders):
    """Image file names a render list should produce, in render order."""
    return [name for render in renders for name in render.output.name_list()]


def strip_frame_numbers(folder, names):
    """Rename V-Ray's Camera0_Img0.0000.jpg to Camera0_Img0.jpg for the images in `names`.

    Only files belonging to this render list are touched. If V-Ray left more than one numbered copy
    of an image (e.g. a stopped run and a full run), the newest one wins. A clean-named file is only
    replaced by a newer numbered one. Nothing is deleted. Returns (renamed, older copies left alone).
    """
    if not os.path.isdir(folder):
        return 0, 0
    wanted = {name.lower(): name for name in names}
    copies = {}
    for file_name in os.listdir(folder):
        match = FRAME_SUFFIX.match(file_name)
        if not match:
            continue
        clean = (match.group("stem") + match.group("ext")).lower()
        if clean in wanted:
            path = os.path.join(folder, file_name)
            copies.setdefault(wanted[clean], []).append((os.path.getmtime(path), path))
    renamed = left = 0
    for clean, found in copies.items():
        found.sort()
        newest_time, newest = found[-1]
        target = os.path.join(folder, clean)
        if os.path.exists(target) and os.path.getmtime(target) >= newest_time:
            left += len(found)
            continue
        os.replace(newest, target)
        renamed += 1
        left += len(found) - 1
    return renamed, left


def actual_files(folder, names):
    """{expected name: file on disk} - Camera0_Img0.jpg -> Camera0_Img0.0000.jpg (any frame padding,
    or no frame number at all). If an image has several copies (e.g. a stopped run and a full run),
    the newest is the one listed. Images with no file are left out."""
    if not os.path.isdir(folder):
        return {}
    wanted = {name.lower(): name for name in names}
    newest = {}
    for file_name in os.listdir(folder):
        match = FRAME_SUFFIX.match(file_name)
        clean = (match.group("stem") + match.group("ext")) if match else file_name
        name = wanted.get(clean.lower())
        if name is None:
            continue
        written = os.path.getmtime(os.path.join(folder, file_name))
        if name not in newest or written > newest[name][0]:
            newest[name] = (written, file_name)
    return {name: file_name for name, (_, file_name) in newest.items()}


def read_run_log(directory, log_path=None):
    """The run log (the given one, else the newest in <directory>\\render_logs), {} if there's none."""
    if not log_path:
        logs = glob.glob(os.path.join(directory, "render_logs", "run_*.json"))
        log_path = max(logs) if logs else None              # run_<date>_<time> - newest sorts last
    try:
        with open(log_path) as f:
            return json.load(f)
    except (OSError, TypeError, ValueError):
        return {}


def unit_label(units):
    """Rhino's unit system name -> 'mm' etc.; millimetres if unknown."""
    units = str(units or "")
    return UNIT_ABBREVIATIONS.get(units.lower(), units or "mm")


def distance_levels(distances, tolerance=0.01):
    """Group distances within 1% of each other (rounding in the CSV makes 250.0994 vs 250.1)."""
    levels = []
    for d in sorted(distances):
        if not levels or d > levels[-1][0] * (1 + tolerance):
            levels.append([d])
        else:
            levels[-1].append(d)
    return levels


def distance_classes(distances):
    """{distance: Close / Medium / Far}, nearest first (more than 3 distances: Medium 1, 2, ...)."""
    levels = distance_levels(distances)
    if len(levels) == 1:
        labels = ["Close"]
    elif len(levels) == 2:
        labels = ["Close", "Far"]
    elif len(levels) == 3:
        labels = ["Close", "Medium", "Far"]
    else:
        labels = ["Close"] + [f"Medium {i}" for i in range(1, len(levels) - 1)] + ["Far"]
    return {d: label for level, label in zip(levels, labels) for d in level}


# ---- materials ---------------------------------------------------------------------------------

def read_vrmat(file_name):
    """{parameter name: value} from a .vrmat (colours as (r, g, b) floats, 0-1 linear)."""
    with open(os.path.join(MATERIALS_FOLDER, file_name), encoding="utf-8") as f:
        text = f.read()
    root = ET.fromstring(text[text.index("<vrmat"):])          # objectid.vrmat starts with a stray '1'
    values = {}
    for parameter in root.iter("parameter"):
        value = parameter.find("value")
        if value is None:
            continue
        rgb = [value.find(c) for c in ("r", "g", "b")]
        if all(c is not None for c in rgb):
            values.setdefault(parameter.get("name"), tuple(float(c.text) for c in rgb))
        elif value.text and value.text.strip():
            try:
                values.setdefault(parameter.get("name"), float(value.text))
            except ValueError:
                pass
    return values


def to_srgb(linear):
    """V-Ray's 0-1 linear colour -> the 0-255 value V-Ray's colour picker shows."""
    c = min(max(linear, 0.0), 1.0)
    c = c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return int(round(c * 255))


def rgb_text(colour, separator=", "):
    return separator.join(str(to_srgb(c)) for c in colour)


def plain_number(value):
    return int(value) if float(value).is_integer() else round(value, 6)


def material_rows(file_name):
    m = read_vrmat(file_name)
    black = (0.0, 0.0, 0.0)
    return [
        ["Material Data", "Value"],
        ["Diffuse", rgb_text(m.get("diffuse", black))],
        ["Reflection", rgb_text(m.get("reflect", black))],
        ["Glossiness", plain_number(m.get("reflect_glossiness", 1.0))],
        ["IOR", plain_number(m.get("fresnel_ior", m.get("refract_ior", 1.6)))],
        ["Opacity", plain_number(m.get("opacity", 1.0))],
        ["Emission", rgb_text(m.get("self_illumination", black))],
    ]


# ---- sheet contents ----------------------------------------------------------------------------

def point_text(point):
    return "{" + ", ".join(f"{n:.6f}" for n in point) + "}"


def white_balance(rgb):
    """(255, 255, 255) -> 255255255, shown as 255,255,255 by the #,##0 format (as in CameraData.xlsx)."""
    return int("".join(f"{c:03d}" for c in rgb))


def length_text(value, unit):
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{text} {unit}"


def camera_index(name):
    digits = re.search(r"\d+$", name)
    return int(digits.group()) if digits else name


def metadata_rows(renders, extra_names, unit, object_name):
    classes = distance_classes([round(r.camera.distance(), 3) for r in renders])
    rows = [[title for title, _ in METADATA_COLUMNS]]
    for render in renders:
        camera, light = render.camera, render.light
        camera_data = (f"From: {point_text(camera.startloc)}, To: {point_text(camera.endloc)}, "
                       f"FoV: {camera.FOV:.2f}\u00b0 Perspective")
        distance = round(camera.distance(), 3)
        uvw = extra_names["uvw"].get(camera.name, "")
        objectid = extra_names["objectid"].get(camera.name, "")
        starts, targets = light.locations()
        for condition, (name, start, target) in enumerate(zip(render.output.name_list(), starts, targets)):
            rows.append([
                os.path.splitext(name)[0], camera_index(camera.name), camera_data, classes[distance],
                length_text(distance, unit), condition, point_text(start), point_text(target),
                uvw, objectid, white_balance(WHITE_BALANCE), EXPOSURE_VALUE,
            ])
    rows.append([])
    rows += material_rows(renders[0].material)
    rows += [[], ["UVW Formula"], [UVW_FORMULA], []]
    objectid_colour = read_vrmat("objectid.vrmat").get("self_illumination", (0.0, 0.0, 0.0))
    rows += [["Object ID", "RGB Value", "Object Identification"],
             [0, rgb_text(objectid_colour, ","), object_name]]
    return rows


def manifest_rows(names, folder, label):
    on_disk = actual_files(folder, names)
    rows = [[f"Filename_{label}_Prefix", f"Filename_{label}_Exact"]]
    missing = 0
    for name in names:
        exact = on_disk.get(name)
        missing += exact is None
        rows.append([os.path.splitext(name)[0], exact or ""])     # no file -> Exact left empty
    return rows, missing


# ---- a minimal .xlsx writer (no openpyxl in Rhino) ---------------------------------------------

def column_letter(index):
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def sheet_xml(rows, widths, number_format_columns=()):
    """One worksheet. Strings are inline, numbers stay numbers, None/'' are left empty."""
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    lines = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            if value is None or value == "":
                continue
            ref = f"{column_letter(c)}{r}"
            if isinstance(value, bool):
                value = str(value)
            if isinstance(value, (int, float)):
                style = ' s="1"' if (c in number_format_columns and r > 1) else ""
                cells.append(f'<c r="{ref}"{style}><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        lines.append(f'<row r="{r}">{"".join(cells)}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<cols>{cols}</cols><sheetData>{"".join(lines)}</sheetData></worksheet>')


def write_xlsx(path, sheets):
    """sheets: list of (name, xml). Calibri 11 throughout; style 1 = #,##0."""
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    ct_sheet = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
    header = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    content_types = (
        header + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="{ct_sheet}"/>'
                  for i in range(1, len(sheets) + 1))
        + '</Types>')
    root_rels = (header + f'<Relationships xmlns="{pkg}">'
                 f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    workbook = (header + f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>'
                + "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
                          for i, (name, _) in enumerate(sheets, start=1))
                + '</sheets></workbook>')
    workbook_rels = (header + f'<Relationships xmlns="{pkg}">'
                     + "".join(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>'
                               for i in range(1, len(sheets) + 1))
                     + f'<Relationship Id="rId{len(sheets) + 1}" Type="{rel}/styles" Target="styles.xml"/>'
                     + '</Relationships>')
    styles = (header + f'<styleSheet xmlns="{main}">'
              '<fonts count="1"><font><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/>'
              '<scheme val="minor"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill>'
              '<fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
              '</styleSheet>')
    temporary = path + ".tmp"
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        z.writestr("xl/styles.xml", styles)
        for i, (_, xml) in enumerate(sheets, start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml)
    try:
        os.replace(temporary, path)
    except PermissionError:
        os.remove(temporary)
        raise PermissionError(f"Can't write {os.path.basename(path)} - close it in Excel and run again")


# ---- entry point -------------------------------------------------------------------------------

def make_test_manifest(directory, test, csvs, object_name, unit):
    """Strip frame numbers and write <test>_Vray_CameraData.xlsx for one test. Returns a summary line."""
    if "default" not in csvs:
        return f"{test}: no _default.csv - skipped"
    renders = {render_type: read_renders(path) for render_type, path in csvs.items()}
    names = {render_type: expected_names(r) for render_type, r in renders.items()}
    test_folder = os.path.join(directory, test)          # <directory>\<test_name>\Renders, UVW, ObjectID + the .xlsx

    notes = []
    for render_type, folder_name in FOLDERS.items():
        if render_type in names:
            renamed, left = strip_frame_numbers(os.path.join(test_folder, folder_name), names[render_type])
            if left:
                notes.append(f"{left} older numbered copies left in {folder_name}")

    extra_names = {render_type: {r.camera.name: os.path.splitext(r.output.name_list()[0])[0]
                                 for r in renders.get(render_type, [])}
                   for render_type in ("uvw", "objectid")}
    metadata = metadata_rows(renders["default"], extra_names, unit, object_name)
    sheets = [("Render_Metadata", sheet_xml(metadata, [w for _, w in METADATA_COLUMNS], number_format_columns=(10,)))]
    missing = {}
    for sheet, render_type, label, widths in MANIFEST_SHEETS:
        rows, missing[sheet] = manifest_rows(names.get(render_type, []),
                                             os.path.join(test_folder, FOLDERS[render_type]), label)
        sheets.append((sheet, sheet_xml(rows, widths)))
    gaps = [f"{n} images missing for {sheet}" for sheet, n in missing.items() if n]

    os.makedirs(test_folder, exist_ok=True)
    path = os.path.join(test_folder, f"{test}_Vray_CameraData.xlsx")
    write_xlsx(path, sheets)
    summary = f"{os.path.basename(path)} ({len(names['default'])} renders)"
    return summary + (" - " + "; ".join(gaps + notes) if gaps or notes else "")


def make_manifest(directory, log_path=None, object_name=None, units=None):
    """Write <test>_Vray_CameraData.xlsx for every test in `directory`. Returns a one-line summary.

    object_name  the Rhino file's name, e.g. cup   } RhinoRenderRunner passes the active file's;
    units        Rhino's unit system, e.g. Millimeters } otherwise read from the run log
    """
    log = read_run_log(directory, log_path)
    if not (object_name and str(object_name).strip()):
        rhino_file = log.get("rhino_file")
        object_name = os.path.splitext(rhino_file)[0] if rhino_file else os.path.basename(os.path.normpath(directory))
    object_name = str(object_name).strip()
    object_name = object_name[:1].upper() + object_name[1:]          # cup -> Cup (rest left as named)
    unit = unit_label(units or log.get("units"))
    tests = find_tests(directory)
    if not tests:
        return f"no render lists found in {directory}"
    results = [make_test_manifest(directory, test, csvs, object_name, unit) for test, csvs in tests.items()]
    summary = " | ".join(results)
    print(f"RenderManifest: {summary}")
    return summary


if __name__ == "__main__":
    make_manifest(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
