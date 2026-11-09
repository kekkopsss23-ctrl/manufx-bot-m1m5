"""
MANUFX M1/M5 - card dei segnali (stile chiaro "paper", diverso dal bot principale).
Disegnate con Pillow, nessun servizio esterno.

    from cards import render_card, card_recap
    png = render_card(payload, "ZONE")
"""
import io
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
TZ = ZoneInfo(os.environ.get("TZ_NAME", "Europe/Rome"))
BRAND = os.environ.get("BRAND_NAME", "MANUFX")
BRAND_SUB = os.environ.get("BRAND_SUB", "SIGNALS  M1 · M5")
TP1_PCT = max(0, min(100, int(float(os.environ.get("TP1_CLOSE_PCT", "70")))))
REST_PCT = 100 - TP1_PCT

W = 1080
# palette chiara
PAPER = (247, 245, 240)
CARD = (255, 255, 255)
INK = (18, 21, 30)
MUTED = (112, 116, 128)
SOFT = (160, 163, 172)
LINE = (226, 223, 215)
BUY = (0, 152, 102)
SELL = (214, 46, 62)
GOLD = (186, 138, 28)
AMBER = (214, 128, 20)
NAVY = (28, 40, 70)

_fonts = {}


def F(size, weight="Regular", display=False):
    key = (size, weight, display)
    if key not in _fonts:
        name = f"InterDisplay-{weight}.otf" if display else f"Inter-{weight}.otf"
        try:
            _fonts[key] = ImageFont.truetype(os.path.join(FONT_DIR, name), size)
        except OSError:
            _fonts[key] = ImageFont.load_default()
    return _fonts[key]


# ----------------------------------------------------------------- helpers
def _v(p, k, default=""):
    v = p.get(k)
    if v is None:
        return default
    v = str(v).strip()
    return default if v == "" or v.lower() in ("nan", "na", "none", "null") else v


def _f(p, k):
    try:
        return float(_v(p, k))
    except ValueError:
        return None


def _fmt(x):
    if x is None or x == "":
        return "—"
    s = str(x).strip()
    try:
        float(s)
    except ValueError:
        return s
    if s.startswith("-"):
        return "-" + _fmt(s[1:])
    ip, _, dp = s.partition(".")
    ip = f"{int(ip):,}" if ip.isdigit() else ip
    dp = (dp or "00").ljust(2, "0")
    return f"{ip}.{dp}"


def tf_label(tf):
    t = str(tf or "")
    if t.isdigit():
        m = int(t)
        return f"M{m}" if m < 60 else (f"H{m // 60}" if m % 60 == 0 else f"M{m}")
    return {"D": "D1", "1D": "D1", "W": "W1", "1W": "W1", "M": "MN"}.get(t, t)


def tw(d, t, f):
    return d.textlength(t, font=f)


def tint(c, a):
    """colore c mescolato col bianco: a=0 bianco, a=1 pieno"""
    return tuple(int(255 * (1 - a) + x * a) for x in c)


def chip(d, x, y, text, f, fg, bg, padx=12, pady=6, outline=None):
    w = tw(d, text, f)
    d.rounded_rectangle((x, y, x + w + padx * 2, y + f.size + pady * 2), radius=8, fill=bg, outline=outline)
    d.text((x + padx, y + pady - 1), text, font=f, fill=fg)
    return w + padx * 2


def triangle(d, x, y, s, up, col):
    if up:
        d.polygon([(x, y + s), (x + s, y + s), (x + s / 2, y)], fill=col)
    else:
        d.polygon([(x, y), (x + s, y), (x + s / 2, y + s)], fill=col)


def _now():
    return datetime.now(TZ).strftime("%d.%m.%Y  %H:%M")


def topbar(d, accent, H):
    """barra superiore scura con logo e data, comune a tutte le card"""
    d.rectangle((0, 0, W, 84), fill=INK)
    d.rectangle((0, 84, W, 90), fill=accent)
    f = F(28, "ExtraBold", display=True)
    d.text((48, 24), BRAND, font=f, fill=(255, 255, 255))
    x = 48 + tw(d, BRAND, f) + 16
    d.text((x, 33), BRAND_SUB, font=F(15, "SemiBold"), fill=SOFT)
    t = _now()
    d.text((W - 48 - tw(d, t, F(16, "Medium")), 32), t, font=F(16, "Medium"), fill=SOFT)


