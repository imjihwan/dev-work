"""Build a Niimbot M2 insert that fits the SnapLock V3 (210x180 inner, height param 58) cavity.
Coordinates = SnapLock STL coordinates (cavity floor at z=-56)."""
import numpy as np, trimesh, manifold3d as mf
from shapely.geometry import Polygon, box
from shapely import affinity
from shapely.geometry.polygon import orient

H = 48.0            # insert height
CLR = 0.4           # side clearance to cavity wall
FLOOR = -56.0
NOTCH_D = 24.0      # finger notch depth from top

# ---------- original pockets (from Niimbot insert, origin at its corner) ----------
I = trimesh.load("/home/claude/m3f/insert_orig_origin.stl")
s = I.section(plane_origin=[0, 0, 20], plane_normal=[0, 0, 1])
p2, _ = s.to_2D(to_2D=np.eye(4))
orig = p2.polygons_full[0]
def to_new(poly):
    # orig center (90,105) -> new (0,92); rotate +90 deg
    p = affinity.translate(poly, -90, -105)
    p = affinity.rotate(p, 90, origin=(0, 0))
    return affinity.translate(p, 0, 92)
holes = [to_new(Polygon(h)).simplify(0.02, preserve_topology=True) for h in orig.interiors]

# ---------- cavity / insert outline ----------
cavity = box(-82, 25, 82, 159).buffer(23, quad_segs=24)          # x +-105, y 2..182, R23
outline = cavity.buffer(-CLR, quad_segs=24)
bottom = cavity.buffer(-(CLR + 4.24 + 0.3), quad_segs=24)        # clears 4.24 x 8.47 floor chamfer
top = outline.buffer(-1.5, quad_segs=24)

def ext(poly, z0, z1):
    poly = orient(poly, 1.0)
    cs = mf.CrossSection([np.asarray(poly.exterior.coords)[:-1]] +
                         [np.asarray(r.coords)[:-1] for r in poly.interiors])
    return mf.Manifold.extrude(cs, z1 - z0).translate((0, 0, z0))
def ring(poly, z):
    xy = np.asarray(orient(poly, 1.0).exterior.coords)[:-1]
    return np.c_[xy, np.full(len(xy), z)]
def hull(*rings):
    return mf.Manifold.hull_points(np.vstack(rings))

body = (hull(ring(bottom, 0), ring(outline, 9.0))
        + ext(outline, 9.0, H - 1.5)
        + hull(ring(outline, H - 1.5), ring(top, H)))

# ---------- finger notches (U shape, open at top) ----------
def notch(cx, cy, width, axis):
    """axis='y': cut goes through along Y (wall runs along X); axis='x': through along X."""
    r = width / 2; zb = H - NOTCH_D + r; L = 30.0
    cyl = mf.Manifold.cylinder(L, r, r, 64).translate((0, 0, -L / 2))
    bx = mf.Manifold.cube((width, H, L)).translate((-r, 0, -L / 2))   # x:width, y:up, z:through
    u = (cyl + bx)
    # local frame: x across notch, y up, z through -> map to world
    if axis == "y":   # through = world Y, up = world Z, across = world X
        u = u.rotate((90, 0, 0))          # y->z, z->-y
    else:             # through = world X, across = world Y
        u = u.rotate((90, 0, 0)).rotate((0, 0, 90))
    return u.translate((cx, cy, zb))

# printer pocket in new coords
pp = max(holes, key=lambda p: p.area)
rolls = [h for h in holes if h is not pp and h.bounds[2] - h.bounds[0] > 150][0]
cable = [h for h in holes if h is not pp and h is not rolls][0]
print("printer pocket", np.round(pp.bounds, 2), "rolls", np.round(rolls.bounds, 2), "cable", np.round(cable.bounds, 2))
# keep the printer off the case floor chamfer (floor flat area ends at x=+-100.76)
pp_clipped = pp.intersection(box(-200, -200, 100.6, 400))
holes = [pp_clipped if h is pp else h for h in holes]
print("printer pocket clipped", np.round(pp.bounds, 2), "->", np.round(pp_clipped.bounds, 2))
pp = pp_clipped
mid_y = (pp.bounds[1] + pp.bounds[3]) / 2
for h in holes:
    body = body - ext(h, -1, H + 1)
# back notch: through the printer/roll divider at the middle cusp
body = body - notch(0.0, (pp.bounds[3] + rolls.bounds[1]) / 2, 28, "y")
# left-end notch: printer pocket <-> cable slot
body = body - notch((pp.bounds[0] + cable.bounds[2]) / 2, mid_y, 40, "x")

print("pre-translate vol", body.volume())
body = body.translate((0, 0, FLOOR))
body = body.simplify(0.005) if hasattr(body, "simplify") else body
mesh = body.to_mesh()
out = trimesh.Trimesh(mesh.vert_properties[:, :3], mesh.tri_verts, process=False)
print("manifold-direct watertight", out.is_watertight, "degenerate", int((out.area_faces<1e-9).sum()))
print("insert bounds", out.bounds.round(2).tolist(), "watertight", out.is_watertight, "vol cm3", round(out.volume / 1000, 1),
      "genus", body.genus())
out.export("/home/claude/out/insert_in_case.stl")
pr = out.copy(); pr.apply_translation((0, 0, -pr.bounds[0][2])); pr.export("/home/claude/out/Niimbot_M2_insert_SnapLockV3.stl")
test = (body.translate((0, 0, -FLOOR)) ^ mf.Manifold.cube((400, 400, 4)).translate((-200, -200, 10))).translate((0, 0, -10)).to_mesh()
t = trimesh.Trimesh(test.vert_properties[:, :3], test.tri_verts); t.export("/home/claude/out/Niimbot_M2_insert_TEST_slice_4mm.stl")
print("test slice vol cm3", round(t.volume / 1000, 1))
