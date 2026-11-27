#!/usr/bin/env python3
"""Generate the app icon (assets/AppIcon.icns) — stdlib-only.

Design: blue gradient rounded square; white line-art globe (outline,
meridian ellipse, three latitude chords) with a wire leaving the globe
to an endpoint node (client connects through it). The 1024 px master
is rendered with 4x supersampling, PNG-encoded by hand (zlib), then
scaled into an .iconset and packed by the system iconutil.

Run:  python3 make_icon.py   (needs macOS sips/iconutil for the .icns)
"""
import math
import os
import struct
import subprocess
import sys
import zlib

N = 1024
TOP = (57, 135, 229)      # #3987e5
BOT = (16, 66, 129)       # #104281
CORNER = 0.24 * N

# globe
GX, GY = 0.415 * N, 0.575 * N
RG = 0.31 * N
LINE_T = 0.022 * N        # half-thickness of all white strokes
MER_A = 0.46 * RG         # meridian ellipse semi-axis x

# wire: leaves the globe at +25 deg, runs up-right to a node dot
_A = math.radians(25.0)
WX0, WY0 = GX + RG * math.cos(_A), GY - RG * math.sin(_A)
WX1, WY1 = 0.815 * N, 0.23 * N
NODE_R = 0.05 * N

SUBS = ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75))


def _inside_rect(x, y):
    """Rounded-square membership."""
    lo, hi, r = CORNER, N - CORNER, CORNER
    if lo <= x <= hi or lo <= y <= hi:
        return True
    dx = max(lo - x, 0.0, x - hi)
    dy = max(lo - y, 0.0, y - hi)
    return dx * dx + dy * dy <= r * r


def _seg_dist(x, y):
    dx, dy = WX1 - WX0, WY1 - WY0
    t = ((x - WX0) * dx + (y - WY0) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    px, py = WX0 + t * dx, WY0 + t * dy
    return math.hypot(x - px, y - py)


def _white(x, y):
    dx, dy = x - GX, y - GY
    r = math.hypot(dx, dy)
    if math.hypot(x - WX1, y - WY1) <= NODE_R:
        return True
    if r > RG + LINE_T:
        # outside the globe: the wire/node live up-right of it
        if x >= GX and _seg_dist(x, y) <= LINE_T:
            return True
        return False
    # globe outline ring
    if abs(r - RG) <= LINE_T:
        return True
    # meridian ellipse ring
    e = math.sqrt((dx / MER_A) ** 2 + (dy / RG) ** 2)
    if abs(e - 1.0) * MER_A <= LINE_T:
        return True
    # latitude chords (skip where they'd cross the outline band)
    if abs(r - RG) < 2 * LINE_T:
        return False
    for fy in (0.0, -0.52, 0.52):
        yc = GY + fy * RG
        half = math.sqrt(max(0.0, RG * RG - (fy * RG) ** 2))
        if abs(y - yc) <= LINE_T and abs(dx) <= half:
            return True
    # wire start section inside the globe rim
    if _seg_dist(x, y) <= LINE_T:
        return True
    return False


def render():
    rows = []
    for py in range(N):
        row = bytearray()
        fy = py / (N - 1)
        c0, c1, c2 = (TOP[i] + (BOT[i] - TOP[i]) * fy for i in range(3))
        for px in range(N):
            cov = 0
            g = 0
            for sx, sy in SUBS:
                x, y = px + sx, py + sy
                if _inside_rect(x, y):
                    cov += 1
                    if _white(x, y):
                        g += 1
            if cov == 0:
                row += b"\x00\x00\x00\x00"
                continue
            t = g / 4.0
            r = c0 + (255 - c0) * t
            gg = c1 + (255 - c1) * t
            b = c2 + (255 - c2) * t
            row += bytes((round(r), round(gg), round(b), cov * 255 // 4))
        rows.append(bytes(row))
    return rows


def png_bytes(rows, size=N):
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6,
                                         0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def write_png(path, rows):
    with open(path, "wb") as f:
        f.write(png_bytes(rows))


def downscale(rows, side):
    """Box-average the N×N RGBA rows down to `side`×`side` (alpha-weighted
    so antialiased edges don't darken)."""
    f = N // side
    out = []
    for oy in range(side):
        row = bytearray()
        for ox in range(side):
            sa = sr = sg = sb = 0
            for dy in range(f):
                src = rows[oy * f + dy]
                for dx in range(f):
                    i = (ox * f + dx) * 4
                    a = src[i + 3]
                    sa += a
                    sr += src[i] * a
                    sg += src[i + 1] * a
                    sb += src[i + 2] * a
            if sa == 0:
                row += b"\x00\x00\x00\x00"
            else:
                row += bytes((round(sr / sa), round(sg / sa),
                              round(sb / sa), min(255, round(sa / (f * f)))))
        out.append(bytes(row))
    return out


def ico_bmp(rows, side):
    """BITMAPINFOHEADER form of an RGBA image for an ICO entry: bottom-up
    32bpp BGRA + all-zero AND mask. Classic BMP entries — NOT the
    PNG-compressed Vista+ kind: the Windows taskbar icon path and
    LoadImageW render PNG entries unreliably (the taskbar button falls
    back to the feather default)."""
    hdr = struct.pack("<IiiHHIIiiII", 40, side, side * 2, 1, 32, 0,
                      0, 0, 0, 0, 0)
    px = b"".join(
        b"".join(bytes((row[i + 2], row[i + 1], row[i], row[i + 3]))
                 for i in range(0, side * 4, 4))
        for row in reversed(rows))
    mask = b"\x00" * (((side + 31) // 32) * 4) * side
    return hdr + px + mask


def write_ico(path, entries):
    """entries: [(side, bmp_bytes from ico_bmp), ...] — classic ICO."""
    out = struct.pack("<HHH", 0, 1, len(entries))
    off = 6 + 16 * len(entries)
    for side, png in entries:
        s = 0 if side >= 256 else side   # 256 is encoded as 0
        out += struct.pack("<BBBBHHII", s, s, 0, 0, 1, 32, len(png), off)
        off += len(png)
    for _, png in entries:
        out += png
    with open(path, "wb") as f:
        f.write(out)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    assets = os.path.join(here, "assets")
    os.makedirs(assets, exist_ok=True)
    master = os.path.join(assets, "AppIcon.png")
    rows = render()
    write_png(master, rows)
    print("master:", master)

    ico = os.path.join(assets, "AppIcon.ico")
    entries = [(s, ico_bmp(downscale(rows, s), s))
               for s in (16, 32, 48, 256)]
    write_ico(ico, entries)
    print("ico:", ico)

    if sys.platform != "darwin":
        print("iconutil is macOS-only; PNG master only")
        return
    iconset = os.path.join(assets, "AppIcon.iconset")
    os.makedirs(iconset, exist_ok=True)
    for name, side in (("16x16", 16), ("16x16@2x", 32), ("32x32", 32),
                       ("32x32@2x", 64), ("128x128", 128),
                       ("128x128@2x", 256), ("256x256", 256),
                       ("256x256@2x", 512), ("512x512", 512),
                       ("512x512@2x", N)):
        out = os.path.join(iconset, f"icon_{name}.png")
        subprocess.run(["sips", "-z", str(side), str(side), master,
                        "--out", out], check=True,
                       stdout=subprocess.DEVNULL)
    icns = os.path.join(assets, "AppIcon.icns")
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns],
                   check=True)
    print("icns:", icns)


if __name__ == "__main__":
    main()