def footer(d, H):
    d.line([(48, H - 54), (W - 48, H - 54)], fill=LINE, width=2)
    f = F(14, "Medium")
    d.text((48, H - 38), "Rischio max 1% del conto · non è consulenza finanziaria", font=f, fill=SOFT)
    t = f"{BRAND} · M1 / M5"
    d.text((W - 48 - tw(d, t, f), H - 38), t, font=f, fill=SOFT)


def _png(img):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ----------------------------------------------------------------- ZONA (quadrata, con scala prezzi)
def card_zone(p):
    H = 1080
    side = _v(p, "side").upper()
    is_buy = side == "BUY"
    acc = BUY if is_buy else SELL
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    topbar(d, acc, H)

    sym = _v(p, "symbol", "—")
    tf = tf_label(_v(p, "tf"))

    # titolo
    y = 128
    triangle(d, 48, y + 14, 46, is_buy, acc)
    d.text((112, y), "BUY ZONE" if is_buy else "SELL ZONE", font=F(68, "Black", display=True), fill=acc)
    y += 92
    d.text((48, y), sym, font=F(40, "Bold", display=True), fill=INK)
    x = 48 + tw(d, sym, F(40, "Bold", display=True)) + 18
    x += chip(d, x, y + 7, tf, F(18, "Bold"), (255, 255, 255), NAVY) + 10
    if _v(p, "inside") == "1":
        chip(d, x, y + 7, "PREZZO IN ZONA", F(15, "Bold"), GOLD, tint(GOLD, 0.12), outline=tint(GOLD, 0.5))

    # ---------------- colonna sinistra: livelli
    y0 = 300
    L = (48, y0, 600, 880)
    d.rounded_rectangle(L, radius=20, fill=CARD, outline=LINE, width=2)
    entry, sl = _f(p, "price"), _f(p, "sl")
    risk = _f(p, "risk") or (abs(entry - sl) if entry is not None and sl is not None else None)
    rows = []
    if _v(p, "zbot") and _v(p, "ztop"):
        rows.append(("ZONA", f"{_fmt(_v(p, 'zbot'))} – {_fmt(_v(p, 'ztop'))}", acc, None, True))
    rows.append(("ENTRY", _fmt(_v(p, "price")), INK, None, False))
    rows.append(("STOP", _fmt(_v(p, "sl")), SELL, "-1R", False))
    for i in range(1, 6):
        tp = _f(p, f"tp{i}")
        if tp is not None:
            rr = f"+{abs(tp - entry) / risk:.0f}R" if risk and entry is not None else None
            rows.append((f"TP{i}", _fmt(_v(p, f"tp{i}")), BUY, rr, False))
    rh = (L[3] - L[1] - 30) / max(len(rows), 1)
    for i, (lab, value, col, rr, hl) in enumerate(rows):
        ry = L[1] + 15 + i * rh
        if hl:
            d.rounded_rectangle((L[0] + 12, ry + 6, L[2] - 12, ry + rh - 6), radius=12, fill=tint(acc, 0.10))
        elif i:
            d.line([(L[0] + 28, ry), (L[2] - 28, ry)], fill=LINE, width=1)
        cy = ry + rh / 2
        d.text((L[0] + 30, cy - 9), lab, font=F(15, "Bold"), fill=MUTED)
        d.text((L[0] + 130, cy - 15), value, font=F(26 if not hl else 24, "Bold"), fill=col)
        if rr:
            fr = F(15, "SemiBold")
            chip(d, L[2] - 30 - tw(d, rr, fr) - 20, cy - 15, rr, fr, col, tint(col, 0.10), padx=10, pady=5)

    # ---------------- colonna destra: scala prezzi
    R = (632, y0, W - 48, 880)
    d.rounded_rectangle(R, radius=20, fill=CARD, outline=LINE, width=2)
    d.text((R[0] + 26, R[1] + 20), "MAPPA LIVELLI", font=F(14, "Bold"), fill=MUTED)
    levels = []
    if sl is not None:
        levels.append(("SL", sl, SELL))
    if entry is not None:
        levels.append(("ENTRY", entry, INK))
    for i in range(1, 6):
        tp = _f(p, f"tp{i}")
        if tp is not None:
            levels.append((f"TP{i}", tp, BUY))
    zt, zb = _f(p, "ztop"), _f(p, "zbot")
    prices = [v for _, v, _ in levels] + [v for v in (zt, zb) if v is not None]
    if prices:
        lo, hi = min(prices), max(prices)
        span = (hi - lo) or 1
        top, bot = R[1] + 64, R[3] - 34
        ax = R[0] + 70

        def py(v):
            return bot - (v - lo) / span * (bot - top)

        if zt is not None and zb is not None:
            d.rectangle((ax - 26, py(zt), R[2] - 26, py(zb)), fill=tint(acc, 0.16))
            d.text((R[2] - 34 - tw(d, "ZONA", F(12, "Bold")), py(zt) + 4), "ZONA", font=F(12, "Bold"), fill=acc)
        d.line([(ax, top - 10), (ax, bot + 10)], fill=LINE, width=3)
        if entry is not None:
            tps = [v for lab, v, _ in levels if lab.startswith("TP")]
            if sl is not None:
                d.line([(ax, py(entry)), (ax, py(sl))], fill=tint(SELL, 0.55), width=6)
            if tps:
                far = max(tps) if is_buy else min(tps)
                d.line([(ax, py(entry)), (ax, py(far))], fill=tint(BUY, 0.55), width=6)
        last_y = None
        for lab, v, col in sorted(levels, key=lambda t: -t[1]):
            yy = py(v)
            d.line([(ax - 12, yy), (R[2] - 26, yy)], fill=tint(col, 0.35), width=1)
            d.ellipse((ax - 8, yy - 8, ax + 8, yy + 8), fill=col)
            ty = yy - 10
            if last_y is not None and abs(ty - last_y) < 22:
                ty = last_y + 22
            d.text((ax + 22, ty), lab, font=F(15, "Bold"), fill=col)
            d.text((ax + 92, ty), _fmt(_v(p, "price") if lab == "ENTRY" else _v(p, "sl") if lab == "SL" else _v(p, lab.lower())),
                   font=F(15, "Medium"), fill=MUTED)
            last_y = ty

    # ---------------- piano
    y = 908
    d.rounded_rectangle((48, y, W - 48, y + 92), radius=18, fill=INK)
    steps = [(f"{TP1_PCT}%", "chiuso a TP1"), ("STOP", "a pareggio"), (f"{REST_PCT}%", "in corsa fino a TP5")]
    cw = (W - 96) / 3
    for i, (big, small) in enumerate(steps):
        cx = 48 + i * cw + 30
        d.text((cx, y + 18), big, font=F(30, "ExtraBold", display=True), fill=(255, 255, 255) if i != 1 else tint(acc, 0.85))
        d.text((cx, y + 58), small, font=F(15, "Medium"), fill=SOFT)
        if i:
            d.line([(48 + i * cw, y + 20), (48 + i * cw, y + 72)], fill=(60, 64, 76), width=1)
    footer(d, H)
    return img


