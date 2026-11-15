"""The body diagram: one self-contained HTML file rendered from build_all() output.

Front and back figures (artwork: react-native-body-highlighter, MIT; see bodyart.py) with
one region per muscle group, one panel per lens, and the
same numbers in a table under each panel, so the picture cannot disagree with the data.
Sequential lenses (program, session) use one blue ramp, light to dark; the recovery
lens uses three status colours that always appear with their text label.
"""

from html import escape

from .muscles import LABEL, MUSCLE_IDS
from .recovery import NOT, RECOVERED, UNCERTAIN, UNTRAINED, text_next

# Artwork: react-native-body-highlighter (MIT; see bodyart.py). Its pieces are assigned to
# muscle groups below. Where one piece covers two groups it is drawn twice, each copy clipped
# to one side of a cut line; the path data itself is never edited.
_SILHOUETTE = {"head", "hair", "hands", "feet", "ankles", "knees"}
_MIDLINE = {"front": 364.25, "back": 1083.5}
_VIEWBOX = {"front": "40 85 650 1270", "back": "760 85 650 1270"}
# (view, slug) -> muscle, or {index: muscle} with None as the default for other indices.
_ASSIGN = {
    "front": {"chest": "chest", "abs": "abs", "triceps": "triceps", "neck": "neck",
              "trapezius": "traps", "adductors": "adductors", "quadriceps": "quads",
              "tibialis": "tibialis", "calves": "calves",
              "obliques": {0: "serratus", 1: "serratus", 3: "serratus", None: "abs"},
              "forearm": {0: "brachioradialis", None: "forearms"}},
    "back": {"neck": "neck", "triceps": "triceps", "lower-back": "lower_back",
             "forearm": "forearms", "gluteal": "glutes", "adductors": "adductors",
             "hamstring": "hamstrings", "calves": "calves",
             # piece 0 is infraspinatus (scapula); the others are lats and teres major
             "upper-back": {0: "mid_back", None: "lats"}},
}
# (view, slug) -> (a, b, muscle on the side containing ref, ref, muscle on the other side).
# Points are for the figure's left-hand half; the right-hand half is mirrored at the midline.
_CUTS = {
    ("front", "deltoids"): ((226, 290), (212, 410), "side_delts", (195, 350), "front_delts"),
    ("front", "biceps"): ((180, 430), (212, 500), "brachialis", (184, 490), "biceps"),
    ("back", "deltoids"): ((944, 290), (928, 410), "side_delts", (914, 360), "rear_delts"),
    ("back", "trapezius"): ((960, 365), (1090, 365), "mid_back", (1050, 450), "traps"),
}


