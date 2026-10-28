"""Ajoute à une police (.ttf / .otf) toutes les lettres accentuées latines qui lui manquent
(français, espagnol, portugais, allemand, nordique, polonais, tchèque, roumain, turc...),
plus la ponctuation typographique (’ « » … – — „ espaces insécables).

Chaque lettre est fabriquée à partir des formes de la police elle-même :
la lettre de base (e, a, u...) + un accent pris dans la police (´ ` ^ ¨ ¸ ~ ...),
ou recréé à partir d'autres signes de la police (` retourné, points, virgule,
^ retourné pour ˇ, parenthèse couchée pour ˘...). En dernier recours seulement,
l'accent est dessiné.

Utilisation en ligne de commande :
    python3 accents_fr.py MaPolice.ttf [AutrePolice.otf ...]
"""

import copy
import math
import os
import sys
from io import BytesIO

from fontTools.ttLib import TTFont, newTable
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.recordingPen import DecomposingRecordingPen, RecordingPen
from fontTools.pens.reverseContourPen import ReverseContourPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen

ACUTE, GRAVE, CIRC, DIER, CEDILLA = "aigu", "grave", "circonflexe", "tréma", "cédille"
TILDE, RING, CARON, MACRON, BREVE, DOT = "tilde", "rond", "caron", "macron", "brève", "point"
OGONEK, DACUTE, COMMA_BELOW = "ogonek", "double aigu", "virgule souscrite"
APOS, SLASH, BAR = "apostrophe", "barre", "barre courte"
TOP_ACCENTS = {ACUTE, GRAVE, CIRC, DIER, TILDE, RING, CARON, MACRON, BREVE, DOT, DACUTE}

# accent : "lettre accentuée + lettre de base" (ı = i sans son point)
_SPEC = {
    ACUTE: "áa ée íı óo úu ýy ćc ńn śs źz ĺl ŕr ÁA ÉE ÍI ÓO ÚU ÝY ĆC ŃN ŚS ŹZ ĹL ŔR",
    GRAVE: "àa èe ìı òo ùu ÀA ÈE ÌI ÒO ÙU",
    CIRC: "âa êe îı ôo ûu ŵw ŷy ĉc ĝg ĥh ŝs ÂA ÊE ÎI ÔO ÛU ŴW ŶY ĈC ĜG ĤH ŜS",
    DIER: "äa ëe ïı öo üu ÿy ÄA ËE ÏI ÖO ÜU ŸY",
    TILDE: "ãa ñn õo ĩı ũu ÃA ÑN ÕO ĨI ŨU",
    RING: "åa ůu ÅA ŮU",
    CEDILLA: "çc şs ţt ÇC ŞS ŢT",
    COMMA_BELOW: "șs țt ȘS ȚT",
    CARON: "čc ěe ňn řr šs žz ČC ĎD ĚE ŇN ŘR ŠS ŤT ŽZ",
    MACRON: "āa ēe īı ōo ūu ĀA ĒE ĪI ŌO ŪU",
    BREVE: "ăa ğg ŭu ĂA ĞG ŬU",
    DOT: "ċc ėe ġg żz ĊC ĖE ĠG İI ŻZ",
    OGONEK: "ąa ęe įi ųu ĄA ĘE ĮI ŲU",
    DACUTE: "őo űu ŐO ŰU",
    APOS: "ďd ťt ľl ĽL",
    SLASH: "øo ØO",
    BAR: "łl ŁL",
}
ACCENTED = {pair[0]: (pair[1], kind) for kind, spec in _SPEC.items() for pair in spec.split()}
LIGATURES = {"œ": "oe", "æ": "ae", "Œ": "OE", "Æ": "AE"}
# Photoshop remplace ' par ’ (guillemets typographiques) : sans eux, « l'été » change aussi de police.
QUOTES = {"’": "right", "‘": "left", "”": "right2", "“": "left2"}
GUILLEMETS = {"«": ("left", True), "»": ("right", True), "‹": ("left", False), "›": ("right", False)}
PUNCTUATION = {"¡": "!", "¿": "?", "…": "ellipsis", "–": "endash", "—": "emdash", "‚": "low", "„": "low2",
               "\u00a0": "space", "\u202f": "thinspace"}

ACCENT_CODEPOINTS = {
    ACUTE: [0x0301, 0x00B4, 0x02CA],
    GRAVE: [0x0300, 0x0060, 0x02CB],
    CIRC: [0x0302, 0x02C6],
    DIER: [0x0308, 0x00A8],
    CEDILLA: [0x0327, 0x00B8],
    TILDE: [0x0303, 0x02DC],
    RING: [0x030A, 0x02DA, 0x00B0],
    CARON: [0x030C, 0x02C7],
    MACRON: [0x0304, 0x00AF, 0x02C9],
    BREVE: [0x0306, 0x02D8],
    DOT: [0x0307, 0x02D9],
    OGONEK: [0x0328, 0x02DB],
    DACUTE: [0x030B, 0x02DD],
    COMMA_BELOW: [0x0326],
}