# ----------------------------------------------------------------- aggiornamenti (TP / SL / BE / CLOSE)
def card_update(p, kind):
    """kind: TP | SL | BE | CLOSE"""
    H = 620
    side = _v(p, "side").upper()
    sym = _v(p, "symbol", "—")
    tf = tf_label(_v(p, "tf"))
    level = _v(p, "level")
    price, entry = _f(p, "price"), _f(p, "entry")
    pr = _v(p, "plan_r")
    try:
        plan_r = float(pr) if pr != "" else None
    except ValueError:
        plan_r = None

    if kind == "TP":
        acc = BUY
        title = f"TP{level} RAGGIUNTO"
        sub = (f"Chiudi il {TP1_PCT}% · stop a pareggio · {REST_PCT}% in corsa" if level == "1"
               else "Obiettivo finale: si chiude tutto" if level == "5"
               else f"Stop a pareggio · il {REST_PCT}% continua")
    elif kind == "BE":
        acc, title = AMBER, "CHIUSA A PAREGGIO"
        sub = f"{TP1_PCT}% già incassato a TP1" + (f" · piano {plan_r:+.1f}R" if plan_r is not None else "")
    elif kind == "CLOSE":
        acc, title, sub = SELL, "SETUP ANNULLATO", "Zona invalidata prima di TP1"
    else:
        acc, title, sub = SELL, "STOP LOSS", "Chiusa a -1R come da piano"

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    topbar(d, acc, H)
    # banda laterale
    d.rectangle((0, 90, 14, H), fill=acc)

    y = 124
    x = 48
    triangle(d, x, y + 6, 22, side == "BUY", BUY if side == "BUY" else SELL)
    x += 34
    d.text((x, y), f"{sym}  ·  {tf}  ·  {side}", font=F(22, "Bold"), fill=INK)
    y += 50
    d.text((48, y), title, font=F(64, "Black", display=True), fill=acc)
    y += 84
    d.text((48, y), sub, font=F(22, "Medium"), fill=MUTED)

    # traccia TP1..TP5
    y += 58
    lv = int(level) if (kind == "TP" and level.isdigit()) else (1 if kind == "BE" else 0)
    tx0, tx1 = 48, W - 48
    ty = y + 20
    d.line([(tx0 + 16, ty), (tx1 - 16, ty)], fill=LINE, width=6)
    if lv:
        d.line([(tx0 + 16, ty), (tx0 + 16 + (tx1 - tx0 - 32) * (lv - 1) / 4, ty)], fill=acc, width=6)
    for k in range(5):
        cx = tx0 + 16 + (tx1 - tx0 - 32) * k / 4
        on = k < lv
        d.ellipse((cx - 16, ty - 16, cx + 16, ty + 16), fill=acc if on else CARD, outline=acc if on else LINE, width=3)
        t = f"TP{k + 1}"
        d.text((cx - tw(d, t, F(14, "Bold")) / 2, ty + 24), t, font=F(14, "Bold"), fill=INK if on else SOFT)

    # riquadro numeri
    y += 92
    box = (48, y, W - 48, H - 72)
    d.rounded_rectangle(box, radius=18, fill=CARD, outline=LINE, width=2)
    cols = []
    if entry is not None:
        cols.append(("ENTRY", _fmt(_v(p, "entry")), INK))
    cols.append(("PREZZO", _fmt(_v(p, "price")), acc))
    if kind == "TP" and level.isdigit():
        cols.append(("POSIZIONE", f"+{level}R", BUY))
    elif plan_r is not None:
        cols.append(("PIANO", f"{plan_r:+.1f}".rstrip("0").rstrip(".") + "R", acc))
    elif kind in ("SL", "CLOSE"):
        cols.append(("PIANO", "-1R", SELL))
    cw = (box[2] - box[0]) / len(cols)
    for i, (lab, value, col) in enumerate(cols):
        cx = box[0] + 28 + i * cw
        mid = (box[1] + box[3]) / 2
        d.text((cx, mid - 32), lab, font=F(13, "Bold"), fill=SOFT)
        d.text((cx, mid - 12), value, font=F(32, "Bold"), fill=col)
        if i:
            d.line([(box[0] + i * cw, box[1] + 16), (box[0] + i * cw, box[3] - 16)], fill=LINE, width=1)
    footer(d, H)
    return img