def _half_planes(a, b):
    """The two half-planes either side of line a-b, as large polygons."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = (dx * dx + dy * dy) ** 0.5
    dx, dy = dx / n, dy / n
    nx, ny = -dy, dx
    A = (a[0] - 3000 * dx, a[1] - 3000 * dy)
    B = (b[0] + 3000 * dx, b[1] + 3000 * dy)
    return [[A, B, (B[0] + 6000 * nx, B[1] + 6000 * ny), (A[0] + 6000 * nx, A[1] + 6000 * ny)],
            [A, B, (B[0] - 6000 * nx, B[1] - 6000 * ny), (A[0] - 6000 * nx, A[1] - 6000 * ny)]]


def _inside(poly, p):
    """Point-in-polygon (ray cast)."""
    x, y, hit = p[0], p[1], False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def _pieces(view):
    """[(muscle or None, path, clip polygon or None, seam line or None)]; None = silhouette."""
    from .bodyart import BACK, FRONT
    art, mid, out = FRONT if view == "front" else BACK, _MIDLINE[view], []
    for slug, side, idx, d in art:
        mirror = side == "right"

        def mx(p):
            return (2 * mid - p[0], p[1]) if mirror else p
        if slug in _SILHOUETTE:
            out.append((None, d, None, None))
        elif (view, slug) in _CUTS:
            a, b, m1, ref, m2 = _CUTS[(view, slug)]
            p1, p2 = _half_planes(mx(a), mx(b))
            if not _inside(p1, mx(ref)):
                p1, p2 = p2, p1
            out.append((m1, d, p1, None))
            out.append((m2, d, p2, (mx(a), mx(b))))
        else:
            rule = _ASSIGN[view][slug]
            out.append((rule if isinstance(rule, str) else rule.get(idx, rule[None]), d, None, None))
    return out


_FRONT = {}
_BACK = {}
for _view, _dest in (("front", _FRONT), ("back", _BACK)):
    for _m, _d, _clip, _seam in _pieces(_view):
        if _m:
            _dest.setdefault(_m, []).append((_d, _clip))


def _figure(view, cls_of, tip_of, title):
    uid = "".join(c if c.isalnum() else "-" for c in title.lower())
    defs, body, regions, seams = [], [], [], []
    for n, (m, d, clip, seam) in enumerate(_pieces(view)):
        if m is None:
            body.append('<path class="body" d="%s"/>' % d)
            continue
        cp = ""
        if clip:
            cid = "%s-%d" % (uid, n)
            defs.append('<clipPath id="%s"><polygon points="%s"/></clipPath>'
                        % (cid, " ".join("%.1f,%.1f" % p for p in clip)))
            cp = ' clip-path="url(#%s)"' % cid
        tip = escape(tip_of(m), quote=True)
        regions.append('<path class="m %s" data-tip="%s" d="%s"%s><title>%s</title></path>'
                       % (cls_of(m), tip, d, cp, escape(tip_of(m))))
        if seam:  # a visible line where one piece is split, clipped to that piece
            sid = "%s-%d-s" % (uid, n)
            defs.append('<clipPath id="%s"><path d="%s"/></clipPath>' % (sid, d))
            (x1, y1), (x2, y2) = seam
            seams.append('<line class="seam" x1="%g" y1="%g" x2="%g" y2="%g" clip-path="url(#%s)"/>'
                         % (x1, y1, x2, y2, sid))
    return ('<svg viewBox="%s" role="img" aria-label="%s"><defs>%s</defs>%s%s%s</svg>'
            % (_VIEWBOX[view], escape(title), "".join(defs), "".join(body), "".join(regions),
               "".join(seams)))


def _figures(cls_of, tip_of, name):
    return ('<div class="figs"><figure>%s<figcaption>Front</figcaption></figure>'
            '<figure>%s<figcaption>Back</figcaption></figure></div>'
            '<p class="tip" aria-live="polite">Tap a muscle for its figures.</p>'
            % (_figure("front", cls_of, tip_of, name + ", front"),
               _figure("back", cls_of, tip_of, name + ", back")))


def _bins(values):
    """Five equal-width bins over (0, max]. Returns (edges, bin_of)."""
    top = max(values) if values and max(values) > 0 else 1.0
    edges = [top * i / 5.0 for i in range(1, 6)]

    def bin_of(v):
        if v <= 0:
            return 0
        for i, e in enumerate(edges):
            if v <= e + 1e-9:
                return i + 1
        return 5
    return edges, bin_of


def _seq_legend(edges, unit):
    cells = ['<span><i class="sw q0"></i>0</span>']
    lo = 0.0
    for i, e in enumerate(edges):
        cells.append('<span><i class="sw q%d"></i>%g–%g</span>' % (i + 1, round(lo, 1), round(e, 1)))
        lo = e
    return '<p class="legend">%s <em>%s</em></p>' % ("".join(cells), escape(unit))


def _table(head, rows):
    out = ["<table><thead><tr>%s</tr></thead><tbody>"
           % "".join("<th%s>%s</th>" % (' class="n"' if num else "", escape(h)) for h, num in head)]
    for row in rows:
        out.append("<tr>%s</tr>" % "".join(
            "<td%s>%s</td>" % (' class="n"' if head[i][1] else "", c) for i, c in enumerate(row)))
    out.append("</tbody></table>")
    return "".join(out)


_STATE_CLASS = {NOT: "s-not", UNCERTAIN: "s-unc", RECOVERED: "s-rec", UNTRAINED: "q0"}
_STATE_MARK = {NOT: "✕", UNCERTAIN: "?", RECOVERED: "✓", UNTRAINED: "–"}


def render_html(allres):
    rec, ses, prog = allres["recovery"], allres["session"], allres["program"]
    rmap = {m["muscle"]: m for m in rec["muscles"]}
    smap = {m["muscle"]: m for m in ses["muscles"]}
    pmap = {m["muscle"]: m for m in prog["muscles"]}

    # Recovery panel
    def r_tip(m):
        x = rmap[m]
        if x["last_hit"] is None:
            return "%s: not trained in this export" % LABEL[m]
        return "%s: %s. Last hit %s, recovered by %s" % (LABEL[m], x["state"], x["last_hit"],
                                                         x["recovered_by"])
    order = {NOT: 0, UNCERTAIN: 1, RECOVERED: 2, UNTRAINED: 3}
    r_rows = [[escape(x["label"]),
               '<i class="sw %s"></i>%s %s' % (_STATE_CLASS[x["state"]], _STATE_MARK[x["state"]],
                                               escape(x["state"])),
               x["last_hit"] or "–", x["recovered_by"] or "–"]
              for x in sorted(rec["muscles"],
                              key=lambda x: (order[x["state"]], x["recovered_by"] or "", x["label"]))]
    r_legend = ('<p class="legend">'
                '<span><i class="sw s-not"></i>✕ likely not recovered</span>'
                '<span><i class="sw s-unc"></i>? uncertain</span>'
                '<span><i class="sw s-rec"></i>✓ likely recovered</span>'
                '<span><i class="sw q0"></i>– not trained recently</span></p>')
    recovery = ('<section><h2>Recovery as of %s</h2><p class="lead">%s</p>%s%s%s'
                '<p class="note">A heuristic: the windows are literature ranges, not measurements '
                'of you. k = %g; feedback points: %d.</p></section>'
                % (rec["as_of"], escape(text_next(rec["next_session"])), r_legend,
                   _figures(lambda m: _STATE_CLASS[rmap[m]["state"]], r_tip, "Recovery"),
                   _table([("Muscle", 0), ("State", 0), ("Last hit", 0), ("Recovered by", 0)], r_rows),
                   rec["k"], rec["tally"]["points"]))

    # Session panel
    s_edges, s_bin = _bins([m["sets"] for m in ses["muscles"]])

    def s_tip(m):
        x = smap[m]
        if x["sets"] <= 0:
            return "%s: not trained this session" % LABEL[m]
        return "%s: %g sets (%s)" % (LABEL[m], x["sets"], ", ".join(
            "%s x%d" % (e["name"], e["sets"]) for e in x["exercises"]))
    s_rows = [[escape(x["label"]), "%g" % x["sets"], "%d" % x["direct_sets"],
               escape(", ".join("%s x%d" % (e["name"], e["sets"]) for e in x["exercises"]))]
              for x in sorted(ses["muscles"], key=lambda x: (-x["sets"], x["label"])) if x["sets"] > 0]
    session = ('<section><h2>Session %s</h2>%s%s%s</section>'
               % (ses["date"], _seq_legend(s_edges, "done sets"),
                  _figures(lambda m: "q%d" % s_bin(smap[m]["sets"]), s_tip, "Session"),
                  _table([("Muscle", 0), ("Sets", 1), ("Direct", 1), ("From", 0)], s_rows)))

    # Program panel
    p_edges, p_bin = _bins([m["sets_per_week"] for m in prog["muscles"]])

    def p_tip(m):
        x = pmap[m]
        return "%s: %g sets/week (%g direct), %g days/week" % (
            LABEL[m], x["sets_per_week"], x["direct_sets_per_week"], x["days_per_week"])
    p_rows = [[escape(x["label"]), "%.1f" % x["sets_per_week"], "%.1f" % x["direct_sets_per_week"],
               "%.1f" % x["days_per_week"]]
              for x in sorted(prog["muscles"], key=lambda x: (-x["sets_per_week"], x["label"]))]
    w = prog["window"]
    program = ('<section><h2>Program, %s to %s</h2><p class="lead">Done sets per week over %.1f '
               'weeks (%d sessions). Secondary work counts half; Direct is primary-mover sets.</p>'
               '%s%s%s</section>'
               % (w["start"], w["end"], w["weeks"], w["sessions"],
                  _seq_legend(p_edges, "done sets per week"),
                  _figures(lambda m: "q%d" % p_bin(pmap[m]["sets_per_week"]), p_tip, "Program"),
                  _table([("Muscle", 0), ("Sets/wk", 1), ("Direct", 1), ("Days/wk", 1)], p_rows)))

    return _PAGE % {"title": "Muscle map, last session %s" % allres["last_session"],
                    "meta": escape(allres["state"]["summary"]),
                    "body": recovery + session + program}


_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<style>
.viz-root{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9;
--body:#ecebe6;--q0:#ecebe6;--q1:#b7d3f6;--q2:#86b6ef;--q3:#5598e7;--q4:#2a78d6;--q5:#184f95;
--not:#d03b3b;--unc:#fab219;--rec:#0ca30c;
background:var(--surface);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;
margin:0 auto;max-width:640px;padding:16px}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;
--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--line:#2c2c2a;--body:#2c2c2a;--q0:#2c2c2a;
--q1:#104281;--q2:#1c5cab;--q3:#2a78d6;--q4:#6da7ec;--q5:#b7d3f6}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--line:#2c2c2a;--body:#2c2c2a;--q0:#2c2c2a;--q1:#104281;--q2:#1c5cab;--q3:#2a78d6;--q4:#6da7ec;--q5:#b7d3f6}
body{margin:0;background:#fcfcfb}
@media (prefers-color-scheme:dark){body{background:#1a1a19}}
h1{font-size:20px;margin:0 0 2px}h2{font-size:17px;margin:28px 0 6px}
.meta,.note{color:var(--muted);font-size:13px;margin:2px 0}
.lead{color:var(--ink2);margin:4px 0 8px}
.figs{display:flex;gap:8px;justify-content:center}
figure{margin:0;flex:1;max-width:250px;text-align:center}
figcaption{color:var(--muted);font-size:12px}
svg{width:100%%;height:auto;display:block}
.body{fill:var(--body)}
.m,.body{stroke:var(--surface);stroke-width:1px;vector-effect:non-scaling-stroke}.m{cursor:pointer}
.seam{stroke:var(--surface);stroke-width:1.5px;vector-effect:non-scaling-stroke;pointer-events:none}
.m:hover,.m.on{stroke:var(--ink);stroke-width:1.5px}
.q0{fill:var(--q0)}.q1{fill:var(--q1)}.q2{fill:var(--q2)}.q3{fill:var(--q3)}.q4{fill:var(--q4)}.q5{fill:var(--q5)}
.s-not{fill:var(--not)}.s-unc{fill:var(--unc)}.s-rec{fill:var(--rec)}
.sw{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px;
box-shadow:0 0 0 1px var(--line)}
i.q0{background:var(--q0)}i.q1{background:var(--q1)}i.q2{background:var(--q2)}i.q3{background:var(--q3)}
i.q4{background:var(--q4)}i.q5{background:var(--q5)}
i.s-not{background:var(--not)}i.s-unc{background:var(--unc)}i.s-rec{background:var(--rec)}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:13px;color:var(--ink2);margin:6px 0}
.legend em{font-style:normal;color:var(--muted)}
.tip{min-height:2.9em;font-size:13px;color:var(--ink2);text-align:center;margin:6px 0 10px}
table{border-collapse:collapse;width:100%%;font-size:13px}
th,td{text-align:left;padding:4px 6px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}
.n{text-align:right;font-variant-numeric:tabular-nums}
</style></head><body><div class="viz-root">
<h1>%(title)s</h1><p class="meta">%(meta)s</p>
%(body)s
</div><script>
document.querySelectorAll("section").forEach(function(sec){
  var tip=sec.querySelector(".tip");
  sec.querySelectorAll(".m").forEach(function(el){
    function show(){sec.querySelectorAll(".m.on").forEach(function(x){x.classList.remove("on")});
      var t=el.getAttribute("data-tip");
      sec.querySelectorAll(".m").forEach(function(x){if(x.getAttribute("data-tip")===t)x.classList.add("on")});
      tip.textContent=t;}
    el.addEventListener("pointerenter",show);el.addEventListener("click",show);
  });
});
</script></body></html>
"""
