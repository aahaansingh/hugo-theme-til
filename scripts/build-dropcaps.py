#!/usr/bin/env python3
"""Build the engraved drop caps: web-sized SVGs + the CSS that wraps text around them.

Usage:
  python3 scripts/build-dropcaps.py SRC_DIR            # e.g. ../dropcaps/web (one <LETTER>.svg each)
  (outputs: static/dropcaps/<L>.svg, assets/css/dropcaps.css, data/dropcaps.json)
  Needs: numpy, scikit-image, pillow, fonttools, brotli.   Takes a couple of minutes.

Per letter:
  1. parse the traced path, scale all letters by one factor, flatten + simplify it
     (Douglas-Peucker), drop specks, and crop the viewBox to the ink.
  2. size it to span N lines: cap-top of line 1 -> baseline of line N (Bringhurst), using
     the body font's real metrics.
  3. measure its right-hand profile line by line and emit a stepped shape-outside polygon,
     so every line of text is "mortised" against the letter with a fixed gap.
     Two gaps: tight when the initial begins a longer word, wide when it is a word itself.

Geometry is in em, so it scales with font-size. It assumes the paragraph line-height LH
(set on .dc-para in main.css) and that the body font is FONT.
"""
import json, re, sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from skimage.measure import approximate_polygon
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / 'static/fonts/SourceSerif4-VariableFont.woff2'  # body font (upright)
LH = 1.7777778          # body line-height (prose-lg: 32/18); keep in sync with .dc-para in main.css
N = 3                   # lines deep
EM = 100                # px/em for the profile raster
DELTA = 0.04            # em dead zone at band edges (browsers snap line boxes a hair)
MIN_INK = 0.08          # a column only counts if it holds >= this much ink (em) in a line band
GAPS = {'': 0.30, 'word': 0.60}   # em between letter and text; 'word' = initial is its own word

# Per-letter tuning (all fractions are of the letter's cropped ink height):
#   top / bot : how much of the top / bottom of the ink box is ornament or overshoot rather than
#               the "body" of the letter. The body (the rest) is what gets cap-top -> baseline;
#               the trimmed parts poke out above the first line / below the baseline.
#   straight  : True for letters whose right edge is (nearly) a straight vertical, so the text is set
#               against one straight line (the furthest-right line sets it) instead of a stepped profile
#   rotate    : degrees, + = clockwise on screen, applied before cropping
#   extra     : extra em of space on lines 1, 2, 3 (dense ink at the lower lines reads tighter
#               than the same gap beside a thin flourish tip)
TUNE = {
    'A': {'bot': 0.014},
    'B': {'top': 0.030, 'bot': 0.016, 'extra': [0, 0.12, 0.12]},
    'D': {'top': 0.065},
    'E': {'extra': [0, 0.12, 0.12]},
    'F': {'extra': [0, 0.12, 0.12]},
    'G': {'top': 0.050, 'bot': 0.036},
    'H': {'bot': 0.012, 'straight': True},
    'I': {'bot': 0.008, 'straight': True},
    'K': {'bot': 0.025},
    'L': {'top': 0.085, 'bot': 0.018, 'rotate': -0.9},
    'M': {'bot': 0.016, 'straight': True},
    'N': {'bot': 0.014, 'straight': True},
    'O': {'top': 0.080, 'bot': 0.030},
    'P': {'bot': 0.012},
    'Q': {'top': 0.060},
    'S': {'top': 0.063, 'bot': 0.018},
    'T': {'top': 0.066},
    'X': {'bot': 0.012, 'extra': [0, 0.12, 0.12]},
    'Z': {'bot': 0.012, 'extra': [0, 0.12, 0.12]},
}

SCALE = 0.3             # output SVG units per source unit
EPS = 0.6               # simplification tolerance (SVG units)
MIN_AREA = 2.0          # drop rings smaller than this (SVG units squared)
TS = [i / 4 for i in range(1, 5)]
TOKEN = re.compile(r'([MLCZ])([^MLCZ]*)')
NUM = re.compile(r'-?\d+(?:\.\d+)?')