GLYPH_NAMES = {
    "à": "agrave", "â": "acircumflex", "ä": "adieresis", "ç": "ccedilla",
    "é": "eacute", "è": "egrave", "ê": "ecircumflex", "ë": "edieresis",
    "î": "icircumflex", "ï": "idieresis", "ô": "ocircumflex", "ö": "odieresis",
    "ù": "ugrave", "û": "ucircumflex", "ü": "udieresis", "ÿ": "ydieresis",
    "á": "aacute", "í": "iacute", "ó": "oacute", "ú": "uacute", "ý": "yacute",
    "ì": "igrave", "ò": "ograve", "ã": "atilde", "ñ": "ntilde", "õ": "otilde",
    "å": "aring", "ø": "oslash", "š": "scaron", "ž": "zcaron", "ł": "lslash",
    "œ": "oe", "æ": "ae", "Œ": "OE", "Æ": "AE",
    "«": "guillemotleft", "»": "guillemotright", "‹": "guilsinglleft", "›": "guilsinglright",
    "’": "quoteright", "‘": "quoteleft", "”": "quotedblright", "“": "quotedblleft",
    "‚": "quotesinglbase", "„": "quotedblbase", "…": "ellipsis", "–": "endash", "—": "emdash",
    "¡": "exclamdown", "¿": "questiondown",
}


class FontError(Exception):
    pass


# --- petites opérations sur les contours ------------------------------------

def bounds(rec):
    pen = BoundsPen(None)
    rec.replay(pen)
    return pen.bounds


def transformed(rec, matrix):
    """Applique une matrice (a, b, c, d, dx, dy) ; garde le bon sens des contours."""
    out = RecordingPen()
    a, b, c, d = matrix[:4]
    target = ReverseContourPen(out) if a * d - b * c < 0 else out
    rec.replay(TransformPen(target, matrix))
    return out


def moved(rec, dx, dy):
    return transformed(rec, (1, 0, 0, 1, dx, dy))


def joined(*recs):
    out = RecordingPen()
    for r in recs:
        out.value.extend(r.value)
    return out


def contours(rec):
    result, current = [], []
    for op in rec.value:
        current.append(op)
        if op[0] in ("closePath", "endPath"):
            r = RecordingPen()
            r.value = current
            result.append(r)
            current = []
    return result


def outline_points(rec, steps=8):
    """Points le long du contour (les courbes sont échantillonnées)."""
    pts, cur = [], (0, 0)
    for op, args in rec.value:
        if op in ("moveTo", "lineTo"):
            cur = args[0]
            pts.append(cur)
        elif op == "curveTo" and len(args) == 3:
            p0, (p1, p2, p3) = cur, args
            for i in range(1, steps + 1):
                t = i / steps
                m = 1 - t
                pts.append(tuple(m**3 * a + 3 * m * m * t * b + 3 * m * t * t * c + t**3 * d
                                 for a, b, c, d in zip(p0, p1, p2, p3)))
            cur = p3
        elif op in ("curveTo", "qCurveTo"):
            pts.extend(a for a in args if a is not None)
            if args[-1] is not None:
                cur = args[-1]
    return pts


def band_center(rec, top=True, fraction=0.25):
    """Milieu horizontal du haut (ou du bas) de la lettre : là où se pose l'accent."""
    x0, y0, x1, y1 = bounds(rec)
    limit = y1 - fraction * (y1 - y0) if top else y0 + fraction * (y1 - y0)
    xs = [x for x, y in outline_points(rec) if (y >= limit if top else y <= limit)]
    return ((min(xs) + max(xs)) / 2 if xs else (x0 + x1) / 2), (limit + (y1 if top else y0)) / 2


def polygon(points):
    rec = RecordingPen()
    rec.moveTo(points[0])
    for p in points[1:]:
        rec.lineTo(p)
    rec.closePath()
    return rec


def stroke(points, widths):
    """Contour d'un trait qui suit des points, avec une épaisseur par point (sens TrueType)."""
    left, right = [], []
    for i, (x, y) in enumerate(points):
        (xa, ya), (xb, yb) = points[max(i - 1, 0)], points[min(i + 1, len(points) - 1)]
        length = math.hypot(xb - xa, yb - ya) or 1
        nx, ny = -(yb - ya) / length, (xb - xa) / length
        h = widths[i] / 2
        left.append((x + nx * h, y + ny * h))
        right.append((x - nx * h, y - ny * h))
    outline = left + right[::-1]
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(outline, outline[1:] + outline[:1]))
    return polygon(outline[::-1] if area > 0 else outline)


def bezier(p0, p1, p2, p3, steps):
    return [tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * c + t ** 3 * d
                  for a, b, c, d in zip(p0, p1, p2, p3)) for t in (i / steps for i in range(steps + 1))]


def circle(cx, cy, r):
    k = 0.5523 * r
    rec = RecordingPen()
    rec.moveTo((cx, cy + r))
    rec.curveTo((cx + k, cy + r), (cx + r, cy + k), (cx + r, cy))
    rec.curveTo((cx + r, cy - k), (cx + k, cy - r), (cx, cy - r))
    rec.curveTo((cx - k, cy - r), (cx - r, cy - k), (cx - r, cy))
    rec.curveTo((cx - r, cy + k), (cx - k, cy + r), (cx, cy + r))
    rec.closePath()
    return rec