# ----------------------------------------------------------------- report giornaliero
def card_recap(data: dict) -> bytes:
    rows = data.get("rows") or []
    tp1 = int(data.get("tp1_pct") or TP1_PCT)
    tot_r = float(data.get("tot_r") or 0)
    acc = BUY if tot_r > 0 else SELL if tot_r < 0 else AMBER
    shown = rows[:14]
    extra = len(rows) - len(shown)
    rh = 48
    H = 90 + 40 + 80 + 150 + 50 + len(shown) * rh + (34 if extra else 0) + 90
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    topbar(d, acc, H)
    y = 122
    d.text((48, y), "REPORT DEL GIORNO", font=F(52, "Black", display=True), fill=INK)
    t = data.get("date", "")
    d.text((W - 48 - tw(d, t, F(22, "Medium")), y + 22), t, font=F(22, "Medium"), fill=MUTED)
    y += 84
    nw, nl, no = data.get("n_win", 0), data.get("n_loss", 0), data.get("n_open", 0)
    tiles = [("ZONE", str(data.get("n", 0)), INK, "  ·  ".join(f"{tf_label(k)}: {v}" for k, v in (data.get("per_tf") or {}).items())),
             ("VINTE / PERSE", f"{nw} / {nl}", BUY if nw >= nl else SELL, f"{no} in corso" if no else "tutte chiuse"),
             ("RISULTATO", f"{tot_r:+.1f}".rstrip("0").rstrip(".") + "R", acc, f"{tp1}% a TP1"),
             ("PIPS", f"{float(data.get('tot_pips') or 0):+.0f}", acc, "somma zone")]
    gap = 14
    tws = (W - 96 - gap * 3) / 4
    for i, (lab, value, col, sub) in enumerate(tiles):
        x = 48 + i * (tws + gap)
        d.rounded_rectangle((x, y, x + tws, y + 128), radius=16, fill=CARD, outline=LINE, width=2)
        d.rectangle((x + 18, y + 18, x + 22, y + 34), fill=col)
        d.text((x + 30, y + 16), lab, font=F(13, "Bold"), fill=SOFT)
        d.text((x + 20, y + 44), value, font=F(38, "Bold"), fill=col)
        d.text((x + 20, y + 96), sub, font=F(13, "Medium"), fill=MUTED)
    y += 150
    hdr = [("ORA", 48), ("SETUP", 140), ("ESITO", 470), ("R", 860), ("PIPS", 960)]
    for lab, x in hdr:
        d.text((x, y + 14), lab, font=F(13, "Bold"), fill=SOFT)
    y += 44
    d.line([(48, y), (W - 48, y)], fill=INK, width=2)
    for i, r_ in enumerate(shown):
        ry = y + i * rh
        if i % 2:
            d.rectangle((48, ry, W - 48, ry + rh), fill=(240, 238, 232))
        ty = ry + 13
        d.text((48, ty), r_["time"], font=F(18, "Medium"), fill=MUTED)
        s = (r_.get("side") or "").upper()
        triangle(d, 140, ty + 3, 14, s == "BUY", BUY if s == "BUY" else SELL)
        d.text((164, ty), f"{r_['symbol']}  {tf_label(r_['tf'])}  {s}", font=F(18, "Bold"), fill=INK)
        st = r_.get("state")
        ecol = BUY if st == "TP" else SELL if st in ("SL", "ANNULLATO") else AMBER if st == "BE" else NAVY
        d.text((470, ty), r_["label"], font=F(18, "SemiBold"), fill=ecol)
        rv = r_.get("r")
        if rv is not None:
            rc = BUY if rv > 0 else SELL if rv < 0 else AMBER
            d.text((860, ty), f"{rv:+.1f}".rstrip("0").rstrip(".") + "R", font=F(18, "Bold"), fill=rc)
            if r_.get("pips") is not None:
                d.text((960, ty), f"{r_['pips']:+.0f}", font=F(18, "Bold"), fill=rc)
        else:
            d.text((860, ty), "—", font=F(18, "Medium"), fill=SOFT)
    y += len(shown) * rh
    if extra:
        d.text((48, y + 8), f"+ altre {extra} zone nel messaggio", font=F(15, "Medium"), fill=SOFT)
    footer(d, H)
    return _png(img)


