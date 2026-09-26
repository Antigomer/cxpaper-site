# -*- coding: utf-8 -*-
"""Builds the Paper Airplane storybook and splices it into index.html.

    python tools/paper_airplane/build.py

WHY A GENERATOR. The other storybooks are 20 s and hand-written. This one is
Chris's longer film (2026-09-26: "slow everything down ... the goal is to
communicate what it can do, not to have it stay under a certain length"), and
it has well over a hundred timed steps. Every time below is written in
SECONDS and turned into keyframe percentages here, so changing the length of
one beat is a change to one number rather than to every percentage after it.

The page is still the thing that ships: this writes the section between the
BEGIN/END PAPER AIRPLANE markers in index.html and nothing else. It lives in
tools/, which _config.yml keeps out of what Pages serves: versioned, not
published. The four .svg files beside it are drawing reused verbatim - the
throw (side, fig), the drone from above, and the truck cab from the Rename
storybook.

WHAT THE FILM SAYS, and where each fact comes from in PST_Build:
  1. The throw; the camera becomes a drone and flies the right-of-way.
  2. LATER, at the truck, the clip is opened in the player. The marking is
     not done in the air - Chris's correction to the first cut.
  3. Pause, pick the class, click it on the frame (video_player.py: the
     "Marking" list is Jane's erosion-control classes in taxonomy order,
     "Marks on this clip" rows are m0001..., "Save the redline (KMZ)").
     A filter bag out in the crop past the LOD flagging; at the stream
     crossing two silt fences and an erosion control blanket.
  4. Deliverable: the clip with the Marco Polocator overlay burned in
     (video_overlay.py / video_render.py - the same layout as a photograph).
  5. Deliverable: the redline KMZ (ecd_video/redline_export.py + export.py):
     doc "Redline - <spread>", folder "Erosion control devices", a folder per
     class "<label> (n)" sorted by label, placemarks "<station> <label>",
     every mark in the erosion-control style ff50c8a0 (#A0C850), areas at
     half fill, and the balloon rows Station / Class / Found by / In the clip
     at / Note, where the note carries "[m0001, 1 frame, drawn ...]".
Values (stations, times, coordinates) are illustrative.
"""

import math
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
INDEX = ROOT / "index.html"

DUR = 88.0          # seconds, the whole film
CLIP_S = 226.0      # the clip's own length, 03:46
SPREAD = "These Big Jobs - Spread I"