# --- le travail sur la police -----------------------------------------------

class AccentBuilder:
    def __init__(self, font):
        if "CFF2" in font or "fvar" in font:
            raise FontError("Les polices variables ne sont pas prises en charge.")
        if "glyf" not in font and "CFF " not in font:
            raise FontError("Format de police non reconnu.")
        self.font = font
        self.is_cff = "CFF " in font
        if self.is_cff and hasattr(font["CFF "].cff.topDictIndex[0], "ROS"):
            raise FontError("Les polices CFF de type CID ne sont pas prises en charge.")
        self.cmap = font.getBestCmap()
        if not self.cmap or not any(t.isUnicode() for t in font["cmap"].tables):
            raise FontError("La police n'a pas de table de caractères Unicode.")
        self.glyphset = font.getGlyphSet()
        self.upm = font["head"].unitsPerEm
        # certaines polices déclarent un angle exagéré : on le limite à 20°
        self.slant = max(-0.36, min(0.36, math.tan(math.radians(-font["post"].italicAngle))))
        self.new_glyphs = []  # (nom, glyphe de référence à gauche, à droite)
        self.added, self.skipped = [], []
        self._measure()

    # mesures générales de la police
    def _measure(self):
        os2 = self.font["OS/2"] if "OS/2" in self.font else None
        self.xh = (getattr(os2, "sxHeight", 0) or self._top("x") or 0.5 * self.upm)
        stem = None
        for ch in "lI|i":
            b = self._box(ch)
            if b and (b[2] - b[0]) < 0.25 * self.upm:
                stem = b[2] - b[0]
                break
        self.stem = min(max(stem or 0.08 * self.upm, 0.03 * self.upm), 0.2 * self.upm)
        self.acc_h = 0.33 * self.xh
        self.gap = 0.12 * self.xh

    def _glyph(self, ch):
        return self.cmap.get(ord(ch)) if len(ch) == 1 else None

    def outline(self, name):
        rec = DecomposingRecordingPen(self.glyphset)
        self.glyphset[name].draw(rec)
        out = RecordingPen()
        out.value = rec.value
        return out

    def advance(self, name):
        return self.font["hmtx"][name][0]

    def _box(self, ch):
        g = self._glyph(ch)
        return bounds(self.outline(g)) if g else None

    def _top(self, ch):
        b = self._box(ch)
        return b[3] if b else None

    def _from_char(self, ch):
        g = self._glyph(ch)
        if not g:
            return None
        rec = self.outline(g)
        return rec if bounds(rec) else None

    # lettre de base (ı = i sans son point)
    def base(self, ch):
        if ch == "ı":
            rec = self._from_char("ı")
            if rec:
                return rec, self.cmap[ord("ı")]
            g = self._glyph("i")
            if not g:
                return None, None
            parts = contours(self.outline(g))
            if len(parts) > 1:
                boxes = [bounds(p) for p in parts]
                lowest = min(b[1] for b in boxes if b)
                parts = [p for p, b in zip(parts, boxes) if b and b[1] <= lowest + 0.1 * self.xh]
            return joined(*parts), g
        g = self._glyph(ch)
        return (self.outline(g), g) if g else (None, None)

    def _fit_height(self, rec, height, shrink_only=True):
        b = bounds(rec)
        h = b[3] - b[1]
        if h <= 0 or (shrink_only and h <= height * 1.6):
            return rec
        s = height / h
        return transformed(rec, (s, 0, 0, s, 0, 0))

    def _fit_width(self, rec, width):
        b = bounds(rec)
        s = width / max(b[2] - b[0], 1)
        return transformed(rec, (s, 0, 0, s, 0, 0))

    def _mirror(self, rec):
        # miroir horizontal, en gardant l'inclinaison de l'italique
        return transformed(rec, (-1, 0, 2 * self.slant, 1, 0, 0))

    def _flip(self, rec):
        # miroir vertical (^ devient ˇ), en gardant l'inclinaison
        return transformed(rec, (1, 0, -2 * self.slant, -1, 0, 0))

    def _from_codepoints(self, codepoints):
        for cp in codepoints:
            rec = self._from_char(chr(cp))
            if rec:
                return rec
        return None

    # accent : (contour, provenance)
    def accent(self, kind):
        rec = self._from_codepoints(ACCENT_CODEPOINTS.get(kind, []))
        if rec:
            return self._fit_height(rec, self.acc_h), "accent de la police"
        if kind in (ACUTE, GRAVE):
            other = self._from_codepoints(ACCENT_CODEPOINTS[GRAVE if kind == ACUTE else ACUTE])
            if other:
                return self._mirror(self._fit_height(other, self.acc_h)), "accent de la police retourné"
        if kind == CIRC:
            built = self._chevron()
            if built:
                return built, "aigu + grave de la police"
            rec = self._from_char("^")
            if rec:
                return self._fit_height(rec, self.acc_h, shrink_only=False), "^ de la police"
        if kind == CARON:
            circ, source = self.accent(CIRC)
            return self._flip(circ), source + ", retourné"
        if kind == DACUTE:
            acute, source = self.accent(ACUTE)
            b = bounds(acute)
            return joined(acute, moved(acute, round(0.8 * (b[2] - b[0]) + 0.3 * self.stem), 0)), source + ", doublé"
        if kind in (DIER, DOT):
            dot = self._from_char(".")
            if dot:
                return self._dot_from(dot, pair=kind == DIER), "point de la police"
        if kind == TILDE:
            rec = self._from_char("~")
            if rec:
                return self._fit_width(rec, 1.9 * self.acc_h), "~ de la police"
        if kind == RING:
            rec = self._from_char("o")
            if rec:
                return self._fit_height(rec, 0.85 * self.acc_h, shrink_only=False), "o de la police"
        if kind == MACRON:
            rec = self._from_char("-")
            if rec:
                b = bounds(rec)
                sx = 1.6 * self.acc_h / max(b[2] - b[0], 1)
                return transformed(rec, (sx, 0, 0, 1, 0, 0)), "trait d'union de la police"
        if kind == BREVE:
            rec = self._from_char("(")
            if rec:
                return self._fit_width(transformed(rec, (0, 1, -1, 0, 0, 0)), 1.6 * self.acc_h), "parenthèse de la police couchée"
        if kind in (COMMA_BELOW, APOS):
            comma = self._from_char(",")
            if comma:
                return comma, "virgule de la police"
        if kind == SLASH:
            rec = self._from_char("/")
            if rec:
                return rec, "/ de la police"
        return self._drawn(kind), "accent dessiné"

    def _chevron(self):
        """^ assemblé avec les vrais accents de la police : un aigu à gauche, un grave à droite."""
        grave = self._from_codepoints(ACCENT_CODEPOINTS[GRAVE])
        acute = self._from_codepoints(ACCENT_CODEPOINTS[ACUTE])
        if not (grave or acute):
            acute, grave = self._drawn(ACUTE), self._drawn(GRAVE)
        grave = self._fit_height(grave, self.acc_h) if grave else self._mirror(self._fit_height(acute, self.acc_h))
        acute = self._fit_height(acute, self.acc_h) if acute else self._mirror(grave)
        # un peu plus plat et plus étroit qu'un aigu, comme un vrai circonflexe
        flatten = (0.8, 0, 0, 0.8, 0, 0)
        acute, grave = transformed(acute, flatten), transformed(grave, flatten)
        a, g = bounds(acute), bounds(grave)
        acute = moved(acute, 0, -a[1])
        grave = moved(grave, 0, -g[1])
        a, g = bounds(acute), bounds(grave)
        overlap = 0.45 * (a[2] - a[0])
        return joined(acute, moved(grave, round(a[2] - overlap - g[0]), round(a[3] - g[3])))

    def _dot_from(self, dot, pair=True):
        """Point (ou premier point du tréma : le second est ajouté au placement, selon la largeur de la lettre)."""
        b = bounds(dot)
        size = max(b[2] - b[0], b[3] - b[1])
        target = min(max(self.stem * 0.8, 0.05 * self.upm), 0.13 * self.upm)
        if size > target:
            s = target / size
            dot = transformed(dot, (s, 0, 0, s, 0, 0))
        dot.single_dot = pair
        return dot

    def _drawn(self, kind):
        w, h, u = self.stem, self.acc_h, self.upm
        if kind in (ACUTE, GRAVE, DACUTE):
            d = 0.6 * h
            rec = polygon([(0, 0), (d - 0.2 * w, h), (d + 0.9 * w, h), (0.6 * w, 0)])
            if kind == GRAVE:
                rec = transformed(rec, (-1, 0, 0, 1, 0, 0))
            if kind == DACUTE:
                rec = joined(rec, moved(rec, round(d + 0.6 * w), 0))
        elif kind in (CIRC, CARON):
            W, t = 2.2 * h, min(1.1 * w, 0.4 * h)  # trait limité, sinon le ^ se referme en losange
            rec = polygon([(0, 0), (W / 2, h), (W, 0), (W - t, 0), (W / 2, h - t * 2 * h / W), (t, 0)])
            if kind == CARON:
                rec = transformed(rec, (1, 0, 0, -1, 0, h))
        elif kind in (DIER, DOT):
            r = 0.6 * w
            rec = circle(r, r, r)
        elif kind == TILDE:
            W, t, a, n = 2 * h, min(0.8 * w, 0.35 * h), 0.25 * h, 16
            xs = [W * i / n for i in range(n + 1)]
            wave = [a * math.sin(2 * math.pi * x / W) for x in xs]
            rec = polygon([(x, y + t) for x, y in zip(xs, wave)] + [(x, y) for x, y in reversed(list(zip(xs, wave)))])
            rec = transformed(rec, (1, 0, 0, -1, 0, 0))
        elif kind in (RING, BREVE):
            R, t, n = 0.5 * h * (1 if kind == RING else 1.5), min(0.7 * w, 0.3 * h), 24
            span = (0, 2 * math.pi) if kind == RING else (math.pi, 2 * math.pi)
            outer = [(R * math.cos(span[0] + (span[1] - span[0]) * i / n), R * math.sin(span[0] + (span[1] - span[0]) * i / n)) for i in range(n + 1)]
            inner = [((R - t) * x / R, (R - t) * y / R) for x, y in outer]
            if kind == RING:
                rec = joined(polygon(list(reversed(outer[:-1]))), polygon(inner[:-1]))
            else:
                rec = polygon(list(reversed(outer)) + inner)
        elif kind == MACRON:
            rec = polygon([(0, 0), (0, 0.7 * w), (1.6 * h, 0.7 * w), (1.6 * h, 0)])
        elif kind == BAR:  # barre du ł : plus large que la hampe, légèrement montante
            length, rise, t = w + 0.4 * self.xh, 0.22 * self.xh, min(0.7 * w, 0.09 * u)
            rec = polygon([(0, 0), (0, t), (length, rise + t), (length, rise)])
        elif kind in (COMMA_BELOW, APOS, SLASH):
            L = 0.35 * self.xh if kind in (COMMA_BELOW, APOS) else 1.0 * self.xh
            t = 0.8 * w
            lean = -0.3 * L if kind in (COMMA_BELOW, APOS) else 0.45 * L
            rec = polygon([(0, 0), (lean, L), (lean + t, L), (t, 0)]) if lean > 0 else polygon([(-lean, 0), (0, L), (t, L), (t - lean, 0)])
        else:  # cédille, ogonek : crochet fin qui s'épaissit dans la courbe et s'affine au bout
            k = self.xh
            thick = min(0.75 * w, 0.1 * k)
            if kind == CEDILLA:
                pts = [(0, 0.06 * k - i * 0.04 * k) for i in range(4)][:-1]
                pts += bezier((0, -0.06 * k), (0.2 * k, -0.06 * k), (0.21 * k, -0.27 * k), (-0.1 * k, -0.27 * k), 16)
            else:
                pts = bezier((0, 0.06 * k), (-0.17 * k, -0.1 * k), (-0.13 * k, -0.3 * k), (0.12 * k, -0.27 * k), 18)
            n = len(pts)
            widths = [thick * (0.45 + 0.55 * math.sin(math.pi * min(i / (n - 1) * 1.15, 1))) if i < n - 1 else 0.18 * thick
                      for i in range(n)]
            rec = stroke(pts, widths)
        if self.is_cff:  # contours dessinés dans le sens TrueType
            out = RecordingPen()
            rec.replay(ReverseContourPen(out))
            rec = out
        if self.slant:
            rec = transformed(rec, (1, 0, self.slant, 1, 0, 0))
        rec.single_dot = kind == DIER
        return rec

    # placement de l'accent sur la lettre : renvoie (contour, chasse)
    def compose(self, base, accent, kind, width):
        bx0, by0, bx1, by1 = bounds(base)
        if getattr(accent, "single_dot", False):
            b = bounds(accent)
            dist = max((b[2] - b[0]) * 1.9, 0.42 * (bx1 - bx0))
            accent = joined(accent, moved(accent, round(dist), 0))
        if kind == SLASH:
            b = bounds(accent)
            accent = transformed(accent, ((s := 1.15 * (by1 - by0) / max(b[3] - b[1], 1)), 0, 0, s, 0, 0))
        ax0, ay0, ax1, ay1 = bounds(accent)
        top_x, top_y = band_center(base, top=True)
        if kind in TOP_ACCENTS:
            capital = by1 > 1.2 * self.xh
            if capital and kind not in (DIER, DOT, RING):
                accent = transformed(accent, (1, 0, 0, 0.82, 0, 0.18 * ay0))
                ax0, ay0, ax1, ay1 = bounds(accent)
            dy = by1 + (0.7 if capital else 1) * self.gap - ay0
            mid_y = (ay0 + ay1) / 2 + dy
            dx = top_x + self.slant * (mid_y - top_y) - (ax0 + ax1) / 2
        elif kind in (CEDILLA, OGONEK, COMMA_BELOW):
            low_x, low_y = band_center(base, top=False)
            if kind == COMMA_BELOW:
                dy = by0 - 0.1 * self.xh - ay1
            else:
                dy = by0 + 0.3 * self.stem - ay1
            mid_y = (ay0 + ay1) / 2 + dy
            target = low_x if kind != OGONEK else bx1 - 0.6 * self.stem - 0.3 * (ax1 - ax0)
            dx = target + self.slant * (mid_y - low_y) - (ax0 + ax1) / 2
        elif kind == APOS:
            pts = [x for x, y in outline_points(base) if y >= by1 - 0.25 * (by1 - by0)]
            dx = max(pts) + 0.06 * self.xh - ax0
            dy = by1 - ay1
            width = max(width, ax1 + dx + 0.06 * self.xh)
        elif kind == SLASH:
            dx = (bx0 + bx1) / 2 - (ax0 + ax1) / 2
            dy = (by0 + by1) / 2 - (ay0 + ay1) / 2
        else:  # BAR : sur la hampe du l / L
            y = by0 + 0.45 * (by1 - by0)
            dx = top_x + self.slant * (y - top_y) - (ax0 + ax1) / 2
            dy = y - (ay0 + ay1) / 2
        return joined(base, moved(accent, round(dx), round(dy))), width

    def ligature(self, pair):
        g1, g2 = self._glyph(pair[0]), self._glyph(pair[1])
        if not (g1 and g2):
            return None
        r1, r2 = self.outline(g1), self.outline(g2)
        b1, b2 = bounds(r1), bounds(r2)
        dx = round(b1[2] - 0.8 * self.stem - b2[0])
        width = dx + self.advance(g2)
        return joined(r1, moved(r2, dx, 0)), width, g2, g1

    def quote(self, style):
        comma = self._from_char(",")
        if not comma:
            return None
        g = self._glyph(",")
        cap = self._top("H") or 0.7 * self.upm
        if style.startswith("left"):
            b = bounds(comma)
            comma = transformed(comma, (-1, 0, 0, -1, b[0] + b[2], b[1] + b[3]))
        b = bounds(comma)
        single = comma if style.startswith("low") else moved(comma, 0, round(cap - b[3]))
        width = self.advance(g)
        if style.endswith("2"):
            step = round((b[2] - b[0]) + 0.6 * self.stem)
            return joined(single, moved(single, step, 0)), width + step, g, g
        return single, width, g, g

    def guillemet(self, side, double=True):
        """« » ‹ › fabriqués avec le ^ (ou l'accent circonflexe) de la police, couché."""
        chevron, _ = self.accent(CIRC)
        angle = (0, 1, -1, 0) if side == "left" else (0, -1, 1, 0)
        chevron = transformed(chevron, angle + (0, 0))
        b = bounds(chevron)
        s = 0.6 * self.xh / (b[3] - b[1])
        chevron = transformed(chevron, (s, 0, 0, s, 0, 0))
        b = bounds(chevron)
        side_bearing = 0.08 * self.xh
        chevron = moved(chevron, round(side_bearing - b[0]), round(0.5 * self.xh - (b[1] + b[3]) / 2))
        step = round(0.75 * (b[2] - b[0]) + 0.5 * self.stem) if double else 0
        rec = joined(chevron, moved(chevron, step, 0)) if double else chevron
        width = round(2 * side_bearing + step + (b[2] - b[0]))
        if self.slant:
            rec = transformed(rec, (1, 0, self.slant, 1, -self.slant * 0.5 * self.xh, 0))
        like = self._glyph("o")
        return rec, width, like, like

    def punctuation(self, style):
        if style in ("!", "?"):  # ¡ ¿ : le signe retourné, qui descend sous la ligne
            g = self._glyph(style)
            if not g:
                return None
            rec = self.outline(g)
            x0, y0, x1, y1 = bounds(rec)
            rec = transformed(rec, (-1, 0, 0, -1, x0 + x1, y0 + y1))
            return moved(rec, 0, round(self.xh - bounds(rec)[3])), self.advance(g), g, g
        if style in ("low", "low2"):
            return self.quote(style)
        if style in ("space", "thinspace"):
            g = self._glyph(" ")
            if not g:
                return None
            width = self.advance(g) * (0.5 if style == "thinspace" else 1)
            return RecordingPen(), width, g, g
        if style == "ellipsis":
            g = self._glyph(".")
            if not g:
                return None
            dot, step = self.outline(g), self.advance(g)
            return joined(dot, moved(dot, step, 0), moved(dot, 2 * step, 0)), 3 * step, g, g
        g = self._glyph("-")  # tirets – et —
        if not g:
            return None
        rec = self.outline(g)
        x0, _, x1, _ = bounds(rec)
        rsb = self.advance(g) - x1
        width = (0.5 if style == "endash" else 1.0) * self.upm
        sx = max(width - x0 - rsb, 1) / max(x1 - x0, 1)
        return transformed(rec, (sx, 0, 0, 1, x0 - sx * x0, 0)), width, g, g

    # ajout d'un glyphe dans la police
    def add_glyph(self, ch, rec, width, left_like, right_like):
        name = glyph_name(ch)
        order = list(self.font.getGlyphOrder())
        while name in order:
            name += ".fr"
        b = bounds(rec)
        lsb = round(b[0]) if b else 0
        width = round(width)
        if self.is_cff:
            top = self.font["CFF "].cff.topDictIndex[0]
            private = top.Private
            nominal = getattr(private, "nominalWidthX", 0)
            pen = T2CharStringPen(width - nominal, None)
            rec.replay(pen)
            cs = pen.getCharString(private=private, globalSubrs=self.font["CFF "].cff.GlobalSubrs)
            strings = top.CharStrings
            if strings.charStringsAreIndexed:
                strings.charStringsIndex.append(cs)
                strings.charStrings[name] = len(strings.charStringsIndex) - 1
            else:
                strings.charStrings[name] = cs
            top.charset.append(name)
        else:
            pen = TTGlyphPen(None)
            rec.replay(Cu2QuPen(pen, max_err=1.0))
            glyf = self.font["glyf"]
            glyf.glyphs[name] = pen.glyph()
            glyf.glyphOrder = order + [name]
        self.font.setGlyphOrder(order + [name])
        self.font["hmtx"][name] = (width, lsb)
        for table in self.font["cmap"].tables:
            if table.isUnicode() and (table.format in (4, 6) and ord(ch) <= 0xFFFF or table.format in (12, 13)):
                table.cmap[ord(ch)] = name
        self.new_glyphs.append((name, left_like, right_like))
        return name

    def run(self):
        for ch, (base_ch, kind) in ACCENTED.items():
            if self._glyph(ch):
                continue
            base, base_name = self.base(base_ch)
            if not base or not bounds(base):
                self.skipped.append(ch)
                continue
            acc, source = self.accent(kind)
            rec, width = self.compose(base, acc, kind, self.advance(base_name))
            self.add_glyph(ch, rec, width, base_name, base_name)
            self.added.append((ch, source))
        extras = [(ch, lambda p=pair: self.ligature(p), "lettres collées (à vérifier)") for ch, pair in LIGATURES.items()]
        extras += [(ch, lambda s=style: self.quote(s), "virgule de la police") for ch, style in QUOTES.items()]
        extras += [(ch, lambda a=args: self.guillemet(*a), "^ de la police couché") for ch, args in GUILLEMETS.items()]
        extras += [(ch, lambda s=style: self.punctuation(s), "signes de la police") for ch, style in PUNCTUATION.items()]
        for ch, make, source in extras:
            if self._glyph(ch):
                continue
            made = make()
            if not made:
                self.skipped.append(ch)
                continue
            self.add_glyph(ch, *made)
            self.added.append((ch, source))
        if self.new_glyphs:
            self._copy_kerning()
            self._copy_gdef()
            self._update_os2()

    # l'approche (kerning) de « e » s'applique aussi à « é »
    def _copy_kerning(self):
        if "GPOS" in self.font and self.font["GPOS"].table.LookupList:
            for lookup in self.font["GPOS"].table.LookupList.Lookup:
                for sub in lookup.SubTable:
                    if lookup.LookupType == 9:
                        if sub.ExtensionLookupType != 2:
                            continue
                        sub = sub.ExtSubTable
                    elif lookup.LookupType != 2:
                        continue
                    self._copy_pairpos(sub)
        # l'ancienne table « kern » ne sert que si la police n'a pas de GPOS ;
        # elle est limitée à environ 10 900 paires, au-delà elle devient illisible
        if "kern" in self.font and "GPOS" not in self.font:
            for table in self.font["kern"].kernTables:
                pairs = getattr(table, "kernTable", None)
                if pairs is None:
                    continue
                original = list(pairs.items())
                for name, left_like, right_like in self.new_glyphs:
                    for (l, r), v in original:
                        if len(pairs) >= 10900:
                            return
                        if l == left_like:
                            pairs[(name, r)] = v
                        if r == right_like:
                            pairs[(l, name)] = v

    def _copy_pairpos(self, sub):
        cov = sub.Coverage.glyphs
        if sub.Format == 1:
            for name, left_like, _ in self.new_glyphs:
                if left_like in cov and name not in cov:
                    sub.PairSet.append(copy.deepcopy(sub.PairSet[cov.index(left_like)]))
                    cov.append(name)
            for ps in sub.PairSet:
                for name, _, right_like in self.new_glyphs:
                    for rec in list(ps.PairValueRecord):
                        if rec.SecondGlyph == right_like:
                            new = copy.deepcopy(rec)
                            new.SecondGlyph = name
                            ps.PairValueRecord.append(new)
                ps.PairValueCount = len(ps.PairValueRecord)
            sub.PairSetCount = len(sub.PairSet)
        elif sub.Format == 2:
            c1, c2 = sub.ClassDef1.classDefs, sub.ClassDef2.classDefs
            for name, left_like, right_like in self.new_glyphs:
                if left_like in cov and name not in cov:
                    cov.append(name)
                    if left_like in c1:
                        c1[name] = c1[left_like]
                if right_like in c2:
                    c2[name] = c2[right_like]

    def _copy_gdef(self):
        if "GDEF" not in self.font:
            return
        cd = getattr(self.font["GDEF"].table, "GlyphClassDef", None)
        if cd:
            for name, left_like, _ in self.new_glyphs:
                if left_like in cd.classDefs:
                    cd.classDefs[name] = cd.classDefs[left_like]

    def _update_os2(self):
        if "OS/2" not in self.font:
            return
        os2 = self.font["OS/2"]
        os2.ulUnicodeRange1 |= 1 << 1  # Latin-1 Supplément
        extended = any(0x100 <= ord(ch) <= 0x24F for ch, _ in self.added)
        if extended:
            os2.ulUnicodeRange1 |= 1 << 3  # Latin étendu A
        if any(0x2000 <= ord(ch) <= 0x206F for ch, _ in self.added):
            os2.ulUnicodeRange1 |= 1 << 31  # ponctuation générale
        if os2.version >= 1:
            os2.ulCodePageRange1 |= 1  # Latin 1
            if extended:
                os2.ulCodePageRange1 |= (1 << 1) | (1 << 4) | (1 << 7)  # Europe de l'Est, turc, balte

    def rename(self, suffix=" FR"):
        """Change le nom de la police pour qu'elle ne se confonde pas avec l'originale."""
        name = self.font["name"]
        family = name.getBestFamilyName() or "Police"
        ps_old = name.getDebugName(6)
        ps_new = (ps_old.split("-", 1)[0] + suffix.strip() + ("-" + ps_old.split("-", 1)[1] if "-" in ps_old else "")) if ps_old else None
        for rec in name.names:
            try:
                text = rec.toUnicode()
            except UnicodeDecodeError:
                continue
            if rec.nameID in (1, 16, 21, 4, 3) and family in text and family + suffix not in text:
                rec.string = text.replace(family, family + suffix, 1)
            elif rec.nameID == 6 and ps_new:
                rec.string = ps_new
        if self.is_cff:
            cff = self.font["CFF "].cff
            top = cff.topDictIndex[0]
            if ps_new:
                cff.fontNames[0] = ps_new
            for attr in ("FamilyName", "FullName"):
                value = getattr(top, attr, None)
                if value and family in value:
                    setattr(top, attr, value.replace(family, family + suffix, 1))
        return family + suffix


