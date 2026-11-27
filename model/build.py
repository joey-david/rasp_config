"""Generate the named-part GLB from scan-fitted dimensions in millimetres.

Run with uv run model/build.py. The glTF uses metres, +Y up and +Z forward.
Scale assumes 65 mm tires. Hidden connectors and board details are illustrative.
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["trimesh>=4.6,<5", "numpy", "shapely>=2", "mapbox-earcut", "scipy", "networkx"]
# ///
from collections import defaultdict
from pathlib import Path
import math

import numpy as np
import trimesh as tm
from shapely import affinity
from shapely.geometry import Point, Polygon, box
from trimesh.visual.material import PBRMaterial

OUTPUT = Path(__file__).resolve().parents[1] / "web/static/schematic/robot-assembly.glb"
colors = {
    "rubber": "#20252a",
    "tread": "#2a3034",
    "case": "#252a30",
    "seam": "#171c21",
    "yellow": "#ffd134",
    "gold": "#dfa92b",
    "brass": "#c39549",
    "metal": "#a3adb4",
    "chrome": "#c4cbd0",
    "white": "#e4e5db",
    "blue": "#338ec1",
    "brown": "#a77f59",
    "clear": "#cee7ed",
    "green": "#24765c",
    "red": "#ae2939",
    "lens": "#223b48",
    "ink": "#343840",
    "aqua": "#41b8a8",
    "copper": "#bb9056",
    "led": "#73cdff",
}


def material(name):
    srgb = np.array(list(bytes.fromhex(colors[name][1:]))) / 255
    rgb = np.rint(
        255 * np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    ).astype(int)
    return PBRMaterial(
        name=name,
        baseColorFactor=[*rgb, 56 if name == "clear" else 255],
        metallicFactor=0.68 if name in ("brass", "metal", "chrome", "copper") else 0.05,
        roughnessFactor=0.25 if name in ("clear", "lens", "chrome") else 0.68,
        alphaMode="BLEND" if name == "clear" else "OPAQUE",
        doubleSided=True,
    )


parts = defaultdict(lambda: defaultdict(list))


def put(part, mat, mesh, pos=(0, 0, 0)):
    mesh.apply_translation(pos)
    parts[part][mat].append(mesh)
    return mesh


def block(part, mat, pos, size):
    return put(part, mat, tm.creation.box(size), pos)


def bar(part, mat, a, b, radius, sides=20):
    return put(
        part, mat, tm.creation.cylinder(radius=radius, segment=[a, b], sections=sides)
    )


def poly_mesh(profile, thickness):
    m = tm.creation.extrude_polygon(profile, thickness, engine="earcut")
    m.apply_transform(tm.transformations.rotation_matrix(-math.pi / 2, [1, 0, 0]))
    return m


def plate(part, mat, profile, y, thickness):
    return put(part, mat, poly_mesh(profile, thickness), (0, y, 0))


def rounded(width, length, r):
    return box(-width / 2 + r, -length / 2 + r, width / 2 - r, length / 2 - r).buffer(
        r, quad_segs=12
    )


def rounded_case(part, mat, pos, width, length, height, radius):
    # Loft the cap and sidewall around a common set of rounded-rectangle vertices.
    levels = [
        (0, 6.2),
        (0.7, 3.6),
        (2, 1.7),
        (4, 0.5),
        (6, 0),
        (height - 6, 0),
        (height - 4, 0.5),
        (height - 2, 1.7),
        (height - 0.7, 3.6),
        (height, 6.2),
    ]
    verts = []
    faces = []
    for y, inset in levels:
        profile = rounded(width - 2 * inset, length - 2 * inset, radius - inset)
        ring = list(profile.exterior.coords)[:-1]
        verts.extend((x, y, -z) for x, z in ring)
    n = len(ring)
    for j in range(len(levels) - 1):
        for i in range(n):
            a = j * n + i
            b = j * n + (i + 1) % n
            faces.extend([(a, b, b + n), (a, b + n, a + n)])
    for i in range(1, n - 1):
        k = (len(levels) - 1) * n
        faces.extend([(0, i + 1, i), (k, k + i, k + i + 1)])
    mesh = tm.Trimesh(verts, faces)
    mesh.fix_normals()
    return put(part, mat, mesh, pos)


def wire(part, mat, points, radius):
    # Round the bends with a Catmull-Rom curve through the cable waypoints.
    pts = np.array([points[0], *points, points[-1]], float)
    curve = []
    for a, b, c, d in zip(pts, pts[1:], pts[2:], pts[3:]):
        for t in np.arange(8) / 8:
            curve.append(
                0.5
                * (
                    2 * b
                    + (-a + c) * t
                    + (2 * a - 5 * b + 4 * c - d) * t * t
                    + (-a + 3 * b - 3 * c + d) * t**3
                )
            )
    curve.append(pts[-1])
    curve = np.array(curve)
    tangent = np.gradient(curve, axis=0)
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    normal = (
        np.array([0.0, 1.0, 0.0])
        if abs(tangent[0, 1]) < 0.9
        else np.array([1.0, 0.0, 0.0])
    )
    rings = []
    faces = []
    n = 10
    for i, g in enumerate(tangent):
        normal -= g * (normal @ g)
        normal /= np.linalg.norm(normal)
        side = np.cross(g, normal)
        for j in range(n):
            ang = 2 * math.pi * j / n
            rings.append(
                curve[i] + radius * (normal * math.cos(ang) + side * math.sin(ang))
            )
            if i:
                a = (i - 1) * n + j
                b = (i - 1) * n + (j + 1) % n
                faces.extend([(a, b, b + n), (a, b + n, a + n)])
    mesh = tm.Trimesh(rings, faces)
    mesh.fix_normals()
    put(part, mat, mesh)


def wheel_solid(part, mat, profile, x, y, z):
    m = tm.creation.revolve(profile, sections=96)
    m.apply_transform(tm.transformations.rotation_matrix(math.pi / 2, [0, 1, 0]))
    return put(part, mat, m, (x, y, z))


def disk(r):
    return Point(0, 0).buffer(r, quad_segs=24)


def axle_plate(part, mat, shape, x, y, z, thickness):
    m = tm.creation.extrude_polygon(shape, thickness, engine="earcut")
    m.apply_transform(tm.transformations.rotation_matrix(math.pi / 2, [0, 1, 0]))
    put(part, mat, m, (x, y, z))


def decks():
    for upper in (False, True):
        name = "Upper acrylic deck" if upper else "Lower chassis plate"
        outline = affinity.scale(disk(1), 63 if upper else 57, 67)
        if not upper:
            for s in (-1, 1):
                outline = outline.difference(
                    box(49, -34, 76, 34) if s == 1 else box(-76, -34, -49, 34)
                )
        for x in (-32, 32):
            for z in (-33, 33):
                outline = outline.difference(Point(x, z).buffer(1.65))
        for z in (-49, -41, 42, 50):
            for x in (-17, 0, 17):
                outline = outline.difference(
                    affinity.translate(rounded(12, 3, 1), x, z)
                )
        for x, z in [
            (-39, -10),
            (39, -10),
            (-18, 25),
            (18, 25),
            (0, 57),
            (0, -57),
            (-28, 12),
            (28, 12),
        ]:
            outline = outline.difference(Point(x, z).buffer(2))
        plate(name, "clear" if upper else "brown", outline, 72 if upper else 41, 2.8)
    for x in (-32, 32):
        for z in (-33, 33):
            bar("Deck standoffs", "brass", (x, 43.8, z), (x, 72, z), 2.9, 6)
            bar("Deck standoffs", "chrome", (x, 74.8, z), (x, 76, z), 3, 16)


def drive():
    for s, side in [(-1, "Right"), (1, "Left")]:
        n = side + " drive wheel"
        x = s * 63
        y = 32.5
        wheel_solid(
            n,
            "rubber",
            [
                (24, -12),
                (28, -12),
                (31, -9),
                (32, -5),
                (32, 5),
                (31, 9),
                (28, 12),
                (24, 12),
                (24, -12),
            ],
            x,
            y,
            0,
        )
        wheel_solid(
            n,
            "yellow",
            [(20, -11), (25, -11), (26, -9), (26, 9), (25, 11), (20, 11), (20, -11)],
            x,
            y,
            0,
        )
        hub = disk(7)
        for j in range(5):
            hub = hub.union(
                affinity.rotate(
                    Polygon([(-3, 3), (3, 3), (9, 22), (2, 23)]), j * 72, origin=(0, 0)
                )
            )
        axle_plate(n, "yellow", hub, x - 5, y, 0, 10)
        bar(n, "gold", (x - 10, y, 0), (x + 10, y, 0), 4.7)
        for j in range(32):
            for half in (-1, 1):
                a = j * 2 * math.pi / 32
                tread = tm.creation.box([10, 1.65, 3.5])
                tread.apply_transform(
                    tm.transformations.rotation_matrix(half * 0.40, [0, 1, 0])
                )
                tread.apply_translation([half * 5, 31.65, 0])
                tread.apply_transform(tm.transformations.rotation_matrix(a, [1, 0, 0]))
                put(n, "tread", tread, (x, y, 0))
        n = side + " TT gearmotor"
        mx = s * 33
        block(n, "yellow", (mx, 31, 1), (18, 20, 34))
        bar(n, "yellow", (mx - 9, 32.5, 13), (mx + 9, 32.5, 13), 9)
        bar(n, "metal", (mx, 32, -14), (mx, 32, -33), 8)
        block(n, "ink", (mx, 32, -35), (13, 13, 4))
        bar(n, "white", (s * 20, 32.5, 0), (s * 56, 32.5, 0), 3)
        block(n, "clear", (mx, 41, 2), (22, 2.5, 35))
        disc = disk(10.6)
        for j in range(20):
            disc = disc.difference(
                affinity.rotate(box(-0.62, 6.6, 0.62, 9.8), 18 * j, origin=(0, 0))
            )
        axle_plate(side + " encoder disc", "ink", disc, s * 20 - 0.7, 32.5, 0, 1.4)
        for dz, mat in [(0, "red"), (3, "ink")]:
            wire(
                "Motor leads",
                mat,
                [
                    (mx, 32, -36),
                    (mx + s * 5, 40, -40),
                    (mx, 46, -46),
                    (15 + dz, 52, -55),
                ],
                0.7,
            )
    for z, side in [(35, "Front"), (-42, "Rear")]:
        n = side + " swivel caster"
        x = 4
        block(n, "metal", (x, 38, z), (18, 2.5, 21))
        bar(n, "brass", (x, 39, z), (x, 41, z), 3, 6)
        bar(n, "chrome", (x, 29, z), (x, 37, z), 8)
        for dx in (-7, 7):
            bar(n, "metal", (x + dx, 30, z), (x + dx, 10, z + 4), 2.7)
        for dx in (-7, 7):
            for dz in (-7, 7):
                bar(n, "chrome", (x + dx, 36.5, z + dz), (x + dx, 38, z + dz), 1.9, 8)
            # Folded fork cheeks enclose the wheel axle.
            cheek = Polygon([(-1, 9), (5, 8), (8, 13), (4, 29), (-5, 31), (-5, 27)])
            axle_plate(n, "chrome", cheek, x + dx - 1, 0, z + 2, 2)
        bar(n, "white", (x - 5.8, 10, z + 4), (x + 5.8, 10, z + 4), 10, 36)
        bar(n, "metal", (x - 8, 10, z + 4), (x + 8, 10, z + 4), 2)


# Board-local +X points out of the USB sockets. In the chassis it faces rearward (-Z).
PI_MOUNT = tm.transformations.rotation_matrix(math.pi / 2, [0, 1, 0])
PI_MOUNT[2, 3] = -12


def pi_point(x, y, z):
    return (PI_MOUNT @ [x, y, z, 1])[:3]


def electronics():
    rounded_case("Anker battery", "case", (3, 76, -3), 101, 69, 27, 8)
    for j in range(4):
        bar("Anker battery", "led", (-24 + j * 3, 83, 31), (-24 + j * 3, 83, 32), 0.78)
    for j, z in enumerate([-14, 10]):
        n = ["Pi power cable", "Motor power cable"][j]
        block(n, "seam", (-50, 87, z), (10, 6.5, 13))
        end = pi_point(-31, 53, -28) if j == 0 else (1, 44, 68)
        points = (
            [
                (-54, 87, z),
                (-63, 84, z),
                (-66, 66, z - 7),
                (-55, 53, -12),
                (-51, 52, 18),
                (-40, 53, 19),
                end,
            ]
            if j == 0
            else [
                (-54, 87, z),
                (-61, 84, 12),
                (-59, 62, 21),
                (-48, 47, 42),
                (-17, 41, 65),
                end,
            ]
        )
        wire(n, "seam", points, 2.0)
    block("VM power adapter", "ink", (4, 43, 71), (13, 6, 15))
    block("VM power adapter", "metal", (4, 43, 64), (9, 3.8, 4))
    n = "Raspberry Pi"
    plate(n, "green", affinity.translate(rounded(82, 54, 3), 0, -3), 49, 1.7)
    block(n, "metal", (30, 57, -16), (20, 13, 16))
    block(n, "metal", (31, 57, 4), (18, 13, 16))
    block(n, "metal", (-31, 53, -25), (9, 4.5, 6))
    block(n, "ink", (0, 52, 0), (14, 2, 14))
    block(n, "ink", (-8, 53, -24), (52, 4.6, 5.5))
    for j in range(20):
        for z in [-25, -22.5]:
            bar(n, "copper", (-32 + 2.54 * j, 55, z), (-32 + 2.54 * j, 59, z), 0.52, 4)
    block(n, "white", (6, 52, 18), (18, 3, 4))
    block("USB boot stick", "metal", (43, 56, -16), (8, 4.4, 12))
    block("USB boot stick", "ink", (54, 56, -16), (17, 6, 14))
    for group in (n, "USB boot stick"):
        for batch in parts[group].values():
            for mesh in batch:
                mesh.apply_transform(PI_MOUNT)
    # Two retaining strips seen along the lower plate in the inverted capture.
    for sign in (-1, 1):
        a = np.array([sign * 40, 40, -34])
        b = np.array([sign * 14, 40, -57])
        m = tm.creation.box([4, 1.4, np.linalg.norm(b - a)])
        m.apply_transform(
            tm.transformations.rotation_matrix(
                math.atan2((b - a)[0], (b - a)[2]), [0, 1, 0]
            )
        )
        put("Chassis retainers", "aqua", m, (a + b) / 2)
    n = "OV5647 camera"
    block(n, "ink", (5, 104, 25), (24, 22, 1.8))
    for x in (-5, 15):
        for y in (96, 112):
            bar(n, "copper", (x, y, 25.8), (x, y, 26.4), 1.3)
    block(n, "ink", (5, 107, 28), (15, 15, 5))
    for z, r, l, mat in [(30, 8, 4, "case"), (34, 7, 3, "ink"), (37, 5.5, 0.8, "lens")]:
        bar(n, mat, (5, 107, z), (5, 107, z + l), r, 36)
    block(n, "white", (5, 95, 27), (17, 4, 4))
    tilt = tm.transformations.rotation_matrix(-0.26, [1, 0, 0], point=[5, 104, 25])
    for batch in parts[n].values():
        for mesh in batch:
            mesh.apply_transform(tilt)
            mesh.apply_translation([0, -1, 4])
    # Flat flex loops in front of the battery and returns to the Pi connector.
    curve = [
        (94, 32),
        (89, 34),
        (82, 35),
        (74, 38),
        (66, 45),
        (60, 49),
        (55, 48),
        (51, 41),
        (52, 30),
        (54, 18),
    ]
    verts = []
    faces = []
    ribbon_path = [(5, y, z, 0) for y, z in curve[:-1]]
    # Twist the flex through 90 degrees to meet the lengthwise CSI socket.
    for x, y, z, angle in [
        (10, 56, 17, 24),
        (16, 57, 2, 55),
        (18, 56, -12, 80),
        (*pi_point(6, 53.5, 18), 90),
    ]:
        ribbon_path.append((x, y, z, angle))
    for j, (x, y, z, angle) in enumerate(ribbon_path):
        span = (
            np.array([math.cos(math.radians(angle)), 0, -math.sin(math.radians(angle))])
            * 8
        )
        verts.extend([np.array([x, y, z]) - span, np.array([x, y, z]) + span])
        if j:
            faces.extend([(2 * j - 2, 2 * j - 1, 2 * j), (2 * j, 2 * j - 1, 2 * j + 1)])
    put("CSI ribbon", "white", tm.Trimesh(verts, faces))
    block("CSI ribbon", "blue", (5, 92, 33), (16, 4, 0.8))
    n = "TB6612FNG driver"
    block(n, "red", (6, 52, -57), (24, 20, 1.6))
    block(n, "ink", (6, 52, -58.5), (7, 7, 1.8))
    for j in range(8):
        for y in (44, 60):
            bar(n, "chrome", (-3 + j * 2.54, y, -59), (-3 + j * 2.54, y, -55), 0.65, 6)
    for j, pin in enumerate([32, 36, 31, 33, 38, 40, 37, 1, 39]):
        pad = pi_point(-32 + 2.54 * ((pin - 1) // 2), 59, -25 if pin % 2 else -22.5)
        wire(
            "GPIO harness",
            ["ink", "red", "aqua", "white"][j % 4],
            [
                pad,
                (-26 + j * 0.6, 64, pad[2] - 5),
                (-20 + j * 1.1, 65, -38),
                (-11 + j * 2, 58, -47),
                (-3 + j * 2, 59, -56),
            ],
            0.6,
        )
    for j, mat in enumerate(["ink", "red"]):
        wire(
            "Motor supply leads",
            mat,
            [
                (4 + j * 2, 43, 65),
                (23 + j * 2, 46, 42),
                (32 + j * 2, 46, -25),
                (19 + j, 48, -49),
                (12 + j * 2, 48, -57),
            ],
            0.7,
        )


def export():
    scene = tm.Scene(base_frame="Assembly")
    scene.metadata.update(
        {
            "reference": "Mischief Bot dual-pass Gaussian splat",
            "scale": "Nominal 65 mm tire diameter; physical scale unverified",
            "mounting": "Pi lengthwise, USB boot stick exits rear, camera at +Z",
            "estimated": "Board variants, hidden connectors, mounting holes, and cable routes",
        }
    )
    for group, batches in parts.items():
        scene.graph.update(frame_to=group, frame_from=scene.graph.base_frame)
        for mat, meshes in batches.items():
            mesh = tm.util.concatenate(meshes)
            mesh.apply_scale(0.001)
            mesh.visual = tm.visual.TextureVisuals(material=material(mat))
            name = f"{group} — {mat}"
            scene.add_geometry(
                mesh, geom_name=name, node_name=name, parent_node_name=group
            )
    OUTPUT.write_bytes(scene.export(file_type="glb"))


if __name__ == "__main__":
    decks()
    drive()
    electronics()
    export()