def parse(d):
    rings, cur, pos = [], None, None
    for cmd, args in TOKEN.findall(d):
        n = [float(x) for x in NUM.findall(args)]
        if cmd == 'M':
            pos = (n[0], n[1]); cur = [pos]
        elif cmd == 'L':
            for i in range(0, len(n), 2):
                pos = (n[i], n[i + 1]); cur.append(pos)
        elif cmd == 'C':
            for i in range(0, len(n), 6):
                x1, y1, x2, y2, x3, y3 = n[i:i + 6]
                x0, y0 = pos
                for t in TS:
                    u = 1 - t
                    a, b, c, e = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
                    cur.append((a * x0 + b * x1 + c * x2 + e * x3, a * y0 + b * y1 + c * y2 + e * y3))
                pos = (x3, y3)
        elif cmd == 'Z':
            if cur and len(cur) > 2:
                rings.append(np.array(cur))
            cur = None
    return rings


def area(r):
    x, y = r[:, 0], r[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


def simplify(rings, prescaled=False):
    out = []
    for r in rings:
        r = r if prescaled else r * SCALE
        if area(r) < MIN_AREA:
            continue
        s = approximate_polygon(np.vstack([r, r[:1]]), EPS)[:-1]
        s = np.rint(s).astype(int)
        keep = np.ones(len(s), bool)
        keep[1:] = np.any(np.diff(s, axis=0) != 0, axis=1)
        s = s[keep]
        if len(s) >= 3:
            out.append(s)
    return out


def rotate(rings, deg):
    if not deg:
        return rings
    allp = np.vstack(rings)
    c = (allp.min(0) + allp.max(0)) / 2
    t = np.radians(deg)
    R = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    return [(r - c) @ R.T + c for r in rings]


def crop(rings):
    allp = np.vstack(rings)
    mn, mx = allp.min(0), allp.max(0)
    return [r - mn for r in rings], int(mx[0] - mn[0]), int(mx[1] - mn[1])


def to_svg(rings, w, h):
    parts = []
    for s in rings:
        deltas = np.diff(s, axis=0)
        parts.append(('M%d %d' % (s[0][0], s[0][1])) + 'l' + ' '.join(str(int(v)) for dv in deltas for v in dv) + 'z')
    d = ''.join(parts).replace(' -', '-')
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d"><path fill-rule="evenodd" d="%s"/></svg>' % (w, h, d)


def raster(rings, w, h, px_w, px_h):
    """Even-odd fill of the rings into a boolean array (px_h x px_w)."""
    canvas = np.zeros((px_h, px_w), bool)
    kx, ky = px_w / w, px_h / h
    for s in rings:
        pts = [(float(x) * kx, float(y) * ky) for x, y in s]
        x0, y0 = int(max(0, min(p[0] for p in pts) - 1)), int(max(0, min(p[1] for p in pts) - 1))
        x1, y1 = int(min(px_w, max(p[0] for p in pts) + 2)), int(min(px_h, max(p[1] for p in pts) + 2))
        if x1 <= x0 or y1 <= y0:
            continue
        im = Image.new('L', (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(im).polygon([(x - x0, y - y0) for x, y in pts], fill=1)
        canvas[y0:y1, x0:x1] ^= np.asarray(im, bool)
    return canvas


# ---- metrics from the body font ----
f = TTFont(str(FONT))
upm = f['head'].unitsPerEm
CAP = f['OS/2'].sCapHeight / upm
ASC, DESC = f['hhea'].ascent / upm, -f['hhea'].descent / upm
gs, cmap = f.getGlyphSet(), f.getBestCmap()


def ink_y(chars, idx):
    v = []
    for c in chars:
        bp = BoundsPen(gs); gs[cmap[ord(c)]].draw(bp); v.append(bp.bounds[idx])
    return v


asc_ink = max(ink_y('bdfhklt', 3)) / upm
desc_ink = -min(ink_y('gjpqy', 1)) / upm
BASE = (LH - (ASC + DESC)) / 2 + ASC     # baseline offset inside a line box
OFF = BASE - CAP                         # cap-top offset inside line 1
ZONE = (BASE - asc_ink - 0.02, BASE + desc_ink + 0.02)   # where text ink lives in a line box


def main():
    src = Path(sys.argv[1])
    out = ROOT / 'static/dropcaps'
    out.mkdir(parents=True, exist_ok=True)
    css = ['/* generated by scripts/build-dropcaps.py -- do not edit */']
    manifest = {}
    Hs = CAP + (N - 1) * LH                  # cap-top(line 1) .. baseline(line N), em
    print('metrics: cap=%.3f base=%.4f off=%.4f Hs=%.3f' % (CAP, BASE, OFF, Hs))
    for f_ in sorted(src.glob('*.svg')):
        L = f_.stem.upper()
        svg = f_.read_text()
        tune = TUNE.get(L, {})
        cache = ROOT / '.cache-dropcaps' / (f_.stem + '.npz')   # parsing the huge source paths is the slow part
        if cache.exists() and cache.stat().st_mtime >= f_.stat().st_mtime:
            z = np.load(cache)
            raw = [z['r%d' % i] for i in range(len(z.files))]
        else:
            raw = parse(re.search(r' d="([^"]+)"', svg).group(1))
            cache.parent.mkdir(exist_ok=True)
            np.savez_compressed(cache, **{'r%d' % i: r for i, r in enumerate(raw)})
        rings = simplify(rotate([r * SCALE for r in raw], tune.get('rotate', 0)), prescaled=True)
        rings, w, h = crop(rings)
        (out / f_.name).write_text(to_svg(rings, w, h))
        top, bot = tune.get('top', 0.0), tune.get('bot', 0.0)
        extra = tune.get('extra', [0] * N)
        # the "body" (ink height minus the trimmed top/bottom) spans cap-top -> baseline
        k = Hs / (h * (1 - top - bot))            # em per SVG unit
        Ws, Hg = w * k, h * k
        yoff = OFF - top * Hg                     # em from the top of line 1 to the top of the glyph box
        a = raster(rings, w, h, round(Ws * EM), round(Hg * EM))
        rights = []
        for kk in range(N):
            y0, y1 = kk * LH + ZONE[0], kk * LH + ZONE[1]
            r0, r1 = max(0, int((y0 - yoff) * EM)), min(a.shape[0], int(np.ceil((y1 - yoff) * EM)))
            band = a[r0:r1] if r1 > r0 else a[:0]
            cols = np.where(band.sum(0) / EM >= MIN_INK)[0] if len(band) else []
            rights.append(float((cols.max() + 1) / EM) if len(cols) else 0.0)
        css.append('.dc-%s .dc-glyph { width: %.3fem; height: %.3fem; margin-top: %.4fem; -webkit-mask-image: url(../dropcaps/%s.svg); mask-image: url(../dropcaps/%s.svg); }'
                   % (L, Ws, Hg, yoff, L, L))
        for name, g in GAPS.items():
            xs = [r + g + e for r, e in zip(rights, extra)]
            if tune.get('straight'):
                xs = [max(xs)] * N
            pts, y_top = [(0, 0)], 0.0
            for kk, x in enumerate(xs):
                last = kk == N - 1
                y_bot = N * LH - DELTA if last else (kk + 1) * LH - DELTA
                pts += [(x, y_top), (x, y_bot)]
                if not last:
                    m = min(x, xs[kk + 1])
                    y_top = (kk + 1) * LH + DELTA
                    pts += [(m, y_bot), (m, y_top)]
            pts.append((0, N * LH - DELTA))
            poly = ', '.join('%.3fem %.3fem' % p for p in pts)
            sel = '.dc-%s' % L + ('.dc-%s' % name if name else '')
            css.append('%s .dc { width: %.3fem; shape-outside: polygon(%s); }' % (sel, max(xs), poly))
        manifest[L] = {'aspect': round(w / h, 4), 'rights': [round(r, 2) for r in rights]}
        print('%s: %d KB  aspect %.2f  glyph %.2fx%.2fem  rights %s' % (L, len(to_svg(rings, w, h)) // 1024, w / h, Ws, Hg, [round(r, 2) for r in rights]))
    (ROOT / 'assets/css/dropcaps.css').write_text('\n'.join(css) + '\n')
    (ROOT / 'data').mkdir(exist_ok=True)
    (ROOT / 'data/dropcaps.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print('wrote assets/css/dropcaps.css and data/dropcaps.json')


if __name__ == '__main__':
    main()