def glyph_name(ch):
    if ch in GLYPH_NAMES:
        return GLYPH_NAMES[ch]
    lower = GLYPH_NAMES.get(ch.lower())
    return lower[0].upper() + lower[1:] if lower else "uni%04X" % ord(ch)


def to_truetype(font):
    """Convertit une police .otf (contours CFF) en .ttf (contours TrueType)."""
    glyphset = font.getGlyphSet()
    order = font.getGlyphOrder()
    glyf = newTable("glyf")
    glyf.glyphOrder = order
    glyf.glyphs = {}
    for name in order:
        pen = TTGlyphPen(None)
        glyphset[name].draw(Cu2QuPen(pen, max_err=1.0, reverse_direction=True))
        glyf.glyphs[name] = pen.glyph()
    for t in ("CFF ", "VORG"):
        if t in font:
            del font[t]
    font["glyf"] = glyf
    font["loca"] = newTable("loca")
    maxp = font["maxp"]
    maxp.tableVersion = 0x00010000
    for attr in ("maxZones", "maxTwilightPoints", "maxStorage", "maxFunctionDefs", "maxInstructionDefs",
                 "maxStackElements", "maxSizeOfInstructions", "maxComponentElements"):
        setattr(maxp, attr, 1 if attr == "maxZones" else 0)
    post = font["post"]
    post.formatType = 2.0
    post.extraNames = []
    post.mapping = {}
    post.glyphOrder = order
    font["head"].glyphDataFormat = 0
    font.sfntVersion = "\0\1\0\0"


