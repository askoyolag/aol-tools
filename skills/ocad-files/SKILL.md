---
name: ocad-files
description: Read, inspect and measure OCAD orienteering map files (.ocd) — scale, georeferencing, symbols, colours, print frame, white-out blending and area. Use for any .ocd file question, og for spørsmål om kartfiler, målestokk, trykkramme og kartareal.
---

# Working with OCAD (.ocd) files

OCAD is the standard orienteering-map CAD format. `.ocd` files are binary, but the
layout is simple enough to parse directly in Python with `struct` — no OCAD
installation and no third-party library needed. Do not look for a pip package;
use `scripts/ocad.py` in this skill, or write the ~100-line parser yourself.

## File layout (v9 through 2018/2020)

### Header (offset 0)

| Offset | Type | Field |
|---|---|---|
| 0 | int16 | `OCADMark` — must be `0x0CAD` (3245) |
| 4 | int16 | `Version` — 9…12, or a year: `2018`, `2020` |
| 8 | uint32 | `FirstSymbolIndexBlk` — file position |
| 12 | uint32 | `ObjectIndexBlock` — file position |
| 32 | uint32 | `FirstStringIndexBlk` — file position |

### Object index blocks (linked list)

`int32 nextBlock`, then 256 entries of **40 bytes**:

| Offset | Type | Field |
|---|---|---|
| 0–15 | 4 × int32 | bounding box left, bottom, right, top |
| 16 | int32 | `Pos` — file position of the object record |
| 20 | int32 | `Len` — number of coordinate pairs |
| 24 | int32 | `Sym` — symbol number × 1000 (negative = graphic/image object) |
| 28 | uint8 | `ObjType` — **1 point, 2 line, 3 area, 4/5 text, 6 line text, 7 rectangle** |
| 30 | uint8 | `Status` — **0 deleted, 1 normal, 2 hidden, 3 undo**. Only read `Status == 1`. |

### Object record (at `Pos`)

`Sym` int32 @0, `Otp` uint8 @4, `Ang` int16 @6 (0.1°), `nItem` uint32 @44,
`nText` uint16 @48, coordinate array from **offset 56**, 8 bytes per point.

### Coordinates (`TDPoly`)

Two int32 per point; the **upper 24 bits are the value in 0.01 mm**, the lower 8
bits are flags.

```python
x_mm = (x >> 8) / 100.0
y_mm = (y >> 8) / 100.0
```

X flags: bit0/bit1 = first/second Bézier control point, bit2 = no left line,
bit3 = area border / virtual gap.
Y flags: bit0 = corner point, **bit1 = first point of a hole** (start a new ring
here), bit2 = no right line, bit3 = dash point.

Bézier control points can be kept as ordinary vertices for area/extent work.

### Symbol index blocks (linked list)

`uint32 nextBlock`, then **256 int32 file positions**. At each position, the
symbol header:

| Offset | Type | Field |
|---|---|---|
| 0 | int32 | `Size` |
| 4 | int32 | `SymNum` — symbol number × 1000 (`101.0` → `101000`) |
| 8 | uint8 | `Otp` |
| 11 | uint8 | `Status` — 0 normal, 1 protected, 2 hidden |
| 26 | int16 | `nColors` |
| 28 | 14 × int16 | `Colors` — colour numbers used |
| 56 | 64 bytes | `Description` — **UTF-16LE**, NUL-terminated (decoding as
  Latin-1 gives you a single letter, which is the usual sign you got this wrong) |

### String index blocks (linked list)

`uint32 nextBlock`, then 256 entries of **16 bytes**: `Pos`, `Len`, `RecType`,
`ObjIndex` (int32). String data at `Pos`, NUL-terminated, **cp1252**. Format:
first field, then tab-separated `<letter><value>` pairs.

Useful record types:

- **9 — colour definition**: field 0 is the colour *name*, `n` the colour number,
  `c`/`m`/`y`/`k` the CMYK values.
- **1039 — scale/georeferencing**: `m` map scale, `a` real-world angle (degrees),
  `x`/`y` real-world easting/northing of the map origin, `r` 1 = real-world
  coordinates, `e` EPSG code, `i` grid/zone id.
- **1026 — print area**: `L`,`B`,`R`,`T` in **map mm**, `a` **print scale**
  (often different from the map scale).

## Unit conversion — the thing that goes wrong

Coordinates are millimetres **at the map scale in string 1039**, not metres:

```
metres = mm × scale / 1000
```

Do **not** derive the scale from `d`/`g` in string 1039 — those fields are
frequently stale and can be off by a factor of 2 or more. Sanity-check instead:
convert the bounding box to metres and see whether the result matches the real
terrain size.

Full transform to real-world coordinates:

```python
f = scale / 1000.0
ca, sa = cos(radians(angle)), sin(radians(angle))
E = (x_mm*f)*ca - (y_mm*f)*sa + x0
N = (x_mm*f)*sa + (y_mm*f)*ca + y0
```

## The three areas people mean by "the area of the map"

Always ask, or state, which one you are reporting.

**1. Printed map area** — usually what a club wants. It is the print frame
**minus the white-out ("blending") that hides everything outside the intended
extract**:

- The frame is an object whose symbol description is `Ramme` (Norwegian) /
  `Frame`, typically `ObjType` 7. Fall back to the 1026 print rectangle, then to
  the largest rectangle or closed graphic object. Validate a 1026 rectangle by
  converting it to paper millimetres (`side_m × 1000 / print_scale`) and checking
  it is a plausible sheet size (roughly 80–1300 mm) — stale print rectangles are
  common and can sit kilometres away from the map.
- Blending is **area objects whose symbol uses a white colour** — the colour
  *name* contains "White"/"Hvit" (e.g. `White background`, `Hvit over bakgrunn`).
  Match on the colour name, not the number: colour 2 is `White background` in one
  file and `Svart` in the next.
- **Only treat layout symbols as blending.** Restrict to `SymNum < 10000`
  (layout/design symbols are 1.000–9.999; map symbols are ≥ 100000). Several
  ordinary ISOM symbols have white in their colour list — `Skog, typisk for
  området` uses `Hvit i gul` — and counting those as blending silently erases
  most of the forest.
- Holes in a white-out polygon are *not* masked: fill ring 0, then punch the
  remaining rings back in.
- Rasterize frame and blending together and count pixels; scale the result by the
  frame's exact polygon area to remove rasterization bias.

**2. Mapped terrain area** — what is actually surveyed. Rasterize all point,
line and area objects (exclude text, `ObjType` 4/5/6), morphologically close gaps
of ~25 m, take the largest connected component.

**3. Bounding box** — width × height of the content. Strip thin strays first with
a morphological opening (~15 m), or one forgotten line doubles it.

Use distance transforms, not `binary_dilation` with a large structuring element —
the latter is orders of magnitude slower:

```python
dilate = lambda m, r: ndimage.distance_transform_edt(~m) <= r
def erode(m, r, border_full=True):        # border_full keeps edge-touching regions
    p = int(np.ceil(r)) + 2
    return (ndimage.distance_transform_edt(
        np.pad(m, p, constant_values=border_full)) > r)[p:-p, p:-p]
```

Rasterize with `PIL.ImageDraw` (`polygon` for areas, `line` for lines) onto a
1-bit image; pick the cell size so the longest side is ~2000 px.

## Practical notes

- A **Design / course-setting file** holds the layout (frame, blending, legend,
  courses) over a background map — often only 20–70 objects. Its value is the
  frame and the blending, not its own geometry. The real map file is a sibling.
- A map file often contains a whole base map with the school or arena as a small
  printed extract. Compare the mapped area against the printed area before
  reporting a number.
- The printed frame may contain blank paper beyond where the map data ends.
  Intersect the printed mask with the closed map content to report how much of
  the sheet actually carries map.
- Objects with `Status != 1` are deleted — skipping them matters.
- Text objects placed outside the map (legend, title) inflate the bounding box.
- Always verify visually: plot map objects, the frame and the blending polygons
  to a PNG and look at it before reporting areas.

## Scripts

- `scripts/ocad.py` — `OcadFile`: header, parameter strings, `setup`
  (scale/georef), `print_area`, `objects()` with rings in map mm, `to_real()`.
- `scripts/ocad_print.py` — `symbol_table`, `color_names`, `find_frame`,
  `blend_rings`, `printed_area(design_path, map_path)` → printed / frame /
  blended / content areas in m².
- `scripts/ocad_area.py` — `analyse(path)` → mapped terrain area, bounding box,
  clusters.

Reference: the OCAD wiki file-format pages (`ocad.com/wiki`, "OCAD 12 File
Format") and `perliedman/ocad2geojson` on GitHub for a JavaScript implementation.