def F(v):
    s = ("%.2f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def P(t):
    s = ("%.3f" % (t / DUR * 100.0)).rstrip("0").rstrip(".")
    return (s or "0") + "%"


CSS = []
TC = []     # the player's timecodes, (class, text), filled by build()


def kf(cls, stops, base="", timing=None, origin=None):
    """One timeline animation. `stops` is [(t or (t1, t2...), decl)] in
    seconds; the first stop is held back to 0 and the last out to DUR, so a
    stop list says only when things change."""
    stops = [((t,) if not isinstance(t, (tuple, list)) else tuple(t), d)
             for t, d in stops]
    first_t, first_d = stops[0]
    if first_t[0] > 0:
        stops[0] = ((0.0,) + first_t, first_d)
    last_t, last_d = stops[-1]
    if last_t[-1] < DUR:
        stops[-1] = (last_t + (DUR,), last_d)
    frames = "".join("%s{%s}" % (",".join(P(x) for x in ts), d) for ts, d in stops)
    extra = ""
    if timing:
        extra += "animation-timing-function:%s;" % timing
    if origin:
        extra += "transform-origin:%s;" % origin
    CSS.append(".pap-scope .%s{%sanimation-name:%s;%s}\n@keyframes %s{%s}"
               % (cls, base, cls, extra, cls, frames))


def vis(cls, on, off=None, fade=0.4, fade_out=None, move=None):
    """Hidden, then shown at `on` (fading over `fade`), then hidden again at
    `off`. `move` is an optional transform it arrives from."""
    fo = fade if fade_out is None else fade_out
    a = "opacity:0" + (";transform:%s" % move if move else "")
    b = "opacity:1" + (";transform:none" if move else "")
    stops = [(on, a), (on + fade, b)]
    if off is not None:
        stops += [(off, b), (off + fo, "opacity:0" + (";transform:none" if move else ""))]
    kf(cls, stops, base="opacity:0;")


def steps_on(cls, windows, base_hidden=True):
    """Instant switches: shown during each (t_on, t_off)."""
    eps = 0.02
    stops = []
    for on, off in windows:
        stops.append((on - eps, "opacity:0"))
        stops.append((on, "opacity:1"))
        if off is not None:
            stops.append((off - eps, "opacity:1"))
            stops.append((off, "opacity:0"))
    kf(cls, stops, base="opacity:0;" if base_hidden else "")


def draw(cls, t0, t1, timing="linear"):
    kf(cls, [(t0, "stroke-dashoffset:100"), (t1, "stroke-dashoffset:0")],
       base="stroke-dasharray:100;stroke-dashoffset:100;fill:none;", timing=timing)


# ============================================================ the ground
# The map the drone flies over, and the same ground again in the KMZ view and
# the overlay's mini-map. One drawing used three times, so a mark in Google
# Earth sits exactly on the thing the drone filmed.
SEGS = [((-60, 380), (200, 380), (420, 330), (560, 305)),
        ((560, 305), (700, 280), (860, 250), (1060, 240))]


def bez(s, t):
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = s
    u = 1 - t
    x = u**3*x0 + 3*u*u*t*x1 + 3*u*t*t*x2 + t**3*x3
    y = u**3*y0 + 3*u*u*t*y1 + 3*u*t*t*y2 + t**3*y3
    dx = 3*u*u*(x1-x0) + 6*u*t*(x2-x1) + 3*t*t*(x3-x2)
    dy = 3*u*u*(y1-y0) + 6*u*t*(y2-y1) + 3*t*t*(y3-y2)
    return x, y, dx, dy


_S = []
_L = 0.0
_prev = None
for _seg in SEGS:
    for _i in range(3001):
        x, y, dx, dy = bez(_seg, _i / 3000.0)
        if _prev:
            _L += math.hypot(x - _prev[0], y - _prev[1])
        n = math.hypot(dx, dy)
        _S.append((_L, x, y, dx / n, dy / n))
        _prev = (x, y)


def at_s(s):
    # straight on past either end: the clip starts west of where the curve does
    if s <= 0:
        _, x, y, tx, ty = _S[0]
        return (x + tx * s, y + ty * s, tx, ty)
    if s >= _L:
        _, x, y, tx, ty = _S[-1]
        return (x + tx * (s - _L), y + ty * (s - _L), tx, ty)
    lo, hi = 0, len(_S) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if _S[mid][0] < s:
            lo = mid + 1
        else:
            hi = mid
    i = max(1, lo)
    a, b = _S[i - 1], _S[i]
    f = (s - a[0]) / ((b[0] - a[0]) or 1)
    return tuple(a[k] + (b[k] - a[k]) * f for k in range(1, 5))


def s_at_x(x):
    for r in _S:
        if r[1] >= x:
            return r[0]
    return _S[-1][0]


def off(s, d):
    x, y, tx, ty = at_s(s)
    return (x - ty * d, y + tx * d)


def poly(pts, close=False):
    return "M" + " L".join("%s %s" % (F(a), F(b)) for a, b in pts) + (" Z" if close else "")


def run(s0, s1, d, n=40):
    return [off(s0 + (s1 - s0) * i / n, d) for i in range(n + 1)]


def ang(s):
    x, y, tx, ty = at_s(s)
    return math.degrees(math.atan2(ty, tx))


S_BAG = s_at_x(330)       # where the filter bag is, beside the ROW
S_X = s_at_x(706)         # where the stream crosses the ROW
S_NEAR, S_FAR = S_X - 30, S_X + 32
FT_PER_PX = 285.0 / (S_X - S_BAG)   # 2206+40 at the bag, 2209+25 at the crossing


def sta_ft(s):
    return 220640.0 + (s - S_BAG) * FT_PER_PX


def sta_text(ft, step=10):
    ft = int(round(ft / step) * step)
    return "%d+%02d" % (ft // 100, ft % 100)


BAG = off(S_BAG, 96)
BAG_STA = sta_text(sta_ft(S_BAG))
NEAR_STA = sta_text(sta_ft(S_NEAR))
FAR_STA = sta_text(sta_ft(S_FAR))
BLK_STA = sta_text(sta_ft(S_X - 19))

# the flight: across the whole map, one clip
S_FLY0, S_FLY1 = s_at_x(-40), s_at_x(1060)
FLY_T0, FLY_T1 = 12.6, 22.6

# ============================================================ the camera
# The video is one scene seen by a camera moving down the line, not pictures
# swapped at the pause. Chris, 2026-09-26: the marked things "just show up out
# of nowhere" - "we should see them coming in the distance and pause when the
# video is close". A point on the ground d map-px ahead is drawn at
# y = HOR + KG/d, so a thing scales about the vanishing point by (its distance
# when drawn) / (its distance now). KG comes from the two silt fences as the
# crossing frame draws them, which puts the bag, the stream and the blanket
# within a few px of where they were already drawn.
VP = (368.0, 86.0)
HOR = VP[1]
BOT = 433.0
NEAR_Y, FAR_Y = 300.5, 212.5      # the silt fences, paused at the crossing
BAG_Y = 293.0                     # the filter bag, paused on it
KG = (S_FAR - S_NEAR) / (1.0 / (FAR_Y - HOR) - 1.0 / (NEAR_Y - HOR))
CAM_A = S_BAG - KG / (BAG_Y - HOR)
CAM_B = S_NEAR - KG / (NEAR_Y - HOR)

# Stakes every 100 ft go by on a loop of SLOTS pairs. Nine loops to the film,
# so the loop and the timeline agree at every pause and the stakes stand still
# where they were rather than jumping.
SLOTS = 8
SPACING = 100.0 / FT_PER_PX
P_LOOP = DUR / (SLOTS * 9)
V = SPACING / P_LOOP               # the drone: map px per second of film

T = dict(
    stage_in=0.6, stage_out=86.9,
    rel=4.1, apex=5.9,
    tilt0=10.2, tilt1=11.4, tilt2=12.6,
    map_out=23.4,
    truck=23.6, lap=24.2, click_open=26.8, player_small=27.2, zoom0=27.8, zoom1=29.4,
    play1=29.6, pauseA=33.6,
    pick_bag=35.2, click_bag=37.0,
    pick_fence=44.0,
    n1=45.0, n2=46.0, n3=47.0, n4=48.0, n_done=48.4,
    f1=49.4, f2=50.2, f3=51.0, f_done=51.4,
    pick_blk=52.6,
    b1=53.6, b2=54.3, b3=55.0, b4=55.7, b_close=56.4,
    save=57.9,
    player_out=60.0,
    ov_in=60.6, ov_out=70.6,
    ge_in=71.6, marks=73.6, gclick=77.0,
)
# resume after a whole number of stake steps, and fly on to the crossing at the
# same speed it came up to the bag
T["play2"] = T["pauseA"] + 5 * P_LOOP
T["pauseB"] = T["play2"] + (CAM_B - CAM_A) / V
CAM_P1 = CAM_A - V * (T["pauseA"] - T["play1"])
S_CLIP0 = CAM_P1                   # 00:00 is where the player first shows it
OV_T0, OV_T1 = T["ov_in"], T["ov_out"] + 0.8


def cam_player(t):
    a, b, c, d = T["play1"], T["pauseA"], T["play2"], T["pauseB"]
    if t <= a:
        return CAM_P1
    if t <= b:
        return CAM_P1 + (CAM_A - CAM_P1) * (t - a) / (b - a)
    if t <= c:
        return CAM_A
    if t <= d:
        return CAM_A + (CAM_B - CAM_A) * (t - c) / (d - c)
    return CAM_B


def cam_overlay(t):
    """The clip with the overlay, from 00:00, at the speed the player flew it
    - it does not pause, and it is still flying when it fades."""
    return S_CLIP0 + V * (min(max(t, OV_T0), OV_T1) - OV_T0)


def clip_time(s):
    return CLIP_S * (s - S_CLIP0) / (S_FLY1 - S_CLIP0)


def mmss(sec):
    sec = int(round(sec))
    return "%02d:%02d" % (sec // 60, sec % 60)


T_A = clip_time(CAM_A)     # he pauses as the bag comes up close
T_B = clip_time(CAM_B)     # and again at the crossing

# the line carries on straight west of the drawn curve, because the clip does
S_WEST = min(S_FLY0, S_CLIP0) - 200
CL_PATH = "M%s 380 L-60 380 C200 380 420 330 560 305 C700 280 860 250 1060 240" % F(at_s(S_WEST)[0])


def rot_rect(s, along0, along1, a0, a1):
    return [off(s + along0, a0), off(s + along1, a0), off(s + along1, a1), off(s + along0, a1)]


def ground():
    g = []
    g.append('<rect x="-600" y="-20" width="1750" height="620" fill="#7F9A24"/>')
    g.append('<path d="M612 -20 L990 -10 L976 150 L664 160 L630 70 Z" fill="#93AD42"/>')
    g.append('<path d="M-150 70 L120 60 L150 250 L-150 262 Z" fill="#8CA637"/>')
    g.append('<path d="M780 380 L1150 372 L1150 600 L800 600 Z" fill="#8FA93C"/>')
    for d in ('M-40 30 C40 -6 152 2 212 38 C268 72 250 146 178 164 C110 182 20 162 -22 122 C-54 90 -60 48 -40 30 Z',
              'M846 452 C920 424 1010 440 1040 480 C1070 520 1030 600 950 606 C870 612 820 584 812 544 C804 500 816 464 846 452 Z'):
        g.append('<path d="%s" fill="#161311" opacity=".14" transform="translate(5,7)"/>' % d)
        g.append('<path d="%s" fill="#4B6006"/>' % d)
    g.append('<path d="M268 60 a9 9 0 1 0 .1 0z M320 122 a7 7 0 1 0 .1 0z M382 40 a7 7 0 1 0 .1 0z M470 86 a9 9 0 1 0 .1 0z M556 52 a7 7 0 1 0 .1 0z M560 520 a7 7 0 1 0 .1 0z M640 500 a8 8 0 1 0 .1 0z M92 520 a8 8 0 1 0 .1 0z" fill="#4B6006" opacity=".8"/>')
    stream = "M646 -20 C680 80 722 150 708 230 C694 300 690 360 716 430 C734 480 748 540 762 600"
    g.append('<path d="%s" fill="none" stroke="#4B6006" stroke-width="64" opacity=".55"/>' % stream)
    # the crop, standing, south of the ROW: rows run with the line
    c0, c1 = s_at_x(150), s_at_x(500)
    crop = run(c0, c1, 60) + run(c1, c0, 250)
    g.append('<path d="%s" fill="#6E8C1A"/>' % poly(crop, True))
    rows = " ".join(poly(run(c0, c1, d, 30)) for d in range(70, 250, 13))
    g.append('<path d="%s" fill="none" stroke="#4B6006" stroke-width="4" opacity=".75"/>' % rows)
    # the right-of-way
    cl = CL_PATH
    g.append('<path d="%s" fill="none" stroke="#161311" stroke-width="116" opacity=".55"/>' % cl)
    g.append('<path d="%s" fill="none" stroke="#CFBC99" stroke-width="110"/>' % cl)
    g.append('<path d="%s" fill="none" stroke="#B9A98D" stroke-width="18"/>' % poly(run(S_WEST, S_FLY1 + 30, -26, 90)))
    g.append('<path d="%s" fill="none" stroke="#2A2320" stroke-width="5"/>' % poly(run(S_WEST, S_FLY1 + 30, 10, 90)))
    # the stream, through it
    g.append('<path d="%s" fill="none" stroke="#5083E2" stroke-width="16"/>' % stream)
    g.append('<path d="%s" fill="none" stroke="#8FB2E8" stroke-width="5"/>' % stream)
    # LOD flagging along the south edge where the crop is
    flags = " ".join("M%s %s a2.4 2.4 0 1 0 .1 0z" % tuple(F(v) for v in off(s, 56))
                     for s in [c0 + i * 18 for i in range(int((c1 - c0) / 18) + 1)])
    g.append('<path d="%s" fill="#BB0A10"/>' % flags)
    # dewatering: a bell hole in the ROW, a pump, and a hose out past the LOD to the bag
    bh = off(S_BAG - 8, 28)
    g.append('<ellipse cx="%s" cy="%s" rx="10" ry="7" fill="#2A2320"/>' % (F(bh[0]), F(bh[1])))
    g.append('<ellipse cx="%s" cy="%s" rx="6.5" ry="4.5" fill="#5083E2"/>' % (F(bh[0]), F(bh[1])))
    pu = off(S_BAG + 6, 38)
    g.append('<rect x="%s" y="%s" width="9" height="7" fill="#F0A53A" stroke="#161311" stroke-width="1" transform="rotate(%s %s %s)"/>'
             % (F(pu[0] - 4.5), F(pu[1] - 3.5), F(ang(S_BAG)), F(pu[0]), F(pu[1])))
    h1 = off(S_BAG + 4, 70)
    g.append('<path d="M%s %s Q%s %s %s %s" fill="none" stroke="#161311" stroke-width="2.4"/>'
             % (F(pu[0]), F(pu[1]), F(h1[0]), F(h1[1]), F(BAG[0]), F(BAG[1] - 3)))
    g.append('<ellipse cx="%s" cy="%s" rx="17" ry="11" fill="#3F4A1E" opacity=".5" transform="rotate(%s %s %s)"/>'
             % (F(BAG[0]), F(BAG[1] + 1), F(ang(S_BAG)), F(BAG[0]), F(BAG[1] + 1)))
    g.append('<rect x="%s" y="%s" width="18" height="10" rx="3" fill="#C9B48A" stroke="#8A7550" stroke-width="1.2" transform="rotate(%s %s %s)"/>'
             % (F(BAG[0] - 9), F(BAG[1] - 5), F(ang(S_BAG)), F(BAG[0]), F(BAG[1])))
    # the crossing: silt fence both banks, a blanket on the near bank, the mat bridge
    for s in (S_NEAR, S_FAR):
        a, b = off(s, -57), off(s, 57)
        g.append('<path d="M%s %s L%s %s" stroke="#161311" stroke-width="2.8"/>' % (F(a[0]), F(a[1]), F(b[0]), F(b[1])))
        posts = " ".join("M%s %s a1.9 1.9 0 1 0 .1 0z" % tuple(F(v) for v in off(s, d)) for d in range(-54, 55, 12))
        g.append('<path d="%s" fill="#87724E" stroke="#161311" stroke-width=".8"/>' % posts)
    g.append('<path d="%s" fill="url(#pap-mesh)" stroke="#8A7550" stroke-width="1"/>' % poly(BLANKET_MAP, True))
    br = rot_rect(S_X, -26, 26, -20, 20)
    g.append('<path d="%s" fill="#87724E" stroke="#5B4529" stroke-width="1.2"/>' % poly(br, True))
    planks = " ".join("M%s %s L%s %s" % (F(off(S_X + k, -20)[0]), F(off(S_X + k, -20)[1]),
                                         F(off(S_X + k, 20)[0]), F(off(S_X + k, 20)[1]))
                      for k in range(-22, 23, 6))
    g.append('<path d="%s" stroke="#6B5B3E" stroke-width="1.2"/>' % planks)
    return "\n".join(g)


BLANKET_MAP = rot_rect(S_X, -26, -12, -52, -22)


def align_layer(labels=True):
    """The alignment and its stationing - a layer, not the ground, so the
    KMZ view (imagery plus what he marked) leaves it off."""
    g = ['<path d="%s" fill="none" stroke="#BB0A10" stroke-width="2.2"/>' % CL_PATH]
    ticks, labs = [], []
    ft0 = int(math.ceil(sta_ft(S_WEST) / 100.0)) * 100
    ft = ft0
    while True:
        s = S_BAG + (ft - 220640.0) / FT_PER_PX
        if s > S_FLY1:
            break
        a, b, c = off(s, -12), off(s, 12), off(s, -28)
        ticks.append("M%s %s L%s %s" % (F(a[0]), F(a[1]), F(b[0]), F(b[1])))
        labs.append((c, sta_text(ft, 100)))
        ft += 100
    g.append('<path d="%s" stroke="#161311" stroke-width="2.2"/>' % " ".join(ticks))
    if labels:
        g.append('<g font-family="IBM Plex Mono, monospace" font-size="11" letter-spacing=".66" fill="#242020" text-anchor="middle">%s</g>'
                 % "".join('<text x="%s" y="%s">%s</text>' % (F(c[0]), F(c[1] + 4), t) for c, t in labs))
    return "\n".join(g), labs


ALIGN_SVG, STA_LABELS = align_layer()
ALIGN_NOLAB, _ = align_layer(labels=False)

# ============================================================ the video frames
# Drawn in the player's frame, x 28-708 y 50-433, looking ahead down the line.
def xL(y):
    return VP[0] - 198.0 * (y - VP[1]) / (BOT - VP[1])


def xR(y):
    return VP[0] + 198.0 * (y - VP[1]) / (BOT - VP[1])


SKY = ('<rect x="28" y="50" width="680" height="383" fill="#7F9A24"/>'
       '<rect x="28" y="50" width="680" height="26" fill="#CFE0F8"/>'
       '<path d="M28 92 L28 78 Q52 66 78 76 Q104 64 132 75 Q160 65 188 75 Q216 64 244 75 Q272 66 300 75 '
       'Q328 64 356 75 Q384 66 412 75 Q440 64 468 75 Q496 66 524 75 Q552 64 580 75 Q608 66 636 75 '
       'Q664 64 708 74 L708 92 Z" fill="#4B6006"/>')
ROWP = ('<path d="M170 433 L363 88 L373 88 L566 433 Z" fill="#CFBC99"/>'
        '<path d="M196 433 L365 90 L367 90 L252 433 Z" fill="#B9A98D"/>'
        '<path d="M338 433 L369 90 L370 90 L356 433 Z" fill="#2A2320"/>'
        '<path d="M170 433 L366 88 M566 433 L370 88" fill="none" stroke="#161311" stroke-width="1.4" opacity=".6"/>')


# ---- the world the camera moves through ----
# Everything below the treeline is drawn by distance, so the same scene is
# the player's frames and the overlay's clip, playing or paused.
Y_TOP, Y_BOT = 92.0, 900.0          # nothing on the ground shows above the treeline
D_EPS = KG / (Y_BOT - HOR)          # nearer than this is under the camera
S_MAX = 4.0
D_FADE0, D_FADE1 = 1100.0, 760.0    # far off, things come out of the haze


def F4(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def fade(d):
    return max(0.0, min(1.0, (D_FADE0 - d) / (D_FADE0 - D_FADE1)))


def y_at(d):
    return Y_BOT if d <= D_EPS else min(Y_BOT, HOR + KG / d)


def pos_at(cam, y):
    """The place on the line that a frame drawn from `cam` shows at height y."""
    return cam + KG / (y - HOR)


def xRe(y):     # the right-of-way's edges as ROWP draws them
    return 373.0 + 193.0 * (y - 88.0) / 345.0


def xLe(y):
    return 363.0 - 193.0 * (y - 88.0) / 345.0


# the standing crop (from the map) and the crossing's bands (from how the
# crossing frame draws them: the bank growth, and the water)
CROP = (s_at_x(150), s_at_x(500))
VEG = (pos_at(CAM_B, 292.0), pos_at(CAM_B, 214.0))
STREAM = (pos_at(CAM_B, 263.0), pos_at(CAM_B, 239.0))

# things standing at one distance, each drawn once where its paused frame had
# it: (id, the height it is drawn at, the camera it is drawn from, how far it
# reaches from the vanishing point in that drawing)
CARDS = [("sh", 250.0, CAM_B, 380), ("nf", NEAR_Y, CAM_B, 250), ("ff", FAR_Y, CAM_B, 150),
         ("bl", 280.0, CAM_B, 230), ("br", 254.0, CAM_B, 210), ("bag", BAG_Y, CAM_A, 330)]


def card_defs():
    d = {}
    # 01:12 - a filter bag out in the standing crop past the LOD flagging, the
    # bell hole it is dewatering, the pump, and the hose out to it
    d["bag"] = ('<ellipse cx="452" cy="358" rx="36" ry="11" fill="#2A2320"/><ellipse cx="452" cy="358" rx="26" ry="7" fill="#5083E2"/>'
                '<rect x="480" y="330" width="22" height="14" rx="2" fill="#F0A53A" stroke="#161311" stroke-width="1.4"/>'
                '<path d="M500 336 C536 334 562 312 598 299" fill="none" stroke="#161311" stroke-width="4" stroke-linecap="round"/>'
                '<ellipse cx="620" cy="298" rx="58" ry="17" fill="#3F4A1E" opacity=".5"/>'
                '<path d="M588 284 Q620 278 652 283 Q660 292 655 302 Q620 309 590 304 Q581 294 588 284 Z" fill="#C9B48A" stroke="#8A7550" stroke-width="1.6"/>'
                '<path d="M596 292 Q622 288 648 291" fill="none" stroke="#8A7550" stroke-width="1.2"/>')
    # 02:31 - the stream crossing: silt fence on both banks, a blanket on the
    # near bank, the mat bridge
    d["sh"] = '<path d="M-6000 250 H6000" fill="none" stroke="#8FB2E8" stroke-width="2.4" stroke-dasharray="14 18"/>'
    for key, y, hgt, step in (("nf", NEAR_Y, 11, 40), ("ff", FAR_Y, 6, 24)):
        a, b = xL(y), xR(y)
        xs = [a + i * step for i in range(int((b - a) / step) + 1)] + [b]
        d[key] = ('<path d="M%s %s L%s %s L%s %s L%s %s Z" fill="#242020"/>'
                  % (F(a), F(y - hgt), F(b), F(y - hgt - 1), F(b), F(y - .5), F(a), F(y))
                  + '<path d="%s" fill="none" stroke="#87724E" stroke-width="%s"/>'
                  % (" ".join("M%s %s V%s" % (F(x), F(y), F(y - hgt - 3)) for x in xs), "2.2" if hgt > 8 else "1.6"))
    d["bl"] = '<path d="M256 292 L322 292 L330 268 L266 268 Z" fill="url(#pap-mesh)" stroke="#8A7550" stroke-width="1.2"/>'
    planks = []
    for y in range(226, 286, 7):
        t = (286 - y) / 64.0
        planks.append("M%s %s L%s %s" % (F(332 + 12 * t), y, F(404 - 12 * t), y))
    d["br"] = ('<path d="M332 286 L404 286 L392 222 L344 222 Z" fill="#87724E" stroke="#5B4529" stroke-width="1.4"/>'
               '<path d="%s" stroke="#6B5B3E" stroke-width="1.3"/>' % " ".join(planks))
    return d


def band_rect(cls, fill):
    return '<rect class="%s" x="-400" y="0" width="1800" height="1" fill="%s"/>' % (cls, fill)


ROWS_D = " ".join("M%s %s L368 86" % (F(368 + (xb - 368) * (Y_BOT - HOR) / (BOT - HOR)), F(Y_BOT))
                  for xb in range(584, 1400, 26))


def world(p):
    """The ground things for the player (p) or the overlay's clip (o)."""
    g = ['<g clip-path="url(#pap-gclip)">']
    # the crop: its rows run with the line, so they never move; what moves is
    # where the field begins and ends, which two covers of plain grass mark
    g.append('<g clip-path="url(#pap-rclip)"><path d="M-400 90 H1400 V%s H-400 Z" fill="#8CA637"/>' % F(Y_BOT + 50)
             + '<path d="%s" fill="none" stroke="#4B6006" stroke-width="4" opacity=".8"/>' % ROWS_D
             + band_rect("pap-a-%sct" % p, "#7F9A24") + band_rect("pap-a-%scb" % p, "#7F9A24") + '</g>')
    g.append('<g clip-path="url(#pap-oclip)" opacity=".75">%s</g>' % band_rect("pap-a-%sveg" % p, "#4B6006"))
    g.append(band_rect("pap-a-%sstr" % p, "#5083E2"))
    for key in ("sh", "nf", "ff", "bl", "br", "bag"):
        g.append('<g class="pap-a-%s%s"><use href="#pap-c-%s"/></g>' % (p, key, key))
    g.append('</g>')
    return "".join(g)


# ---- the stakes: pairs every 100 ft along both edges ----
D_NEAR = KG / ((BOT - HOR) * 1.12)          # a pair this close is out of the bottom of the frame
D_FAR = D_NEAR + SLOTS * SPACING
LOOP = SLOTS * P_LOOP


def pair_def():
    out = []
    for side, x in ((1, xR(BOT) + 7), (-1, xL(BOT) - 7)):
        out.append('<path d="M%s 433 L%s 433 L%s 403 L%s 403 Z" fill="#DAC68A" stroke="#161311" stroke-width=".6"/>'
                   '<path d="M%s 403 l%s 5 l%s 5 z" fill="#BB0A10"/>'
                   % (F(x - 3), F(x + 3), F(x + 2.1), F(x - 2.1), F(x), F(side * 12), F(-side * 12)))
    return "".join(out)


def pair_state(u):
    d = D_FAR - u * (D_FAR - D_NEAR)
    s = KG / ((BOT - HOR) * d)
    op = max(0.0, min(1.0, (D_FAR - d) / (0.8 * SPACING)))
    return s, op


def pair_xf(s, op):
    return "opacity:%s;transform:translate(%spx,%spx) scale(%s)" % (F(op), F(VP[0] * (1 - s)), F(VP[1] * (1 - s)), F4(s))


def drift_pairs():
    return "".join('<g class="pap-drift" style="animation-delay:%ss"><use href="#pap-pair"/></g>' % F4(-k * P_LOOP)
                   for k in range(SLOTS))


def static_pairs(t):
    """The pairs exactly where the moving ones are at time t."""
    out = []
    for k in range(SLOTS):
        s, op = pair_state(((t + k * P_LOOP) % LOOP) / LOOP)
        if op > 0:
            out.append('<use href="#pap-pair" opacity="%s" transform="translate(%s,%s) scale(%s)"/>'
                       % (F(op), F(VP[0] * (1 - s)), F(VP[1] * (1 - s)), F4(s)))
    return "".join(out)


NEAR_V = [(xL(NEAR_Y) + 2, NEAR_Y), (330, NEAR_Y - .3), (410, NEAR_Y - .6), (xR(NEAR_Y) - 2, NEAR_Y - .5)]
FAR_V = [(xL(FAR_Y) + 2, FAR_Y), (368, FAR_Y - .4), (xR(FAR_Y) - 2, FAR_Y - .6)]
BLK_V = [(256, 292), (322, 292), (330, 268), (266, 268)]
BAG_V = (620, 293)


# ---- turning distance into keyframes ----
def decimate(ts, vals, tols):
    """Keep only the samples linear interpolation cannot do without."""
    def fits(i, j):
        for m in range(i + 1, j):
            f = (ts[m] - ts[i]) / (ts[j] - ts[i])
            for c, tol in enumerate(tols):
                if abs(vals[i][c] + (vals[j][c] - vals[i][c]) * f - vals[m][c]) > tol:
                    return False
        return True
    keep, i, n = [0], 0, len(ts)
    while i < n - 1:
        j = i + 1
        while j + 1 < n and fits(i, j + 1):
            j += 1
        keep.append(j)
        i = j
    return keep


def track(cls, cam, wins, fn, tols, css, origin=None):
    pts = []
    for a, b in wins:
        n = max(2, int(math.ceil((b - a) / 0.02)))
        ts = [a + (b - a) * i / n for i in range(n + 1)]
        vals = [fn(cam(tt)) for tt in ts]
        pts += [(ts[i], vals[i]) for i in decimate(ts, vals, tols)]
    stops = []
    for tt, v in pts:
        if stops and tt - stops[-1][0] < 1e-6:
            continue
        stops.append((tt, css(v)))
    kf(cls, stops, timing="linear", origin=origin)


def card_fn(pos, d_ref):
    def fn(c):
        d = pos - c
        if d <= d_ref / S_MAX:
            return (S_MAX, 0.0)
        # out in the haze nothing shows, so nothing needs to move
        return (d_ref / min(d, D_FADE0), fade(d))
    return fn


def card_css(v):
    s, op = v
    return "opacity:%s;transform:translate(%spx,%spx) scale(%s)" % (F(op), F(VP[0] * (1 - s)), F(VP[1] * (1 - s)), F4(s))


def band_fn(near, far):
    def fn(c):
        dn, dfar = near - c, far - c
        if dfar <= D_EPS:
            return (Y_BOT, 0.0, 0.0)
        yf, yn = y_at(dfar), y_at(dn)
        return (yf, yn - yf, fade(max(dn, 0.0)))
    return fn


def band_css(v):
    return "opacity:%s;transform:translate(0px,%spx) scale(1,%s)" % (F(v[2]), F(v[0]), F(v[1]))


def cover_top(c):      # plain grass from the treeline down to where the crop ends
    yf = y_at(CROP[1] - c)
    return (Y_TOP, max(0.0, yf - Y_TOP))


def cover_bot(c):      # and from where it begins down past the bottom
    y0 = max(Y_TOP, y_at(CROP[0] - c))
    return (y0, Y_BOT + 60 - y0)


def cover_css(v):
    return "transform:translate(0px,%spx) scale(1,%s)" % (F(v[0]), F(v[1]))


def world_css(p, cam, wins):
    px = 0.5        # how far off the true path a keyframe may let anything drift
    for key, y_ref, cam0, reach in CARDS:
        track("pap-a-%s%s" % (p, key), cam, wins, card_fn(pos_at(cam0, y_ref), KG / (y_ref - HOR)),
              (px / reach, 0.05), card_css)
    track("pap-a-%sveg" % p, cam, wins, band_fn(*VEG), (px, px, 0.05), band_css)
    track("pap-a-%sstr" % p, cam, wins, band_fn(*STREAM), (px, px, 0.05), band_css)
    track("pap-a-%sct" % p, cam, wins, cover_top, (px, px), cover_css)
    track("pap-a-%scb" % p, cam, wins, cover_bot, (px, px), cover_css)


def drift_css():
    n = 600
    ts = [LOOP * i / n for i in range(n + 1)]
    vals = [pair_state(i / float(n)) for i in range(n + 1)]
    keep = decimate(ts, vals, (0.35 / 300.0, 0.03))
    frames = "".join("%s%%{%s}" % ((("%.3f" % (ts[i] / LOOP * 100)).rstrip("0").rstrip(".") or "0"), pair_xf(*vals[i]))
                     for i in keep)
    CSS.append(".pap-scope .pap-drift{animation:pap-drift %ss linear infinite both;transform-box:view-box;transform-origin:0 0;}\n"
               "@keyframes pap-drift{%s}" % (F4(LOOP), frames))


# ---- the overlay's clip: where it is, every few tenths of a second ----
MM_K, MM_CX, MM_CY = 1.7, 200.5, 460.0


def heading(s):
    _, _, tx, ty = at_s(s)
    return (90.0 + math.degrees(math.atan2(ty, tx))) % 360.0


H0 = heading(cam_overlay(OV_T0))
OV_STEPS = []
_t = OV_T0
while _t < OV_T1 - 0.05:
    OV_STEPS.append((_t, cam_overlay(_t + 0.2)))
    _t += 0.4


def build():
    CSS.clear()
    t = T
    drift_css()
    # ---------------------------------------------------------- stage
    # ---------------------------------------------------------- beat 1: the throw
    kf("pap-a-fig", [(0.3, "opacity:0;transform:translateY(80px)"), (1.6, "opacity:1;transform:none"),
                     (10.0, "opacity:1;transform:none"), (11.2, "opacity:0;transform:translateY(10px)")])
    kf("pap-a-dip", [(2.2, "transform:none"), (3.3, "transform:translateY(6px)"),
                     (3.8, "transform:translateY(-4px)"), (t["rel"], "transform:none")])
    kf("pap-a-arm", [(2.2, "transform:rotate(0deg)"), (3.3, "transform:rotate(24deg)"),
                     (t["rel"], "transform:rotate(-150deg)"), (4.4, "transform:rotate(-168deg)"),
                     (5.2, "transform:rotate(-150deg)")])
    kf("pap-a-held", [(t["rel"] - 0.02, "opacity:1"), (t["rel"], "opacity:0")])
    kf("pap-a-eyes", [(4.2, "transform:none"), (4.9, "transform:translate(1.5px,-3px)")])
    # a parabola from the hand to the top of the throw, sampled at equal times
    x0, y0, x1, y1 = 360.9, 332.2, 590.0, 130.0
    v = 2 * (y0 - y1)
    toss = [(t["rel"] - 0.02, "opacity:0;transform:translate(%spx,%spx) rotate(-150deg) scale(1.05)" % (F(x0), F(y0)))]
    for i in range(5):
        u = i / 4.0
        x = x0 + (x1 - x0) * u
        y = y0 - v * u + (v / 2) * u * u
        r = -150 - 570 * u
        toss.append((t["rel"] + (t["apex"] - t["rel"]) * u,
                     "opacity:1;transform:translate(%spx,%spx) rotate(%sdeg) scale(1.05)" % (F(x), F(y), F(r))))
    toss += [(7.8, "opacity:1;transform:translate(590px,122px) rotate(-720deg) scale(1.05)"),
             (9.5, "opacity:1;transform:translate(598px,126px) rotate(-720deg) scale(1.05)"),
             (11.0, "opacity:0;transform:translate(720px,20px) rotate(-720deg) scale(.4)")]
    kf("pap-a-toss", toss, base="opacity:0;", timing="linear")
    kf("pap-a-unfold", [(t["apex"], "opacity:0;transform:scale(.05,.4)"), (t["apex"] + 0.35, "opacity:1;transform:scale(1.15,1.05)"),
                        (t["apex"] + 0.7, "opacity:1;transform:none")], base="opacity:0;", origin="0px -24px")
    kf("pap-a-pop", [(t["apex"] - 0.05, "opacity:0;transform:scale(.2)"), (t["apex"] + 0.2, "opacity:1;transform:scale(1)"),
                     (t["apex"] + 0.9, "opacity:0;transform:scale(2.2)")], base="opacity:0;", origin="590px 130px")
    vis("pap-a-recon", 6.6, None, fade=0.3)
    vis("pap-a-cone", 6.9, 9.3, fade=0.5, fade_out=0.6)

    # ---------------------------------------------------------- beat 2: the flight
    kf("pap-a-world", [(t["tilt0"], "transform:none;opacity:1"),
                       (t["tilt1"], "transform:translate(0px,26px) scale(1.02,.44);opacity:1"),
                       ((t["tilt2"], t["map_out"]), "transform:none;opacity:1"),
                       (t["map_out"] + 1.0, "transform:none;opacity:0")], origin="500px 290px")
    kf("pap-a-side", [(10.4, "opacity:1"), (11.8, "opacity:0")], timing="linear")
    kf("pap-a-map", [(11.0, "opacity:0"), (12.4, "opacity:1")], base="opacity:0;", timing="linear")
    fly = [(12.2, "opacity:0;transform:translate(%spx,%spx) scale(1.6)" % tuple(F(v) for v in at_s(S_FLY0)[:2]))]
    n = 16
    for i in range(n + 1):
        u = i / float(n)
        x, y = at_s(S_FLY0 + (S_FLY1 - S_FLY0) * u)[:2]
        fly.append((FLY_T0 + (FLY_T1 - FLY_T0) * u, "opacity:1;transform:translate(%spx,%spx) scale(1)" % (F(x), F(y))))
    fly.append((FLY_T1 + 0.05, "opacity:0;transform:translate(%spx,%spx) scale(1)" % tuple(F(v) for v in at_s(S_FLY1)[:2])))
    kf("pap-a-drone2", fly, base="opacity:0;", timing="linear")
    draw("pap-a-track", FLY_T0, FLY_T1)
    vis("pap-a-hud", 12.4, 23.6, fade=0.5, fade_out=0.6)
    tcs = [0.0, 0.17, 0.34, 0.51, 0.68, 0.85]
    for i, u in enumerate(tcs):
        on = FLY_T0 + (FLY_T1 - FLY_T0) * u
        offt = FLY_T0 + (FLY_T1 - FLY_T0) * (tcs[i + 1] if i + 1 < len(tcs) else 1.0)
        steps_on("pap-a-rec%d" % i, [(on, offt)])
    steps_on("pap-a-recon2", [(0.1, FLY_T1)], base_hidden=False)
    steps_on("pap-a-saved", [(FLY_T1, None)])

    # ---------------------------------------------------------- beat 3: later, at the truck
    kf("pap-a-truck", [(t["truck"], "opacity:0;transform:translateY(110px)"), (t["truck"] + 1.6, "opacity:1;transform:none"),
                       (28.8, "opacity:1;transform:none"), (29.4, "opacity:0;transform:none")], base="opacity:0;")
    kf("pap-a-lap", [(t["lap"], "opacity:0;transform:translateX(560px)"), (t["lap"] + 0.5, "opacity:1;transform:translateX(380px)"),
                     (t["lap"] + 1.8, "opacity:1;transform:none"), (28.8, "opacity:1;transform:none"),
                     (29.4, "opacity:0;transform:none")], base="opacity:0;")
    vis("pap-a-chip1", 24.6, 28.8, fade=0.6, fade_out=0.5, move="translateY(-8px)")
    kf("pap-a-lcur", [(25.6, "opacity:0;transform:translate(700px,300px)"), (26.0, "opacity:1;transform:translate(700px,300px)"),
                      (t["click_open"], "opacity:1;transform:translate(799px,158px)"),
                      (27.1, "opacity:1;transform:translate(799px,158px)"), (27.4, "opacity:0;transform:translate(799px,158px)")],
       base="opacity:0;", timing="linear")
    vis("pap-a-lopen", t["click_open"], t["click_open"] + 0.35, fade=0.05, fade_out=0.2)

    # ---------------------------------------------------------- beat 4: the player
    small = "translate(449.38px,98.64px) scale(.40123)"
    kf("pap-a-zoom", [(t["player_small"] - 0.1, "opacity:0;transform:%s" % small), (t["player_small"] + 0.1, "opacity:1;transform:%s" % small),
                      (t["zoom0"], "opacity:1;transform:%s" % small), (t["zoom1"], "opacity:1;transform:none"),
                      (t["player_out"], "opacity:1;transform:none"), (t["player_out"] + 1.2, "opacity:0;transform:scale(.97)")],
       base="opacity:0;")
    playing = [(t["play1"], t["pauseA"]), (t["play2"], t["pauseB"])]
    # the clip: the ground comes toward the camera while it plays and holds
    # still while it is paused; the stakes go by on their loop while it plays
    # and stand where the loop left them while it is paused
    world_css("p", cam_player, playing)
    steps_on("pap-a-pdrift", playing)
    steps_on("pap-a-psP", [(0.1, t["play1"])], base_hidden=False)
    steps_on("pap-a-psA", [(t["pauseA"], t["play2"])])
    steps_on("pap-a-psB", [(t["pauseB"], None)])
    kf("pap-a-fb", [(t["pauseB"] - 0.3, "opacity:0"), (t["pauseB"], "opacity:1")], base="opacity:0;")
    steps_on("pap-a-bpause", playing)
    steps_on("pap-a-bplay", [(0.1, t["play1"]), (t["pauseA"], t["play2"]), (t["pauseB"], None)], base_hidden=False)
    # the timecode, stepping while it plays
    codes = [(0.1, "00:00")]
    for a, b, t0, t1 in ((t["play1"], t["pauseA"], 0.0, T_A), (t["play2"], t["pauseB"], T_A, T_B)):
        for k in (1, 2, 3):
            codes.append((a + (b - a) * k / 3.0, mmss(t0 + (t1 - t0) * k / 3.0)))
    del TC[:]
    for i, (on, txt) in enumerate(codes):
        offt = codes[i + 1][0] if i + 1 < len(codes) else None
        steps_on("pap-a-tc%d" % i, [(on, offt)], base_hidden=(i > 0))
        TC.append(("pap-a-tc%d" % i, txt))
    kx1 = 502.0 * T_A / CLIP_S
    kx2 = 502.0 * T_B / CLIP_S
    kf("pap-a-knob", [(t["play1"], "transform:none"), (t["pauseA"], "transform:translateX(%spx)" % F(kx1)),
                      (t["play2"], "transform:translateX(%spx)" % F(kx1)), (t["pauseB"], "transform:translateX(%spx)" % F(kx2))],
       timing="linear")
    kf("pap-a-played", [(t["play1"], "transform:scaleX(0)"), (t["pauseA"], "transform:scaleX(%s)" % F(T_A / CLIP_S)),
                        (t["play2"], "transform:scaleX(%s)" % F(T_A / CLIP_S)), (t["pauseB"], "transform:scaleX(%s)" % F(T_B / CLIP_S))],
       timing="linear", origin="110px 457px")
    # class selections
    steps_on("pap-a-sel6", [(t["pick_bag"], t["pick_fence"])])
    steps_on("pap-a-sel0", [(t["pick_fence"], t["pick_blk"])])
    steps_on("pap-a-sel2", [(t["pick_blk"], None)])
    # marks on the frame
    vis("pap-a-ma", t["click_bag"], t["play2"], fade=0.15, fade_out=0.1)   # drawn on one frame
    for cls, a, b in (("pap-a-n1", t["n1"], t["n2"]), ("pap-a-n2", t["n2"], t["n3"]), ("pap-a-n3", t["n3"], t["n4"]),
                      ("pap-a-g1", t["f1"], t["f2"]), ("pap-a-g2", t["f2"], t["f3"]),
                      ("pap-a-k1", t["b1"], t["b2"]), ("pap-a-k2", t["b2"], t["b3"]), ("pap-a-k3", t["b3"], t["b4"]),
                      ("pap-a-k4", t["b4"], t["b_close"])):
        draw(cls, a, b)
    for cls, a in (("pap-a-nv1", t["n1"]), ("pap-a-nv2", t["n2"]), ("pap-a-nv3", t["n3"]), ("pap-a-nv4", t["n4"]),
                   ("pap-a-gv1", t["f1"]), ("pap-a-gv2", t["f2"]), ("pap-a-gv3", t["f3"]),
                   ("pap-a-kv1", t["b1"]), ("pap-a-kv2", t["b2"]), ("pap-a-kv3", t["b3"]), ("pap-a-kv4", t["b4"])):
        vis(cls, a, fade=0.12)
    vis("pap-a-kfill", t["b_close"], fade=0.4)
    # the marks list
    for cls, a in (("pap-a-r1", t["click_bag"] + 0.4), ("pap-a-r2", t["n_done"] + 0.2),
                   ("pap-a-r3", t["f_done"] + 0.2), ("pap-a-r4", t["b_close"] + 0.4)):
        vis(cls, a, fade=0.3, move="translateX(-8px)")
    vis("pap-a-savebtn", t["save"], t["save"] + 0.45, fade=0.05, fade_out=0.3)
    vis("pap-a-saved2", t["save"] + 0.3, fade=0.4)
    # the pointer: every waypoint is a click or a move, and it moves at an even pace
    cur = [(34.0, 500, 380, 0), (34.3, 500, 380, 1), (35.0, 800, 239, 1), (t["pick_bag"], 800, 239, 1),
           (36.4, BAG_V[0], BAG_V[1], 1), (38.6, BAG_V[0], BAG_V[1], 1), (39.2, 62, 457, 1), (t["play2"], 62, 457, 1),
           (40.2, 62, 457, 1), (40.5, 62, 457, 0), (t["pauseB"] + 0.05, 300, 380, 0), (t["pauseB"] + 0.35, 300, 380, 1),
           (43.8, 800, 107, 1), (t["pick_fence"], 800, 107, 1)]
    cur += [(tt, x, y, 1) for tt, (x, y) in zip((t["n1"], t["n2"], t["n3"], t["n4"], t["n_done"]), NEAR_V + [NEAR_V[-1]])]
    cur += [(tt, x, y, 1) for tt, (x, y) in zip((t["f1"], t["f2"], t["f3"], t["f_done"]), FAR_V + [FAR_V[-1]])]
    cur += [(52.2, 800, 151, 1), (t["pick_blk"], 800, 151, 1)]
    cur += [(tt, x, y, 1) for tt, (x, y) in zip((t["b1"], t["b2"], t["b3"], t["b4"], t["b_close"]), BLK_V + [BLK_V[0]])]
    cur += [(57.4, 848, 490, 1), (t["save"], 848, 490, 1), (59.2, 848, 490, 1), (59.6, 848, 490, 0)]
    kf("pap-a-pcur", [(tt, "opacity:%d;transform:translate(%spx,%spx)" % (o, F(x), F(y))) for tt, x, y, o in cur],
       base="opacity:0;", timing="linear")

    # ---------------------------------------------------------- beat 5: the overlay
    vis("pap-a-chip2", 60.4, t["ov_out"], fade=0.6, fade_out=0.5, move="translateY(-8px)")
    vis("pap-a-ov", t["ov_in"], t["ov_out"], fade=0.8, fade_out=0.8)
    # the clip plays from 00:00 at the player's speed and does not slow down:
    # Chris, 2026-09-26, "I don't know why the overlay video file moves so slow
    # at the end" - it had been one still frame creeping 14% larger over ten
    # seconds while the station ticked four times
    ov_win = [(OV_T0, OV_T1)]
    world_css("o", cam_overlay, ov_win)

    def mm(c):
        x, y = at_s(c)[:2]
        return (MM_CX - MM_K * x, MM_CY - MM_K * y, heading(c))
    track("pap-a-mm", cam_overlay, ov_win, mm, (0.3, 0.3, 0.2),
          lambda v: "transform:translate(%spx,%spx) scale(%s)" % (F(v[0]), F(v[1]), F(MM_K)))
    track("pap-a-mcone", cam_overlay, ov_win, mm, (9, 9, 0.2),
          lambda v: "transform:rotate(%sdeg)" % F(v[2] - H0), origin="%spx %spx" % (F(MM_CX), F(MM_CY)))
    track("pap-a-ring", cam_overlay, ov_win, mm, (9, 9, 0.2),
          lambda v: "transform:rotate(%sdeg)" % F(-v[2]), origin="861.7px 365.9px")
    for i, (on, _c) in enumerate(OV_STEPS):
        offt = OV_STEPS[i + 1][0] if i + 1 < len(OV_STEPS) else None
        steps_on("pap-a-q%d" % i, [(on if i else 0.1, offt)], base_hidden=(i > 0))
    track("pap-a-ovknob", cam_overlay, ov_win, lambda c: (880.0 * clip_time(c) / CLIP_S,), (0.3,),
          lambda v: "transform:translateX(%spx)" % F(v[0]))

    # ---------------------------------------------------------- beat 6: the KMZ
    vis("pap-a-chip3", 71.2, fade=0.6, move="translateY(-8px)")
    vis("pap-a-ge", t["ge_in"], fade=0.8, move="translateY(10px)")
    for i in range(6):
        vis("pap-a-t%d" % i, 72.4 + 0.22 * i, fade=0.3, move="translateX(-6px)")
    draw("pap-a-gl", t["marks"], t["marks"] + 1.0, timing="cubic-bezier(.4,0,.2,1)")
    vis("pap-a-gp", t["marks"] + 0.8, fade=0.6)
    kf("pap-a-gb", [(t["marks"] + 1.2, "opacity:0;transform:scale(.3)"), (t["marks"] + 1.5, "opacity:1;transform:scale(1.25)"),
                    (t["marks"] + 1.7, "opacity:1;transform:none")], base="opacity:0;", origin="%spx %spx" % (F(BAG[0]), F(BAG[1])))
    vis("pap-a-glab", t["marks"] + 1.6, fade=0.4)
    kf("pap-a-gcur", [(75.8, "opacity:0;transform:translate(%spx,%spx)" % (F(BAG_S[0] + 90), F(BAG_S[1] + 70))),
                      (76.1, "opacity:1;transform:translate(%spx,%spx)" % (F(BAG_S[0] + 90), F(BAG_S[1] + 70))),
                      (t["gclick"], "opacity:1;transform:translate(%spx,%spx)" % (F(BAG_S[0] + 2), F(BAG_S[1] + 2))),
                      (78.0, "opacity:1;transform:translate(%spx,%spx)" % (F(BAG_S[0] + 2), F(BAG_S[1] + 2))),
                      (78.5, "opacity:0;transform:translate(%spx,%spx)" % (F(BAG_S[0] + 2), F(BAG_S[1] + 2)))],
       base="opacity:0;", timing="linear")
    kf("pap-a-gring", [(t["gclick"], "opacity:0;transform:scale(.2)"), (t["gclick"] + 0.15, "opacity:.9;transform:scale(1)"),
                       (t["gclick"] + 0.8, "opacity:0;transform:scale(1.9)")], base="opacity:0;",
       origin="%spx %spx" % (F(BAG_S[0]), F(BAG_S[1])))
    kf("pap-a-gball", [(t["gclick"] + 0.1, "opacity:0;transform:scale(.05)"), (t["gclick"] + 0.2, "opacity:1;transform:scale(.05)"),
                       (t["gclick"] + 0.6, "opacity:1;transform:scale(1.04)"), (t["gclick"] + 0.8, "opacity:1;transform:none")],
       base="opacity:0;", timing="cubic-bezier(.2,1.2,.35,1)", origin="%spx %spx" % (F(BAG_S[0]), F(BAG_S[1] - 12)))

    # ---------------------------------------------------------- captions
    wins = [(0, 23.6), (23.6, 29.4), (29.4, 60.0), (60.0, 71.0), (71.0, 86.6)]
    for i, (a, b) in enumerate(wins):
        stops = []
        if a > 0:
            stops += [(a - 0.5, "opacity:.34"), (a, "opacity:1")]
        else:
            stops += [(0, "opacity:1")]
        stops += [(b - 0.5, "opacity:1"), (b, "opacity:.34")]
        kf("pap-a-st%d" % (i + 1), stops, timing="linear")
    return "\n".join(CSS)


# the KMZ view: ground scaled into the map pane
GE_X0, GE_Y0, GE_W, GE_H = 290.0, 80.0, 690.0, 482.0
_rx0, _rx1 = BAG[0] - 150, off(S_FAR, 57)[0] + 120
_ry0, _ry1 = off(S_X, -57)[1] - 150, BAG[1] + 70
GK = min(GE_W / (_rx1 - _rx0), GE_H / (_ry1 - _ry0))
GX = GE_X0 + (GE_W - GK * (_rx1 - _rx0)) / 2 - GK * _rx0
GY = GE_Y0 + (GE_H - GK * (_ry1 - _ry0)) / 2 - GK * _ry0
BAG_S = (GX + GK * BAG[0], GY + GK * BAG[1])


def svg():
    side = (HERE / "side.svg").read_text(encoding="utf-8")
    fig = (HERE / "fig.svg").read_text(encoding="utf-8")
    drone2 = (HERE / "drone2.svg").read_text(encoding="utf-8")
    truck = (HERE / "truck.svg").read_text(encoding="utf-8")
    truck = truck[:truck.index("<!-- laptop back")].rstrip()
    truck = truck.replace('<g class="cps-truck">', '<g class="pap-a-truck">', 1)
    o = []
    A = o.append
    A('<svg class="pap-svg" viewBox="0 0 1000 580" preserveAspectRatio="xMidYMid meet" role="img" aria-labelledby="pap-t pap-d" focusable="false">')
    A('<title id="pap-t">Paper Airplane: fly the right-of-way, then mark what the clip shows</title>')
    A('<desc id="pap-d">An inspector in a hi-vis vest throws his camera into the air; at the top of the throw it unfolds into a drone and starts recording. '
      'The view tilts over into a map and the drone flies the whole right-of-way, past a standing crop field and over a stream crossing, drawing its flight behind it, and the clip is saved. '
      'Later, in the truck, the clip is opened in Paper Airplane on a laptop and the player fills the picture. It plays down the right-of-way, stakes going by, and a filter bag out in the crop past the LOD flagging comes up out of the distance; it pauses when the bag is close: '
      'Filter bag is picked from the class list and one click marks it. It plays on, the bag goes by, the stream crossing comes up, and it pauses there: silt fence is picked and drawn along the near bank and again along the far bank, '
      'then an erosion control blanket on the near bank is drawn round. Each mark joins the list of marks on this clip, and the redline is saved as a KMZ. '
      'Two things come out. The clip with the overlay burned in, playing from the start: the bag and the crossing go by, with a mini-map of the corridor sliding under the camera cone, a compass, and a caption with the station and the spread, These Big Jobs - Spread I, turning over as it flies. '
      'And the KMZ opened in Google Earth: a folder of erosion control devices with the blanket, the filter bag and the two silt fences drawn on the ground where they are; '
      'the filter bag is clicked and its balloon gives the station, the class, that it was marked by hand in the viewer, when in the clip, and the mark it came from.</desc>')
    A('<defs>')
    A('<clipPath id="pap-fclip"><rect x="28" y="50" width="680" height="383"/></clipPath>')
    right = "M%s %s L1400 %s L1400 %s L%s %s Z" % (F(xRe(Y_TOP)), F(Y_TOP), F(Y_TOP), F(Y_BOT + 60), F(xRe(Y_BOT + 60)), F(Y_BOT + 60))
    left = "M%s %s L-1000 %s L-1000 %s L%s %s Z" % (F(xLe(Y_TOP)), F(Y_TOP), F(Y_TOP), F(Y_BOT + 60), F(xLe(Y_BOT + 60)), F(Y_BOT + 60))
    A('<clipPath id="pap-gclip"><rect x="-1000" y="%s" width="2400" height="%s"/></clipPath>' % (F(Y_TOP), F(Y_BOT)))
    A('<clipPath id="pap-rclip"><path d="%s"/></clipPath>' % right)
    A('<clipPath id="pap-oclip"><path d="%s"/><path d="%s"/></clipPath>' % (left, right))
    A('<clipPath id="pap-ovclip"><rect x="60" y="60" width="880" height="495"/></clipPath>')
    A('<clipPath id="pap-mmclip"><rect x="64" y="370" width="273" height="172" rx="8"/></clipPath>')
    A('<clipPath id="pap-geclip"><rect x="%s" y="%s" width="%s" height="%s"/></clipPath>' % (F(GE_X0), F(GE_Y0), F(GE_W), F(GE_H - 2)))
    A('<pattern id="pap-mesh" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
      '<rect width="6" height="6" fill="#D9C27A"/><path d="M0 0 h6 M0 0 v6" stroke="#B59A5A" stroke-width="1"/></pattern>')
    A('<pattern id="pap-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
      '<rect width="5" height="5" fill="#E8E03A"/><path d="M0 0 v5" stroke="#161311" stroke-width="2"/></pattern>')
    A('<g id="pap-ground">%s</g>' % ground())
    A('<g id="pap-align">%s</g>' % ALIGN_NOLAB)
    for key, body in card_defs().items():
        A('<g id="pap-c-%s">%s</g>' % (key, body))
    A('<g id="pap-pair">%s</g>' % pair_def())
    A('</defs>')
    A('<rect x="0" y="0" width="1000" height="580" fill="#F5F1E8"/>')
    A('<g class="pap-stage">')

    # ---- beats 1-2: the world ----
    A('<g class="pap-a-world" style="transform-origin:500px 290px">')
    A(side)
    track = poly(run(S_FLY0, S_FLY1, 0, 90))
    A('<g class="pap-a-map"><use href="#pap-ground"/>%s' % ALIGN_SVG)
    A('<path class="pap-a-track" pathLength="100" stroke="#161311" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round" opacity=".35" d="%s"/>' % track)
    A('<path class="pap-a-track" pathLength="100" stroke="#F7F2E6" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" d="%s"/>' % track)
    A('</g></g>')
    A(fig)
    A(drone2)
    # HUD: recording, then the clip saved
    A('<g class="pap-a-hud" font-family="IBM Plex Mono, monospace" font-size="14" fill="#F2ECDF">'
      '<rect x="770" y="22" width="206" height="32" rx="16" fill="#161311" opacity=".82"/>'
      '<g class="pap-a-recon2"><circle class="pap-blink" cx="790" cy="38" r="5.5" fill="#E8322A"/><text x="804" y="43">REC</text>')
    for i, u in enumerate([0.0, 0.17, 0.34, 0.51, 0.68, 0.85]):
        A('<text class="pap-a-rec%d" x="840" y="43">%s</text>' % (i, mmss(CLIP_S * u)))
    A('</g><g class="pap-a-saved"><rect x="784" y="32" width="12" height="12" fill="#F2ECDF"/>'
      '<text x="804" y="43">DJI_0042.MP4 %s</text></g></g>' % mmss(CLIP_S))

    # ---- beat 3: the truck ----
    A(truck)
    A('<g class="pap-a-lap">')
    A('<path d="M441 66 L869 66 L873 374 L437 372 Z" fill="#161311" opacity=".18"/>'
      '<rect x="436" y="61" width="428" height="308" rx="7" fill="#161311"/>'
      '<rect x="455" y="80" width="390" height="270" fill="#F2ECDF"/>'
      '<rect x="455" y="80" width="390" height="16" fill="#161311"/>'
      '<text x="463" y="91.5" font-family="IBM Plex Mono, monospace" font-size="8.5" fill="#F2ECDF">Construction Paper</text>'
      '<g font-family="IBM Plex Mono, monospace" font-size="7.5" letter-spacing=".5" fill="#8A8078">'
      '<text x="463" y="112">RENAME</text><text x="505" y="112">MARCO POLOCATOR</text>'
      '<text x="584" y="112" fill="#161311" font-weight="700">PAPER AIRPLANE</text>'
      '<text x="660" y="112">PHOTO KMZ</text><text x="712" y="112">GIS TOOLS</text></g>'
      '<path d="M455 117 H845" stroke="#D6C9AE" stroke-width="1"/><path d="M584 117 H654" stroke="#5083E2" stroke-width="2"/>'
      '<text x="470" y="138" font-family="IBM Plex Sans, sans-serif" font-size="10" fill="#161311">Drone clip</text>'
      '<rect x="470" y="146" width="290" height="24" fill="#FFFFFF" stroke="#8A8078" stroke-width="1"/>'
      '<text x="478" y="162" font-family="IBM Plex Mono, monospace" font-size="11" fill="#161311">DJI_0042.MP4</text>'
      '<rect x="768" y="146" width="62" height="24" fill="#F2ECDF" stroke="#161311" stroke-width="1.2"/>'
      '<rect class="pap-a-lopen" x="768" y="146" width="62" height="24" fill="#F0A53A" stroke="#161311" stroke-width="1.2"/>'
      '<text x="799" y="162" text-anchor="middle" font-family="IBM Plex Sans, sans-serif" font-size="11" fill="#161311">Open</text>')
    A('<rect x="451" y="76" width="398" height="6" fill="#161311"/><rect x="451" y="348" width="398" height="6" fill="#161311"/>'
      '<rect x="449" y="76" width="7" height="278" fill="#161311"/><rect x="844" y="76" width="7" height="278" fill="#161311"/>'
      '<path d="M424 369 L876 369 L906 428 L394 428 Z" fill="#242020"/>'
      '<path d="M450 380 L850 380 L872 412 L428 412 Z" fill="#3A332E"/>'
      '<path d="M598 416 L702 416 L706 424 L594 424 Z" fill="#3A332E"/>')
    A('</g>')
    A('<g class="pap-a-lcur">' + CURSOR + '</g>')
    A(chip("pap-a-chip1", "LATER, BACK AT THE TRUCK"))

    # ---- beat 4: the player ----
    A(player())

    # ---- beat 5: the overlay ----
    A(chip("pap-a-chip2", "WHAT YOU GET: THE VIDEO OVERLAY"))
    A(overlay())

    # ---- beat 6: the KMZ ----
    A(chip("pap-a-chip3", "WHAT YOU GET: THE KMZ OF EVERY MARK"))
    A(ge())
    A('</g></svg>')
    return "\n".join(o)


CURSOR = ('<path d="M0 0 L0 30 L8 23 L14 36 L20 33 L14 20 L24 19 Z" fill="#F2ECDF" stroke="#161311" '
          'stroke-width="2.5" stroke-linejoin="round"/>')


def chip(cls, text):
    w = 20 + 8.9 * len(text)
    return ('<g class="%s"><rect x="22" y="16" width="%s" height="30" fill="#161311"/>'
            '<text x="32" y="36" font-family="IBM Plex Mono, monospace" font-size="14" letter-spacing=".5" fill="#F2ECDF">%s</text></g>'
            % (cls, F(w + 4), text))


def seg(cls, a, b, extra=""):
    return ('<path class="pap-a-seg %s" pathLength="100" stroke="#BB0A10" stroke-width="3.6" stroke-linecap="round" d="M%s %s L%s %s"%s/>'
            % (cls, F(a[0]), F(a[1]), F(b[0]), F(b[1]), extra))


def vtx(cls, p, r=4.8):
    return '<circle class="%s" cx="%s" cy="%s" r="%s" fill="#F2ECDF" stroke="#BB0A10" stroke-width="2.2"/>' % (cls, F(p[0]), F(p[1]), F(r))


CLASSES = [("Silt fence", "line"), ("Straw / mulch", "area"), ("Erosion control blanket", "area"),
           ("Trench breaker", "point"), ("Sediment barrier along a mat cr…", "line"),
           ("Sediment log / wattle", "line"), ("Filter bag / dewatering bag", "point")]


def player():
    o = []
    A = o.append
    A('<g class="pap-a-zoom">')
    A('<rect x="18" y="17" width="972" height="556" fill="#161311" opacity=".18"/>')
    A('<rect x="14" y="12" width="972" height="556" fill="#F2ECDF" stroke="#161311" stroke-width="3"/>')
    A('<rect x="14" y="12" width="972" height="26" fill="#161311"/>')
    A('<text x="28" y="30" font-family="IBM Plex Mono, monospace" font-size="13" fill="#F2ECDF">Paper Airplane &#183; DJI_0042.MP4</text>')
    A('<rect x="28" y="50" width="680" height="383" fill="#161311"/>')
    A('<g clip-path="url(#pap-fclip)">')
    # the clip: one scene, the camera moving down the line
    A(SKY + ROWP + world("p"))
    A('<g class="pap-a-pdrift">%s</g>' % drift_pairs())
    for cls, at in (("pap-a-psP", T["play1"]), ("pap-a-psA", T["pauseA"]), ("pap-a-psB", T["pauseB"])):
        A('<g class="%s">%s</g>' % (cls, static_pairs(at)))
    # the bag's mark
    A('<g class="pap-a-ma"><circle cx="%s" cy="%s" r="9" fill="#BB0A10" stroke="#F2ECDF" stroke-width="3"/>'
      '<circle cx="%s" cy="%s" r="14" fill="none" stroke="#BB0A10" stroke-width="2"/></g>' % (F(BAG_V[0]), F(BAG_V[1]), F(BAG_V[0]), F(BAG_V[1])))
    # the crossing's marks
    A('<g class="pap-a-fb">')
    # fill-opacity, not opacity: the fade-in animates opacity and would override it
    A('<path class="pap-a-kfill" d="%s" fill="#BB0A10" fill-opacity=".28"/>' % poly(BLK_V, True))
    for i in range(3):
        A(seg("pap-a-n%d" % (i + 1), NEAR_V[i], NEAR_V[i + 1]))
    for i in range(2):
        A(seg("pap-a-g%d" % (i + 1), FAR_V[i], FAR_V[i + 1]))
    for i in range(4):
        A(seg("pap-a-k%d" % (i + 1), BLK_V[i], BLK_V[(i + 1) % 4]))
    for i, p in enumerate(NEAR_V):
        A(vtx("pap-a-nv%d" % (i + 1), p))
    for i, p in enumerate(FAR_V):
        A(vtx("pap-a-gv%d" % (i + 1), p, 4))
    for i, p in enumerate(BLK_V):
        A(vtx("pap-a-kv%d" % (i + 1), p))
    A('</g></g>')
    A('<rect x="28" y="50" width="680" height="383" fill="none" stroke="#161311" stroke-width="1.5"/>')
    # transport
    A('<rect x="28" y="444" width="68" height="26" fill="#F2ECDF" stroke="#161311" stroke-width="1.4"/>')
    A('<g font-family="IBM Plex Sans, sans-serif" font-size="12" fill="#161311" text-anchor="middle">'
      '<text class="pap-a-bplay" x="62" y="461">Play</text><text class="pap-a-bpause" x="62" y="461">Pause</text></g>')
    A('<path d="M110 457 H612" stroke="#161311" stroke-width="4" opacity=".2"/>')
    A('<path class="pap-a-played" d="M110 457 H612" stroke="#F0A53A" stroke-width="4"/>')
    A('<g class="pap-a-knob"><circle cx="110" cy="457" r="6.5" fill="#F0A53A" stroke="#161311" stroke-width="1.6"/></g>')
    A('<g font-family="IBM Plex Mono, monospace" font-size="12" fill="#161311" text-anchor="end">')
    for cls, txt in TC:
        A('<text class="%s" x="708" y="462">%s / %s</text>' % (cls, txt, mmss(CLIP_S)))
    A('</g>')
    A('<text x="28" y="496" font-family="IBM Plex Sans, sans-serif" font-size="12" fill="#161311" opacity=".72">'
      'Camera offset measured: 2.4&#176;, from 412 samples.</text>')
    A('<text class="pap-a-saved2" x="28" y="520" font-family="IBM Plex Sans, sans-serif" font-size="12.5" font-weight="600" fill="#495F03">'
      'Saved Redline_%s.kmz &#8212; 4 marks.</text>' % SPREAD)
    # side panel
    A('<g font-family="IBM Plex Sans, sans-serif">')
    A('<text x="724" y="66" font-size="14" font-weight="600" fill="#161311">Marking</text>')
    A('<text x="724" y="84" font-size="11.5" fill="#161311" opacity=".62">Pick what you are about to mark.</text>')
    A('<rect x="724" y="94" width="248" height="158" fill="#FFFFFF" stroke="#8A8078" stroke-width="1"/>')
    for idx in (6, 0, 2):
        A('<rect class="pap-a-sel%d" x="725" y="%s" width="246" height="22" fill="#F0A53A"/>' % (idx, F(96 + 22 * idx)))
    for i, (lab, kind) in enumerate(CLASSES):
        y = 96 + 22 * i + 15
        A('<text x="732" y="%s" font-size="11.5" fill="#161311">%s</text>' % (F(y), lab))
        A('<text x="964" y="%s" font-size="11" fill="#161311" opacity=".6" text-anchor="end">%s</text>' % (F(y), kind))
    A('<rect x="724" y="262" width="11" height="11" fill="#FFFFFF" stroke="#8A8078" stroke-width="1"/>')
    A('<text x="742" y="272" font-size="11.5" fill="#161311">Show every class</text>')
    A('<text x="724" y="300" font-size="14" font-weight="600" fill="#161311">Marks on this clip</text>')
    A('<rect x="724" y="308" width="248" height="112" fill="#FFFFFF" stroke="#8A8078" stroke-width="1"/>')
    rows = [("m0001", "Filter bag / dewat…", BAG_STA), ("m0002", "Silt fence", NEAR_STA),
            ("m0003", "Silt fence", FAR_STA), ("m0004", "Erosion control bl…", BLK_STA)]
    for i, (mid, what, where) in enumerate(rows):
        y = 310 + 22 * i + 15
        A('<g class="pap-a-r%d"><text x="732" y="%s" font-family="IBM Plex Mono, monospace" font-size="11" fill="#161311" opacity=".7">%s</text>'
          '<text x="778" y="%s" font-size="11.5" fill="#161311">%s</text>'
          '<text x="964" y="%s" font-family="IBM Plex Mono, monospace" font-size="11" fill="#161311" text-anchor="end">%s</text></g>'
          % (i + 1, F(y), mid, F(y), what, F(y), where))
    A('<rect x="724" y="434" width="248" height="28" fill="#F2ECDF" stroke="#161311" stroke-width="1.2" opacity=".6"/>')
    A('<text x="848" y="452" font-size="12" fill="#161311" text-anchor="middle" opacity=".6">Teach Jane from these marks</text>')
    A('<rect x="724" y="476" width="248" height="28" fill="#F2ECDF" stroke="#161311" stroke-width="1.6"/>')
    A('<rect class="pap-a-savebtn" x="724" y="476" width="248" height="28" fill="#F0A53A" stroke="#161311" stroke-width="1.6"/>')
    A('<text x="848" y="495" font-size="12.5" font-weight="600" fill="#161311" text-anchor="middle">Save the redline (KMZ)</text>')
    A('</g>')
    A('<g class="pap-a-pcur">' + CURSOR + '</g>')
    A('</g>')
    return "\n".join(o)


def overlay():
    """The clip with the overlay burned in - Marco Polocator's layout on a
    frame of video, placed by the same fractions as his photographs."""
    o = []
    A = o.append
    A('<g class="pap-a-ov">')
    A('<rect x="60" y="60" width="880" height="495" fill="#161311"/>')
    A('<g clip-path="url(#pap-ovclip)">')
    # the clip itself: the same scene the player showed, never paused
    A('<g transform="translate(23.765,-4.706) scale(1.29412)">')
    A(SKY + ROWP + world("o") + drift_pairs())
    A('</g>')
    # mini-map, bottom left: the map slides under the drone as it flies
    k, cx, cy = MM_K, MM_CX, MM_CY
    A('<rect x="64" y="370" width="273" height="172" rx="8" fill="#5F6B3E"/>')
    A('<g clip-path="url(#pap-mmclip)"><g class="pap-a-mm">')
    A('<use href="#pap-ground"/><use href="#pap-align"/>')
    c0, c1 = cam_overlay(OV_T0), cam_overlay(OV_T1)
    A('<path d="%s" fill="none" stroke="#E8E03A" stroke-width="%s"/>' % (" ".join(poly(run(c0 - 160, c1 + 160, d, 60)) for d in (-55, 55)), F4(1 / k)))
    labs = ['<text x="%s" y="%s" text-anchor="middle">%s</text>' % (F(c[0]), F(c[1]), txt) for c, txt in STA_LABELS]
    A('<g font-family="IBM Plex Sans, sans-serif" font-size="%s" font-weight="700" fill="#FFFFFF" stroke="#161311" '
      'stroke-width="%s" paint-order="stroke">%s</g>' % (F4(10 / k), F4(2 / k), "".join(labs)))
    A('</g>')
    hd = math.radians(H0 - 90.0)
    a1, a2 = hd - math.radians(32), hd + math.radians(32)
    A('<g class="pap-a-mcone"><path d="M%s %s L%s %s L%s %s Z" fill="#E8322A" opacity=".5"/></g>'
      % (F(cx), F(cy), F(cx + 90 * math.cos(a1)), F(cy + 90 * math.sin(a1)), F(cx + 90 * math.cos(a2)), F(cy + 90 * math.sin(a2))))
    A('<circle cx="%s" cy="%s" r="4.5" fill="#E8322A" stroke="#FFFFFF" stroke-width="1.8"/>' % (F(cx), F(cy)))
    A('</g>')
    A('<rect x="64" y="370" width="273" height="22" rx="8" fill="#1A1A14" opacity=".55"/>')
    # where it is at each step: station, how far off the line, position, heading
    lat0, lon0 = 40.371884, -97.029102
    x_ref, y_ref = at_s(S_BAG)[:2]
    away = [6, 3, 5, 2, 4, 7, 3, 5, 2, 6, 4, 3]
    steps = []
    for i, (_on, c) in enumerate(OV_STEPS):
        x, y = at_s(c)[:2]
        steps.append((sta_text(sta_ft(c)), away[i % len(away)],
                      lat0 - (y - y_ref) * FT_PER_PX / 364000.0,
                      lon0 + (x - x_ref) * FT_PER_PX / (364000.0 * math.cos(math.radians(lat0))),
                      int(round(heading(c)))))
    A('<g font-family="IBM Plex Sans, sans-serif" font-weight="700" fill="#FFFFFF">'
      '<text x="72" y="385" font-size="11">N &#8593;</text>')
    for i, (st, ft, _la, _lo, _h) in enumerate(steps):
        A('<text class="pap-a-q%d" x="329" y="386" font-size="12" text-anchor="end">%s &#183; %d ft away</text>' % (i, st, ft))
    bar = 100.0 / FT_PER_PX * k
    A('<text x="%s" y="533" font-size="10.5">100 ft</text></g>' % F(74 + bar + 6))
    A('<path d="M74 530 h%s M74 525 v9 M%s 525 v9" stroke="#FFFFFF" stroke-width="1.6"/>' % (F(bar), F(74 + bar)))
    A('<rect x="64" y="370" width="273" height="172" rx="8" fill="none" stroke="#FFFFFF" stroke-width="2" opacity=".8"/>')
    # compass: the ring turns, the needle does not
    A('<circle cx="861.7" cy="365.9" r="46" fill="#FFFFFF" opacity=".3"/>'
      '<circle cx="861.7" cy="365.9" r="46" fill="none" stroke="#FFFFFF" stroke-width="2" opacity=".9"/>')
    A('<g class="pap-a-ring"><g stroke="#FFFFFF" stroke-width="1.5" opacity=".85">'
      '<path d="M861.7 323 v8 M861.7 401 v8 M819 365.9 h8 M896.4 365.9 h8"/></g>'
      '<g font-family="IBM Plex Sans, sans-serif" font-size="14.5" font-weight="700" fill="#E8322A" text-anchor="middle">'
      '<text x="861.7" y="343">N</text><text x="861.7" y="400">S</text><text x="889" y="371">E</text><text x="834.5" y="371">W</text></g></g>')
    A('<path d="M861.7 331 l8 35 l-8 11 l-8 -11 Z" fill="#E8322A"/><path d="M861.7 401 l8 -35 l-8 -11 l-8 11 Z" fill="#FFFFFF" opacity=".8"/>'
      '<circle cx="861.7" cy="365.9" r="4" fill="#FFFFFF"/>')
    A('<rect x="824" y="425" width="76" height="28" rx="8" fill="#101010" opacity=".6"/>'
      '<rect x="824" y="425" width="76" height="28" rx="8" fill="none" stroke="#FFFFFF" stroke-width="1.5" opacity=".8"/>')
    A('<g text-anchor="middle" font-family="IBM Plex Sans, sans-serif" font-size="15" font-weight="700" fill="#FFFFFF">')
    for i, (_st, _ft, _la, _lo, h) in enumerate(steps):
        A('<text class="pap-a-q%d" x="862" y="444.5">%03d&#176;M</text>' % (i, h))
    A('</g>')
    # caption, bottom right, green; the station turns over as it flies
    A('<rect x="665" y="462" width="271" height="68" rx="8" fill="#12200F" opacity=".72"/>'
      '<rect x="665" y="462" width="271" height="68" rx="8" fill="none" stroke="#8FD16A" stroke-width="1.3" opacity=".55"/>')
    A('<g font-family="IBM Plex Sans, sans-serif" font-size="12.4" fill="#8FD16A">')
    for i, (st, _ft, la, lo, h) in enumerate(steps):
        A('<g class="pap-a-q%d"><text x="676" y="481" font-size="14.5" font-weight="700">%s</text>'
          '<text x="676" y="511">%.6f  %.6f | %03d&#176;M</text></g>' % (i, st, la, lo, h))
    A('<text x="746" y="481" font-size="14.5" font-weight="700" fill="#FFFFFF">%s</text>' % SPREAD)
    A('<text x="676" y="496">STREAM_S04 DEM-EX-GA-S04</text>')
    A('<text x="676" y="525">2026-09-16</text>')
    A('</g>')
    A('</g>')
    A('<rect x="60" y="60" width="880" height="495" fill="none" stroke="#161311" stroke-width="2"/>')
    A('<path d="M60 568 H940" stroke="#161311" stroke-width="4" opacity=".2"/>')
    A('<g class="pap-a-ovknob"><circle cx="60" cy="568" r="6" fill="#F0A53A" stroke="#161311" stroke-width="1.5"/></g>')
    A('</g>')
    return "\n".join(o)


def ge():
    """The redline KMZ opened in Google Earth: the ground, the marks in the
    erosion-control style, the folder tree the program writes, one balloon."""
    o = []
    A = o.append
    k = GK
    A('<g class="pap-a-ge">')
    A('<rect x="24" y="61" width="960" height="506" fill="#161311" opacity=".18"/>')
    A('<rect x="20" y="56" width="960" height="506" fill="#F2ECDF" stroke="#161311" stroke-width="3"/>')
    A('<g clip-path="url(#pap-geclip)"><g transform="translate(%s,%s) scale(%s)"><use href="#pap-ground"/>' % (F(GX), F(GY), F(k)))
    lw, cw = 4.0 / k, 7.0 / k
    near = [off(S_NEAR, d) for d in (-54, -18, 18, 54)]
    far = [off(S_FAR, d) for d in (-54, 0, 54)]
    A('<path class="pap-a-gp" d="%s" fill="#A0C850" fill-opacity=".5" stroke="#A0C850" stroke-width="%s"/>' % (poly(BLANKET_MAP, True), F(3 / k)))
    for line in (near, far):
        A('<path class="pap-a-gl" pathLength="100" d="%s" stroke="#161311" stroke-opacity=".55" stroke-width="%s" stroke-linecap="round"/>' % (poly(line), F(cw)))
        A('<path class="pap-a-gl" pathLength="100" d="%s" stroke="#A0C850" stroke-width="%s" stroke-linecap="round"/>' % (poly(line), F(lw)))
    A('<g class="pap-a-gb"><circle cx="%s" cy="%s" r="%s" fill="#A0C850" stroke="#FFFFFF" stroke-width="%s"/>'
      '<circle cx="%s" cy="%s" r="%s" fill="none" stroke="#161311" stroke-opacity=".6" stroke-width="%s"/></g>'
      % (F(BAG[0]), F(BAG[1]), F(7 / k), F(2.4 / k), F(BAG[0]), F(BAG[1]), F(8.6 / k), F(1 / k)))
    A('</g></g>')
    A('<text class="pap-a-glab" x="%s" y="%s" font-family="IBM Plex Sans, sans-serif" font-size="12.5" font-weight="600" fill="#FFFFFF" '
      'stroke="#161311" stroke-width="3" paint-order="stroke">%s Filter bag / dewatering bag</text>' % (F(BAG_S[0] + 13), F(BAG_S[1] + 4), BAG_STA))
    # title bar and the Places tree
    A('<rect x="20" y="56" width="960" height="24" fill="#161311"/>')
    A('<text x="32" y="73" font-family="IBM Plex Mono, monospace" font-size="12.5" fill="#F2ECDF">Redline_%s.kmz</text>' % SPREAD)
    A('<rect x="21.5" y="80" width="268.5" height="480.5" fill="#F2ECDF"/><path d="M290 80 V562" stroke="#161311" stroke-width="1.5"/>')
    A('<text x="32" y="103" font-family="IBM Plex Sans, sans-serif" font-size="13" font-weight="600" fill="#161311">Places</text>')
    A('<path d="M32 111 H278" stroke="#161311" stroke-width="1" opacity=".2"/>')
    tree = [(0, True, "Redline_%s.kmz" % SPREAD), (1, True, "Redline - %s" % SPREAD), (2, True, "Erosion control devices"),
            (3, False, "Erosion control blanket (1)"), (3, False, "Filter bag / dewatering bag (1)"), (3, False, "Silt fence (2)")]
    for i, (lvl, folder, txt) in enumerate(tree):
        y = 130 + 22 * i
        x = 30 + 13 * lvl
        g = ['<g class="pap-a-t%d" font-family="IBM Plex Sans, sans-serif" font-size="11" fill="#161311">' % i]
        if folder:
            g.append('<path d="M%s %s l7 0 l-3.5 5 z" fill="#161311"/>' % (F(x), F(y - 7)))
        g.append('<rect x="%s" y="%s" width="9" height="9" fill="#FFFFFF" stroke="#8A8078" stroke-width="1"/>'
                 '<path d="M%s %s l2.2 2.4 l4 -5" fill="none" stroke="#2757B6" stroke-width="1.6"/>'
                 % (F(x + 10), F(y - 9), F(x + 11.5), F(y - 4.5)))
        if not folder:
            g.append('<rect x="%s" y="%s" width="10" height="4" fill="#A0C850"/>' % (F(x + 23), F(y - 6.5)))
        g.append('<text x="%s" y="%s">%s</text></g>' % (F(x + 37 if not folder else x + 23), F(y), txt))
        A("".join(g))
    # the click, and the balloon it opens
    A('<g class="pap-a-gring" fill="none" stroke="#FFFFFF" stroke-width="3"><circle cx="%s" cy="%s" r="16"/></g>' % (F(BAG_S[0]), F(BAG_S[1])))
    bw, bh = 346.0, 146.0
    tip = (BAG_S[0], BAG_S[1] - 12)
    bx = min(max(tip[0] - bw * 0.35, GE_X0 + 10), 972 - bw)
    by = tip[1] - 18 - bh
    rows = [("Station", BAG_STA), ("Class", "Filter bag / dewatering bag"), ("Found by", "hand, in the viewer"),
            ("In the clip at", "%.1f s" % T_A), ("Note", "[m0001, 1 frame, drawn 2026-09-16T15:02]")]
    A('<g class="pap-a-gball">')
    A('<path d="M%s %s L%s %s L%s %s Z" fill="#FFFFFF" stroke="#999999" stroke-width="1.2"/>'
      % (F(tip[0] - 9), F(by + bh - 1), F(tip[0]), F(tip[1]), F(tip[0] + 9), F(by + bh - 1)))
    A('<rect x="%s" y="%s" width="%s" height="%s" rx="4" fill="#FFFFFF" stroke="#999999" stroke-width="1.2"/>' % (F(bx), F(by), F(bw), F(bh)))
    A('<path d="M%s %s h16" stroke="#FFFFFF" stroke-width="2.6"/>' % (F(tip[0] - 8), F(by + bh)))
    A('<text x="%s" y="%s" font-family="Arial, Helvetica, sans-serif" font-size="13" font-weight="700" fill="#202020">%s Filter bag / dewatering bag</text>'
      % (F(bx + 12), F(by + 24), BAG_STA))
    A('<g font-family="Arial, Helvetica, sans-serif" font-size="11" fill="#202020">')
    for i, (kk, vv) in enumerate(rows):
        y = by + 50 + 20 * i
        A('<text x="%s" y="%s" font-weight="700">%s</text><text x="%s" y="%s">%s</text>' % (F(bx + 12), F(y), kk, F(bx + 102), F(y), vv))
    A('</g></g>')
    A('<g class="pap-a-gcur">' + CURSOR + '</g>')
    A('</g>')
    return "\n".join(o)


STATIC_CSS = r"""
/* ============================================================
   Paper Airplane (the program's FlyPaper tab until 2026-09-26).
   GENERATED by tools/paper_airplane/build.py, which says
   where every fact in the drawing comes from. Change the timing
   there, not here: each time is in seconds in that file.

   The film: the throw and the flight; LATER, at the truck, the
   clip opened and marked; then what comes out of it - the clip
   with the overlay burned in, and the redline KMZ.
   ============================================================ */
.pap-scope{
  --pap-ink:#161311; --pap-ground:#F5F1E8; --pap-red-t:#AC040C;
  --pap-mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --pap-dur:%(DUR)ss;
  margin:0; overflow:hidden;
}
.pap-stagewrap{position:relative;width:100%%;border-radius:3px;overflow:hidden;background:var(--pap-ground);}
.pap-svg{display:block;width:100%%;height:auto;}

.pap-stage{animation:pap-stage var(--pap-dur) linear infinite both;}
@keyframes pap-stage{0%%{opacity:0}%(IN)s,%(OUT)s{opacity:1}100%%{opacity:0}}

.pap-scope [class*="pap-a-"]{
  animation-duration:var(--pap-dur);
  animation-iteration-count:infinite;
  animation-fill-mode:both;
  animation-timing-function:cubic-bezier(.32,.72,.28,1);
  transform-box:view-box; transform-origin:0 0;
}

/* rotors, props and the REC light keep their own time; the stakes going by
   (.pap-drift, generated below) keep a time that divides the film exactly */
.pap-flutter{animation:pap-flutter .14s linear infinite;transform-box:fill-box;transform-origin:center;}
@keyframes pap-flutter{0%%,100%%{transform:scaleX(1)}50%%{transform:scaleX(.12)}}
.pap-prop{animation:pap-spin .28s linear infinite;transform-box:fill-box;transform-origin:center;}
@keyframes pap-spin{to{transform:rotate(360deg)}}
.pap-blink{animation:pap-blink 1s steps(1,end) infinite;}
@keyframes pap-blink{0%%{opacity:1}50%%{opacity:.15}}

/* ---- captions under the stage ---- */
.pap-steps{display:flex;gap:.5rem 1.6rem;flex-wrap:wrap;list-style:none;margin:.9rem 0 0;padding:0;
  font-family:var(--pap-mono);font-size:11px;letter-spacing:.04em;text-transform:uppercase;
  color:rgba(22,19,17,.62);}
.pap-steps li{display:flex;align-items:baseline;gap:.45rem;opacity:.34;}
.pap-steps b{font-weight:400;color:var(--pap-red-t);}
@media (max-width:40rem){ .pap-steps{font-size:10px;gap:.35rem .9rem;} }
"""

RM_CSS = r"""
/* ---- reduced motion: the finished result - the KMZ open in Google Earth
       with every mark on the ground and the filter bag's balloon open ---- */
@media (prefers-reduced-motion:reduce){
  .pap-scope *{animation:none !important;transition:none !important;}
  .pap-stage{opacity:1;}
  .pap-scope [class*="pap-a-"]{opacity:0 !important;}
  .pap-scope .pap-a-ge,.pap-scope .pap-a-chip3,.pap-scope .pap-a-gp,.pap-scope .pap-a-gb,.pap-scope .pap-a-glab,
  .pap-scope .pap-a-gball,.pap-scope .pap-a-t0,.pap-scope .pap-a-t1,.pap-scope .pap-a-t2,.pap-scope .pap-a-t3,
  .pap-scope .pap-a-t4,.pap-scope .pap-a-t5,.pap-scope .pap-a-gl,.pap-scope .pap-steps li{opacity:1 !important;transform:none !important;}
  .pap-scope .pap-a-gl{stroke-dashoffset:0 !important;}
}

/* ---- parked by site.js while scrolled off screen ---- */
.pap-scope.is-parked *{animation-play-state:paused !important;}
"""


def section():
    keyframes = build()
    static = STATIC_CSS % {"DUR": F(DUR), "IN": P(T["stage_in"]), "OUT": P(T["stage_out"])}
    body = svg()
    steps = ['<li class="pap-a-st1"><b>01</b> Fly the right-of-way</li>',
             '<li class="pap-a-st2"><b>02</b> Later, open the clip</li>',
             '<li class="pap-a-st3"><b>03</b> Pause and mark what is there</li>',
             '<li class="pap-a-st4"><b>04</b> The video, with the overlay</li>',
             '<li class="pap-a-st5"><b>05</b> A KMZ of every mark</li>']
    return ('<!-- ================= BEGIN PAPER AIRPLANE STORYBOOK ================= -->\n'
            '<section class="pap-scope" aria-label="How Paper Airplane turns a drone flight into a marked-up clip: the video with the overlay burned in, and a KMZ of every erosion control device marked on it">\n'
            '<style>' + static + "\n/* ---- the timeline, generated ---- */\n" + keyframes + "\n" + RM_CSS + '</style>\n'
            '<div class="pap-stagewrap">\n' + body + '\n</div>\n'
            '<ol class="pap-steps">\n  ' + "\n  ".join(steps) + '\n</ol>\n</section>\n')


def main():
    # keep the working copy's line endings as they were found (git stores LF)
    raw = INDEX.read_bytes()
    eol = "\r\n" if b"\r\n" in raw else "\n"
    html = raw.decode("utf-8").replace("\r\n", "\n")
    a = html.index("<!-- ================= BEGIN PAPER AIRPLANE STORYBOOK")
    b = html.index("<!-- ================= END PAPER AIRPLANE STORYBOOK")
    sec = section()
    new = html[:a] + sec + html[b:]
    INDEX.write_bytes(new.replace("\n", eol).encode("utf-8"))
    print("wrote", INDEX, "| film %ss | pause A %s (%s) | pause B %s | bag %s near %s far %s blanket %s"
          % (F(DUR), mmss(T_A), F(T_A), mmss(T_B), BAG_STA, NEAR_STA, FAR_STA, BLK_STA))
    print("camera: KG %.0f | %.1f px/s (%.0f ft/s of film) | bag first seen %.0f px off | play2 %.2f s pauseB %.2f s | section %d bytes"
          % (KG, V, V * FT_PER_PX, CAM_A + KG / (BAG_Y - HOR) - CAM_P1, T["play2"], T["pauseB"], len(sec.encode("utf-8"))))


if __name__ == "__main__":
    main()