def fix_font(data, filename="police.ttf", truetype=False):
    """Prend le contenu d'un fichier de police, renvoie (nouveau contenu, nom de fichier, rapport).

    truetype=True rend toujours un .ttf, même à partir d'un .otf.
    """
    try:
        font = TTFont(BytesIO(data))
    except Exception:
        raise FontError("Ce fichier n'est pas une police lisible (.ttf ou .otf).")
    if font.flavor:
        font.flavor = None
    builder = AccentBuilder(font)
    report = {"warnings": []}
    if "OS/2" in font and font["OS/2"].fsType & 0x0002:
        report["warnings"].append("La licence de cette police interdit en principe de la modifier ou de l'intégrer.")
    builder.run()
    report["family"] = builder.rename() if builder.added else font["name"].getBestFamilyName()
    report["added"] = builder.added
    report["skipped"] = builder.skipped
    for t in ("hdmx", "LTSH", "VDMX", "DSIG"):
        if t in font:
            del font[t]
    if truetype and builder.is_cff:
        to_truetype(font)
        builder.is_cff = False
    out = BytesIO()
    font.save(out)
    stem, _ = os.path.splitext(os.path.basename(filename))
    ext = ".otf" if builder.is_cff else ".ttf"
    return out.getvalue(), stem + "-FR" + ext, report


def main(paths):
    if not paths:
        print(__doc__)
        return 1
    for path in paths:
        print(f"\n{os.path.basename(path)}")
        try:
            with open(path, "rb") as f:
                data, out_name, report = fix_font(f.read(), path)
        except FontError as e:
            print(f"  ✗ {e}")
            continue
        if not report["added"]:
            print("  Rien à ajouter : la police a déjà tous les accents.")
            continue
        out_path = os.path.join(os.path.dirname(os.path.abspath(path)), out_name)
        with open(out_path, "wb") as f:
            f.write(data)
        print("  Ajouté : " + " ".join(ch for ch, _ in report["added"]))
        if report["skipped"]:
            print("  Impossible (lettre de base absente) : " + " ".join(report["skipped"]))
        for w in report["warnings"]:
            print("  ⚠ " + w)
        print(f"  → {out_name}  (nom dans Photoshop : « {report['family']} »)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