# ----------------------------------------------------------------- API
def render_card(p: dict, event: str | None = None) -> bytes:
    ev = (event or _v(p, "event")).upper()
    if ev == "ZONE":
        img = card_zone(p)
    elif ev == "TP":
        img = card_update(p, "TP")
    elif ev == "CLOSE":
        img = card_update(p, "CLOSE")
    elif ev == "SL" and _v(p, "reason").upper().startswith("BE"):
        img = card_update(p, "BE")
    else:
        img = card_update(p, "SL")
    return _png(img)


if __name__ == "__main__":
    out = os.environ.get("OUT", "samples")
    os.makedirs(out, exist_ok=True)
    base = {"symbol": "XAUUSD", "tf": "1"}
    buy = {**base, "tf": "5", "side": "BUY", "price": "4186.20", "sl": "4181.90", "risk": "4.30",
           "tp1": "4190.50", "tp2": "4194.80", "tp3": "4199.10", "tp4": "4203.40", "tp5": "4207.70",
           "ztop": "4191.40", "zbot": "4183.60", "inside": "1"}
    sell = {**base, "side": "SELL", "price": "4201.30", "sl": "4203.10", "risk": "1.80",
            "tp1": "4199.50", "tp2": "4197.70", "tp3": "4195.90", "tp4": "4194.10", "tp5": "4192.30",
            "ztop": "4202.60", "zbot": "4200.40", "inside": "0"}
    samples = {
        "1_zona_buy_m5": (buy, "ZONE"),
        "2_zona_sell_m1": (sell, "ZONE"),
        "3_tp1": ({**base, "side": "SELL", "level": "1", "price": "4199.50", "entry": "4201.30"}, "TP"),
        "4_tp3": ({**base, "tf": "5", "side": "BUY", "level": "3", "price": "4199.10", "entry": "4186.20"}, "TP"),
        "5_stop": ({**base, "side": "BUY", "reason": "SL HIT", "price": "4181.90", "entry": "4186.20"}, "SL"),
        "6_pareggio": ({**base, "side": "BUY", "reason": "BE HIT", "price": "4186.20", "entry": "4186.20", "plan_r": 0.7}, "SL"),
        "7_annullato": ({**base, "side": "SELL", "r": "-1", "price": "4204.00", "plan_r": -1}, "CLOSE"),
    }
    for name, (payload, ev) in samples.items():
        with open(os.path.join(out, f"{name}.png"), "wb") as f:
            f.write(render_card(payload, ev))
        print("ok", name)
