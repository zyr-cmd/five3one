"""The body diagram: one self-contained HTML file rendered from build_all() output.

Front and back figures with one region per muscle group, one panel per lens, and the
same numbers in a table under each panel, so the picture cannot disagree with the data.
Sequential lenses (program, session) use one blue ramp, light to dark; the recovery
lens uses three status colours that always appear with their text label.
"""

from html import escape

from .muscles import LABEL, MUSCLE_IDS
from .recovery import NOT, RECOVERED, UNCERTAIN, UNTRAINED, text_next

# Region geometry in a 200 x 400 box, left half only; the right half is mirrored.
# ("e", cx, cy, rx, ry) ellipse | ("p", [(x, y), ...]) polygon | ("r", x, y, w, h, radius) rect
_FRONT = {
    "neck": [("r", 92, 44, 16, 13, 3)],
    "traps": [("p", [(91, 50), (72, 62), (91, 62)])],
    "front_delts": [("e", 67, 73, 9, 11)],
    "side_delts": [("e", 56, 76, 5, 11)],
    "chest": [("r", 77, 64, 21, 27, 7)],
    "serratus": [("p", [(73, 94), (82, 94), (83, 120), (76, 116)])],
    "abs": [("r", 85, 94, 15, 58, 5)],
    "biceps": [("e", 59, 108, 7.5, 18)],
    "brachialis": [("e", 49.5, 117, 3.2, 10)],
    "brachioradialis": [("e", 49, 148, 4.5, 13)],
    "forearms": [("e", 57.5, 156, 5.5, 20)],
    "quads": [("e", 83, 218, 12.5, 37)],
    "adductors": [("e", 96, 200, 3.4, 21)],
    "tibialis": [("e", 84, 302, 5.5, 30)],
}
_BACK = {
    "neck": [("r", 92, 44, 16, 13, 3)],
    "traps": [("p", [(100, 50), (72, 61), (78, 71), (100, 67)])],
    "rear_delts": [("e", 67, 75, 9, 11)],
    "side_delts": [("e", 56, 78, 5, 11)],
    "mid_back": [("r", 81, 71, 19, 27, 5)],
    "lats": [("p", [(73, 88), (79, 88), (79, 101), (99, 101), (99, 138), (83, 130), (75, 110)])],
    "lower_back": [("r", 85, 141, 15, 22, 4)],
    "triceps": [("e", 59, 108, 8, 19)],
    "forearms": [("e", 55, 153, 7.5, 21)],
    "glutes": [("e", 87, 181, 12.5, 15)],
    "hamstrings": [("e", 84, 232, 12, 30)],
    "adductors": [("e", 96.5, 216, 3.2, 17)],
    "calves": [("e", 84, 300, 9.5, 30)],
}
# Neutral silhouette under the regions (left half; mirrored).
_BODY = [("e", 100, 27, 15, 17), ("r", 92, 42, 16, 16, 3), ("r", 71, 60, 29, 106, 10),
         ("e", 57, 110, 11, 52), ("e", 55, 156, 9, 30), ("e", 53, 190, 6, 8),
         ("e", 85, 222, 15, 62), ("e", 84, 300, 11, 40), ("e", 82, 346, 10, 6)]


def _shape(spec, mirror, attrs):
    kind = spec[0]
    if kind == "e":
        _, cx, cy, rx, ry = spec
        cx = 200 - cx if mirror else cx
        return '<ellipse cx="%g" cy="%g" rx="%g" ry="%g" %s/>' % (cx, cy, rx, ry, attrs)
    if kind == "r":
        _, x, y, w, h, rad = spec
        x = 200 - x - w if mirror else x
        return '<rect x="%g" y="%g" width="%g" height="%g" rx="%g" %s/>' % (x, y, w, h, rad, attrs)
    pts = [((200 - x) if mirror else x, y) for x, y in spec[1]]
    return '<polygon points="%s" %s/>' % (" ".join("%g,%g" % p for p in pts), attrs)


def _figure(regions, cls_of, tip_of, title):
    out = ['<svg viewBox="40 6 120 350" role="img" aria-label="%s">' % escape(title)]
    for spec in _BODY:
        out.append(_shape(spec, False, 'class="body"'))
        if not (spec[0] == "e" and spec[1] == 100) and not (spec[0] == "r" and spec[1] == 92):
            out.append(_shape(spec, True, 'class="body"'))
    for m in MUSCLE_IDS:
        for spec in regions.get(m, []):
            attrs = 'class="m %s" data-tip="%s"' % (cls_of(m), escape(tip_of(m), quote=True))
            centred = spec[0] == "r" and spec[1] == 92
            tip = "<title>%s</title>" % escape(tip_of(m))
            for mirror in ((False,) if centred else (False, True)):
                shape = _shape(spec, mirror, attrs)
                out.append(shape[:-2] + ">" + tip + "</" + shape[1:shape.index(" ")] + ">")
    out.append("</svg>")
    return "".join(out)


def _figures(cls_of, tip_of, name):
    return ('<div class="figs"><figure>%s<figcaption>Front</figcaption></figure>'
            '<figure>%s<figcaption>Back</figcaption></figure></div>'
            '<p class="tip" aria-live="polite">Tap a muscle for its figures.</p>'
            % (_figure(_FRONT, cls_of, tip_of, name + ", front"),
               _figure(_BACK, cls_of, tip_of, name + ", back")))


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
        cells.append('<span><i class="sw q%d"></i>%s%g</span>'
                     % (i + 1, "&gt;" if i else "&gt;0–", e) if False else
                     '<span><i class="sw q%d"></i>%g–%g</span>' % (i + 1, round(lo, 1), round(e, 1)))
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
                '<span><i class="sw q0"></i>– not trained</span></p>')
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
.m{stroke:var(--surface);stroke-width:1.2;cursor:pointer}
.m:hover,.m.on{stroke:var(--ink);stroke-width:1.4}
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
