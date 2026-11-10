"""
MANUFX M1/M5 - secondo bot segnali (indicatore MANUFX SELL/BUY ZONE)
Progetto SEPARATO dal bot principale (manufx-bot): server, token, gruppo e stato propri.
Stessa logica delle zone (preavviso, zona, TP, stop, annullo, riepilogo), stile diverso,
e pubblica SEMPRE i segnali dei timeframe M1 e M5 (gli altri timeframe vengono ignorati).

TradingView (alert webhook) -> questo server -> gruppo Telegram

Variabili d'ambiente:
  TELEGRAM_TOKEN   token del NUOVO bot (BotFather)
  CHAT_ID          id del NUOVO gruppo, es. -1001234567890
  TOPIC_ID         (opzionale) topic dove pubblicare; vuoto = chat generale del gruppo
  TOPIC_M1         (opzionale) topic dedicato alle zone M1 (ha la precedenza su TOPIC_ID)
  TOPIC_M5         (opzionale) topic dedicato alle zone M5 (ha la precedenza su TOPIC_ID)
  RECAP_TOPIC      (opzionale) topic del riepilogo giornaliero (default TOPIC_ID)
  WEBHOOK_SECRET   chiave segreta: la stessa scritta nell'indicatore (gruppo "Telegram Bot")
  TIMEFRAMES       timeframe pubblicati, default "1,5" (= M1 e M5)
  FOLLOW_TFREC     on/off (default off): se on applica anche il filtro volatilita' dell'indicatore
                   (pubblica solo il timeframe consigliato). Off = M1 e M5 sempre.
  ONE_SIDE         on/off (default on): niente zona opposta finche' un setup sullo stesso simbolo e' aperto
  TP1_CLOSE_PCT    % da chiudere a TP1 (default 70)
  CARD_EVENTS      eventi con immagine (default nessuno: solo testo; es. ZONE,TP,SL,CLOSE,RECAP)
  TP_SHOW          TP mostrati nel segnale (default "1,5")
  SHOW_TF          on/off (default off): aggiunge M1/M5 dopo il simbolo
  PRICE_DECIMALS   decimali dei prezzi (vuoto = automatico: oro senza decimali)
  RECAP_TIME       ora del riepilogo (default 21:00, vuoto = disattivato)
  STATE_FILE       file di stato (default trades.json; su Railway meglio /data/trades.json con un Volume)
  OPENAI_API_KEY   (opzionale) commento AI di 1-2 frasi
  BRAND_NAME / BRAND_SUB  testo del logo sulle card
"""
import os
import json
import time
import html
import queue
import hashlib
import logging
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request, jsonify, Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("manufx-m1m5")


def _int_env(name):
    try:
        return int(os.environ.get(name, "0") or 0) or None
    except ValueError:
        return None


TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
TOPIC_ID = _int_env("TOPIC_ID")
TOPIC_BY_TF = {"1": _int_env("TOPIC_M1"), "5": _int_env("TOPIC_M5")}
RECAP_TOPIC = _int_env("RECAP_TOPIC") or TOPIC_ID
SECRET = os.environ.get("WEBHOOK_SECRET", "")
TIMEFRAMES = {t.strip().upper() for t in os.environ.get("TIMEFRAMES", "1,5").split(",") if t.strip()}
FOLLOW_TFREC = os.environ.get("FOLLOW_TFREC", "off").lower() == "on"
ONE_SIDE = os.environ.get("ONE_SIDE", "on").lower() == "on"
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
AI_COMMENT = os.environ.get("AI_COMMENT", "on").lower() == "on" and bool(OPENAI_KEY)
STATE_FILE = os.environ.get("STATE_FILE", "trades.json")
TZ = ZoneInfo(os.environ.get("TZ_NAME", "Europe/Rome"))
TP1_PCT = max(0, min(100, int(float(os.environ.get("TP1_CLOSE_PCT", "70")))))
REST_PCT = 100 - TP1_PCT
RECAP_TIME = os.environ.get("RECAP_TIME", "21:00")
PIP_SIZE = os.environ.get("PIP_SIZE", "")
CARD_EVENTS = {e.strip().upper() for e in os.environ.get("CARD_EVENTS", "").split(",") if e.strip()}

TRADE_EVENTS = {"PRE", "PRE_KO", "ZONE", "TP", "SL", "TSL", "CLOSE"}   # ZONE_ENTER / ZONE_EXIT ignorati

app = Flask(__name__)
jobs: "queue.Queue[dict]" = queue.Queue()
state_lock = threading.Lock()
recent = OrderedDict()


# ---------------------------------------------------------------- stato
def load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s: dict) -> None:
    try:
        if len(s) > 300:
            for k in list(s.keys())[: len(s) - 300]:
                s.pop(k, None)
        d = os.path.dirname(STATE_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f)
    except Exception as e:
        log.warning("Impossibile salvare lo stato: %s", e)


trades = load_state()


# ---------------------------------------------------------------- utilità
def val(p: dict, k: str):
    v = p.get(k)
    if v is None:
        return None
    v = str(v).strip()
    return None if v == "" or v.lower() in ("nan", "na", "null", "none") else v


def num(p: dict, k: str):
    v = val(p, k)
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def esc(s) -> str:
    return html.escape(str(s))


def tf_label(tf) -> str:
    if not tf:
        return ""
    t = str(tf)
    if t.isdigit():
        m = int(t)
        return f"M{m}" if m < 60 else f"H{m // 60}" if m % 60 == 0 else f"M{m}"
    return {"D": "D1", "1D": "D1", "W": "W1", "1W": "W1", "M": "MN", "1M": "MN"}.get(t, t)


def tf_norm(tf) -> str:
    """'1', 'M1', '1m' -> '1' ; '5', 'M5' -> '5'"""
    t = str(tf or "").strip().upper()
    if t.startswith("M") and t[1:].isdigit():
        return t[1:]
    if t.endswith("M") and t[:-1].isdigit():
        return t[:-1]
    return t


ALLOWED_TF = {tf_norm(t) for t in TIMEFRAMES}


def topic_for(tf) -> int | None:
    return TOPIC_BY_TF.get(tf_norm(tf)) or TOPIC_ID


def trade_key(p: dict) -> str:
    tid = val(p, "id")
    return f"{val(p, 'symbol')}|{val(p, 'tf')}|{tid}" if tid else f"{val(p, 'symbol')}|{val(p, 'tf')}"


def open_opposite(symbol: str, tf: str, side: str) -> dict | None:
    with state_lock:
        for k, t in trades.items():
            if k.endswith("|PRE") or not t.get("open"):
                continue
            parts = k.split("|")
            if parts[0] == symbol and parts[1] != tf and t.get("side") and t.get("side") != side:
                return {**t, "key": k}
    return None


def is_duplicate(raw: str) -> bool:
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    now = time.time()
    while recent and now - next(iter(recent.values())) > 600:
        recent.popitem(last=False)
    if h in recent:
        return True
    recent[h] = now
    return False


# ---------------------------------------------------------------- Telegram
def tg(method: str, data: dict):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    for attempt in range(4):
        try:
            r = requests.post(url, json=data, timeout=15)
            j = r.json()
        except Exception as e:
            log.error("Telegram non raggiungibile (%s), tentativo %d", e, attempt + 1)
            time.sleep(2)
            continue
        if j.get("ok"):
            return j["result"]
        if r.status_code == 429:
            wait = j.get("parameters", {}).get("retry_after", 3)
            time.sleep(wait + 1)
            continue
        log.error("Errore Telegram: %s", j.get("description"))
        return None
    return None


def send(text: str, reply_to: int | None = None, topic: int | None = None):
    data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True}}
    if topic:
        data["message_thread_id"] = topic
    if reply_to:
        data["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    res = tg("sendMessage", data)
    return res.get("message_id") if res else None


from cards import render_card, card_recap  # noqa: E402


def send_photo(img: bytes, caption: str, reply_to: int | None = None, topic: int | None = None):
    data = {"chat_id": CHAT_ID, "caption": caption[:1024], "parse_mode": "HTML"}
    if topic:
        data["message_thread_id"] = topic
    if reply_to:
        data["reply_parameters"] = json.dumps({"message_id": reply_to, "allow_sending_without_reply": True})
    for attempt in range(3):
        try:
            r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data=data,
                              files={"photo": ("card.png", img, "image/png")}, timeout=60)
            j = r.json()
            if j.get("ok"):
                return j["result"]["message_id"]
            if r.status_code == 429:
                time.sleep(j.get("parameters", {}).get("retry_after", 3) + 1)
                continue
            log.error("Errore sendPhoto: %s", j.get("description"))
            return None
        except Exception as e:
            log.error("sendPhoto fallito: %s", e)
            time.sleep(2)
    return None


def send_with_card(p: dict, ev: str, text: str, reply_to=None, entry=None, topic=None):
    if ev in CARD_EVENTS:
        try:
            data = dict(p)
            if entry is not None and not val(data, "entry"):
                data["entry"] = entry
            mid = send_photo(render_card(data, ev), text, reply_to, topic)
            if mid:
                return mid
        except Exception as e:
            log.warning("Card non generata: %s", e)
    return send(text, reply_to, topic)


# ---------------------------------------------------------------- commento AI (opzionale)
def ai_comment(p: dict) -> str | None:
    if not AI_COMMENT:
        return None
    facts = {k: v for k, v in p.items() if k not in ("secret", "strength", "lvl", "risk", "reason", "rsi", "tvsym", "id", "volidx", "tfrec")}
    prompt = (
        "Scrivi una sola frase breve, tono professionale e calmo, per un gruppo Telegram di trader "
        "su questa zona di acquisto/vendita dell'indicatore MANUFX. Usa SOLO i dati forniti, non inventare numeri. "
        "Non spiegare mai perché la zona è stata generata. Niente promesse di guadagno, niente emoji. "
        "Non dire mai 'non entrare'.\n\n"
        f"Dati: {json.dumps(facts, ensure_ascii=False)}"
    )
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                          json={"model": OPENAI_MODEL, "messages": [{"role": "user", "content": prompt}],
                                "max_completion_tokens": 80},
                          timeout=10)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("Commento AI non disponibile: %s", e)
        return None


# ---------------------------------------------------------------- testi (formato semplice)
# Formato richiesto:
#   Xauusd sell 4021-4023
#
#   Tp 4014
#   Tp 3946
#
#   Sl 4037
TP_SHOW = [int(x) for x in os.environ.get("TP_SHOW", "1,5").split(",") if x.strip().isdigit()]
SHOW_TF = os.environ.get("SHOW_TF", "off").lower() == "on"
PRICE_DECIMALS = os.environ.get("PRICE_DECIMALS", "")   # vuoto = automatico (oro senza decimali)


def plan_result(r: int, tp1_done: bool) -> float:
    if r >= 1:
        return TP1_PCT / 100 * 1 + REST_PCT / 100 * r
    return TP1_PCT / 100 * 1 if tp1_done else -1.0


def fmt_r(x: float) -> str:
    return f"{x:+.1f}".rstrip("0").rstrip(".") + "R"


def decimals(symbol: str):
    if PRICE_DECIMALS.strip().isdigit():
        return int(PRICE_DECIMALS)
    s = (symbol or "").upper()
    if "XAU" in s or "GOLD" in s or "MGC" in s or s.startswith("GC"):
        return 0
    return None   # altri simboli: prezzo come arriva da TradingView


def px(v, symbol: str) -> str:
    if v is None or str(v).strip() == "":
        return "-"
    d = decimals(symbol)
    if d is None:
        return esc(v)
    try:
        return f"{float(v):.{d}f}"
    except ValueError:
        return esc(v)


def title(symbol: str, side: str, tf=None) -> str:
    """'Xauusd sell'  (con SHOW_TF=on: 'Xauusd M5 sell')"""
    s = esc((symbol or "").capitalize())
    if SHOW_TF and tf:
        s += f" {esc(tf_label(tf))}"
    return f"{s} {esc((side or '').lower())}"


def zone_range(p: dict) -> str:
    sym = val(p, "symbol")
    zb, zt = num(p, "zbot"), num(p, "ztop")
    if zb is not None and zt is not None:
        lo, hi = sorted((zb, zt))
        a, b = px(lo, sym), px(hi, sym)
        return a if a == b else f"{a}-{b}"
    return px(val(p, "price"), sym)


def fmt_zone(p: dict) -> str:
    sym = val(p, "symbol")
    lines = [f"{title(sym, val(p, 'side'), val(p, 'tf'))} {zone_range(p)}", ""]
    for i in TP_SHOW:
        if val(p, f"tp{i}"):
            lines.append(f"Tp {px(val(p, f'tp{i}'), sym)}")
    lines += ["", f"Sl {px(val(p, 'sl'), sym)}"]
    return "\n".join(lines)


def handle(p: dict) -> None:
    ev = (val(p, "event") or "").upper()
    tf_raw = val(p, "tf")
    # 1) solo i timeframe scelti (default M1 e M5)
    if ALLOWED_TF and tf_norm(tf_raw) not in ALLOWED_TF:
        log.info("Scartato %s %s: timeframe %s non pubblicato da questo bot", ev, val(p, "symbol"), tf_raw)
        return

    key = trade_key(p)
    symbol = val(p, "symbol")
    topic = topic_for(tf_raw)
    with state_lock:
        t = trades.get(key, {})
    pre_key = f"{symbol}|{tf_raw}|PRE"
    side_in = (val(p, "side") or "").upper()

    # 2) filtro volatilita' dell'indicatore: spento di default (M1 e M5 sempre)
    tfrec = (val(p, "tfrec") or "").upper()
    tf_ok = (not FOLLOW_TFREC) or (not tfrec) or tfrec == (tf_raw or "").upper()
    def skip_zone(why: str):
        # zona NON pubblicata: la segniamo, cosi' i suoi TP / stop successivi vengono scartati
        log.info("Scartato %s %s %s %s: %s", ev, symbol, tf_raw, side_in, why)
        if ev == "ZONE":
            with state_lock:
                trades[key] = {"skipped": True, "side": side_in, "open": False, "ts": time.time()}
                trades.pop(pre_key, None)
                save_state(trades)

    if ev in ("PRE", "ZONE") and not tf_ok:
        skip_zone(f"timeframe consigliato {tfrec}")
        return
    # 3) un solo setup per direzione sullo stesso simbolo
    if ONE_SIDE and ev in ("PRE", "ZONE"):
        opp = open_opposite(symbol, tf_raw, side_in)
        if opp:
            skip_zone(f"setup {opp.get('side')} ancora aperto ({opp.get('key')})")
            return
    if ev in ("TP", "SL", "TSL", "CLOSE") and t.get("skipped"):
        log.info("Scartato %s %s %s: zona %s non pubblicata", ev, symbol, tf_raw, val(p, "id"))
        return
    # 4) aggiornamento di una zona sconosciuta (non pubblicata o server riavviato)
    if ev in ("TP", "SL", "TSL", "CLOSE") and not t:
        if ev == "TSL" or not tf_ok:
            return
        log.warning("Zona %s sconosciuta (riavvio?): pubblico %s senza risposta", key, ev)
        t = {"msg": None, "side": side_in, "entry": num(p, "entry"), "open": True,
             "tp1": ev == "TP" and (val(p, "level") or "") != "1", "sl": False, "maxr": 0, "recovered": True,
             "symbol": symbol, "tf": tf_raw, "ts": time.time()}
        with state_lock:
            trades[key] = t
            save_state(trades)

    if ev == "PRE":
        txt = (f"{title(symbol, side_in, tf_raw)} {px(val(p, 'price'), symbol)} in formazione\n\n"
               "Potete valutare di iniziare a piazzare il trade, livelli definitivi a breve")
        mid = send(txt, topic=topic)
        with state_lock:
            trades[pre_key] = {"msg": mid, "side": side_in, "id": val(p, "id")}
            save_state(trades)
        return

    if ev == "PRE_KO":
        with state_lock:
            pre = trades.pop(pre_key, {})
            save_state(trades)
        if pre.get("msg"):
            send(f"{title(symbol, pre.get('side') or side_in, tf_raw)} non confermato", pre.get("msg"), topic)
        return

    if ev == "ZONE":
        with state_lock:
            pre = trades.pop(pre_key, {})
            save_state(trades)
        pre_reply = pre.get("msg") if pre.get("side") == side_in else None
        mid = send_with_card(p, "ZONE", fmt_zone(p), pre_reply, topic=topic)
        with state_lock:
            trades[key] = {"msg": mid, "side": side_in, "entry": num(p, "price"),
                           "open": True, "tp1": False, "sl": False, "maxr": 0,
                           "symbol": symbol, "tf": tf_raw, "risk": num(p, "risk"), "ts": time.time()}
            save_state(trades)
        return

    reply = t.get("msg")
    side = t.get("side") or side_in
    tp1_done = bool(t.get("tp1"))
    sl_done = bool(t.get("sl"))
    head = title(symbol, side, tf_raw)

    if ev == "TP":
        lvl = val(p, "level") or "?"
        n = int(lvl) if lvl.isdigit() else 0
        # si pubblicano solo i TP mostrati nel segnale (default TP1 e TP5)
        if n in TP_SHOW:
            txt = f"{head}\n\nTp {px(val(p, 'price'), symbol)} ✅"
            if n == 1:
                txt += f"\nChiudere il {TP1_PCT}% e portare Sl a pareggio"
            elif n == max(TP_SHOW):
                txt += "\nObiettivo finale raggiunto"
            send_with_card(p, "TP", txt, reply, entry=t.get("entry") or num(p, "entry"), topic=topic)
        with state_lock:
            if key in trades:
                if n == 1:
                    trades[key]["tp1"] = True
                trades[key]["maxr"] = max(int(t.get("maxr") or 0), n)
                if n == 5:
                    trades[key]["open"] = False
                save_state(trades)

    elif ev == "SL":
        if tp1_done:
            be = val(p, "entry") or (f"{t.get('entry')}" if t.get("entry") else val(p, "price"))
            p = {**p, "reason": "BE HIT", "plan_r": plan_result(0, True), "price": be}
            txt = f"{head}\n\nSl a pareggio {px(be, symbol)}\n{TP1_PCT}% già chiuso in Tp"
        else:
            txt = f"{head}\n\nSl {px(val(p, 'price'), symbol)} ❌"
        send_with_card(p, "SL", txt, reply, entry=t.get("entry"), topic=topic)
        with state_lock:
            if key in trades:
                trades[key]["sl"] = True
                trades[key]["open"] = False
                save_state(trades)

    elif ev == "CLOSE":
        try:
            r = int(float(val(p, "r") or 0))
        except ValueError:
            r = 0
        if sl_done or r >= 1 or tp1_done:
            with state_lock:
                if key in trades:
                    trades[key]["open"] = False
                    save_state(trades)
            return
        p = {**p, "plan_r": plan_result(r, tp1_done), "tp1_pct": TP1_PCT}
        send_with_card(p, "CLOSE", f"{head}\n\nSetup annullato", reply, topic=topic)
        with state_lock:
            if key in trades:
                trades[key]["open"] = False
                save_state(trades)


# ---------------------------------------------------------------- riepilogo giornaliero
def pip_size(symbol: str) -> float:
    sym = (symbol or "").upper()
    for part in PIP_SIZE.split(","):
        if "=" in part and part.split("=")[0].strip().upper() == sym:
            try:
                return float(part.split("=")[1])
            except ValueError:
                pass
    if "XAU" in sym or "GOLD" in sym or "XAG" in sym:
        return 0.1
    if "JPY" in sym:
        return 0.01
    if any(k in sym for k in ("BTC", "ETH", "US30", "NAS", "SPX", "US100", "US500", "GER", "DAX", "UK100", "USOIL", "WTI")):
        return 1.0
    return 0.0001


def trade_outcome(t: dict):
    tp1, sl, maxr, open_ = bool(t.get("tp1")), bool(t.get("sl")), int(t.get("maxr") or 0), bool(t.get("open"))
    if open_:
        return "APERTO", (plan_result(0, True) if tp1 else None)
    if sl:
        return ("BE", plan_result(0, True)) if tp1 else ("SL", -1.0)
    if maxr >= 1:
        return "TP", plan_result(maxr, True)
    return ("BE", plan_result(0, True)) if tp1 else ("ANNULLATO", -1.0)


def recap_data(day: datetime | None = None) -> dict:
    day = day or datetime.now(TZ)
    with state_lock:
        items = [(k, dict(t)) for k, t in trades.items() if not k.endswith("|PRE")]
    rows = []
    for k, t in items:
        ts = t.get("ts")
        if not ts or t.get("skipped"):
            continue
        born = datetime.fromtimestamp(ts, TZ)
        if born.date() != day.date():
            continue
        sym = t.get("symbol") or k.split("|")[0]
        tf = t.get("tf") or k.split("|")[1]
        state, r = trade_outcome(t)
        risk, ps = t.get("risk"), pip_size(sym)
        pips = (r * risk / ps) if (r is not None and risk) else None
        maxr = int(t.get("maxr") or 0)
        if state == "APERTO":
            label = "in corso" + (f" · TP{maxr}, stop a BE" if maxr else "")
        else:
            label = {"SL": "stop loss", "BE": "pareggio dopo TP1", "TP": f"TP{maxr}", "ANNULLATO": "annullato"}[state]
        rows.append({"time": born.strftime("%H:%M"), "ts": ts, "symbol": sym, "tf": tf, "side": t.get("side") or "",
                     "state": state, "label": label, "r": r, "pips": pips, "maxr": maxr})
    rows.sort(key=lambda x: x["ts"])
    per_tf = {}
    for x in rows:
        per_tf[x["tf"]] = per_tf.get(x["tf"], 0) + 1
    closed = [x for x in rows if x["state"] != "APERTO"]
    return {"date": day.strftime("%d/%m/%Y"), "rows": rows, "per_tf": dict(sorted(per_tf.items())),
            "n": len(rows), "n_open": len(rows) - len(closed), "n_closed": len(closed),
            "n_win": sum(1 for x in closed if (x["r"] or 0) > 0),
            "n_loss": sum(1 for x in closed if (x["r"] or 0) < 0),
            "tot_r": sum(x["r"] for x in rows if x["r"] is not None),
            "tot_pips": sum(x["pips"] for x in rows if x["pips"] is not None),
            "symbols": sorted({x["symbol"] for x in rows})}


def build_recap(data: dict) -> str:
    head = f"Report {data['date']}"
    if not data["rows"]:
        return head + "\n\nNessun segnale oggi"
    out = [head, ""]
    for x in data["rows"]:
        mark = {"TP": "✅", "BE": "✅", "SL": "❌", "ANNULLATO": "➖", "APERTO": "⏳"}[x["state"]]
        res = f" {fmt_r(x['r'])}" if x["r"] is not None else ""
        out.append(f"{mark} {x['time']} {title(x['symbol'], x['side'], x['tf'])} – {esc(x['label'])}{res}")
    out += ["", f"Vinte {data['n_win']} · Perse {data['n_loss']} · In corso {data['n_open']}",
            f"Totale {fmt_r(data['tot_r'])} ({data['tot_pips']:+.0f} pips)"]
    return "\n".join(out)


def send_recap(day: datetime | None = None):
    try:
        data = recap_data(day)
        text = build_recap(data)
        if data["rows"] and "RECAP" in CARD_EVENTS:
            try:
                img = card_recap({**data, "tp1_pct": TP1_PCT})
                if len(text) <= 1000:
                    mid = send_photo(img, text, topic=RECAP_TOPIC)
                else:   # didascalia max 1024 caratteri: titolo sulla foto, report completo in risposta
                    mid = send_photo(img, text.split("\n")[0], topic=RECAP_TOPIC)
                    if mid:
                        send(text, mid, RECAP_TOPIC)
                if mid:
                    return mid
            except Exception as e:
                log.warning("Card riepilogo non generata: %s", e)
        return send(text, topic=RECAP_TOPIC)
    except Exception as e:
        log.warning("Riepilogo non inviato: %s", e)
        return None


def recap_scheduler():
    try:
        hh, mm = (int(x) for x in RECAP_TIME.split(":"))
    except ValueError:
        log.warning("RECAP_TIME non valido: %s", RECAP_TIME)
        return
    while True:
        now = datetime.now(TZ)
        nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        time.sleep(max(1.0, (nxt - datetime.now(TZ)).total_seconds()))
        send_recap()


def worker():
    while True:
        p = jobs.get()
        try:
            handle(p)
        except Exception:
            log.exception("Errore nella gestione del segnale")
        finally:
            jobs.task_done()


def startup_check():
    if not TOKEN or not CHAT_ID:
        log.error("MANCANO TELEGRAM_TOKEN o CHAT_ID nelle variabili di Railway")
        return
    me = tg("getMe", {})
    log.info("Bot Telegram: %s", ("@" + me["username"]) if me else "TOKEN NON VALIDO")
    chat = tg("getChat", {"chat_id": CHAT_ID})
    log.info("Gruppo: %s", chat.get("title") if chat else "CHAT_ID errato oppure il bot non e' nel gruppo")
    if me and chat:
        m = tg("getChatMember", {"chat_id": CHAT_ID, "user_id": me["id"]})
        log.info("Ruolo del bot nel gruppo: %s", m.get("status") if m else "?")
    log.info("Timeframe pubblicati: %s | topic generale %s, M1 %s, M5 %s | chiave webhook %s",
             sorted(ALLOWED_TF), TOPIC_ID, TOPIC_BY_TF["1"], TOPIC_BY_TF["5"], "impostata" if SECRET else "VUOTA")


threading.Thread(target=startup_check, daemon=True).start()
threading.Thread(target=worker, daemon=True).start()
if RECAP_TIME.strip():
    threading.Thread(target=recap_scheduler, daemon=True).start()


# ---------------------------------------------------------------- endpoint
@app.get("/stato")
def stato():
    """/stato?secret=...  ultime zone ricevute e se sono state pubblicate"""
    if not _auth():
        return jsonify(ok=False, error="chiave errata"), 403
    with state_lock:
        items = list(trades.items())[-20:]
    return jsonify(ok=True, ultime=[{"zona": k, "pubblicata": not t.get("skipped"), "aperta": t.get("open"),
                                     "lato": t.get("side")} for k, t in items])


@app.get("/")
def health():
    return jsonify(ok=True, bot="manufx-m1m5", timeframes=sorted(ALLOWED_TF), topic=TOPIC_ID,
                   topic_m1=TOPIC_BY_TF["1"], topic_m5=TOPIC_BY_TF["5"], follow_tfrec=FOLLOW_TFREC,
                   ai=AI_COMMENT, cards=sorted(CARD_EVENTS))


@app.post("/webhook")
def webhook():
    raw = request.get_data(as_text=True) or ""
    log.info("Webhook ricevuto: %s", raw[:300].replace(SECRET, "***") if SECRET else raw[:300])
    try:
        data = json.loads(raw)
        items = data if isinstance(data, list) else [data]
        assert items and all(isinstance(x, dict) for x in items)
    except Exception:
        # l'indicatore manda anche alert di solo testo (breakout, TP ecc.): qui non servono
        return jsonify(ok=True, ignored="non JSON"), 200
    if SECRET and any(p.get("secret") != SECRET for p in items):
        log.warning("Webhook rifiutato: chiave segreta diversa da WEBHOOK_SECRET (controlla l'indicatore e ricrea l'alert)")
        return jsonify(ok=False, error="chiave errata"), 403
    accepted = 0
    for p in items:
        if (val(p, "event") or "").upper() not in TRADE_EVENTS:
            continue
        if is_duplicate(json.dumps(p, sort_keys=True)):
            continue
        jobs.put(p)
        accepted += 1
    return jsonify(ok=True, accepted=accepted)


def _auth():
    return not SECRET or request.args.get("secret") == SECRET


@app.get("/test")
def test():
    if not _auth():
        return jsonify(ok=False, error="chiave errata"), 403
    res = {}
    for tf in ("1", "5"):
        res[tf_label(tf)] = send(f"◆ <b>MANUFX M1 · M5</b>\nTest {tf_label(tf)}: il bot pubblica correttamente qui.", topic=topic_for(tf))
    return jsonify(ok=all(res.values()), messages=res)


@app.get("/test-card")
def test_card():
    """/test-card?secret=...&side=BUY&tf=5"""
    if not _auth():
        return jsonify(ok=False, error="chiave errata"), 403
    side = request.args.get("side", "BUY").upper()
    tf = request.args.get("tf", "5")
    demo = demo_zone(side, tf)
    if request.args.get("dry"):
        return Response(render_card(demo, "ZONE"), mimetype="image/png")
    mid = send_photo(render_card(demo, "ZONE"), fmt_zone(demo), topic=topic_for(tf))
    return jsonify(ok=bool(mid), message_id=mid)


def demo_zone(side="BUY", tf="5"):
    b = side == "BUY"
    d = {"event": "ZONE", "side": side, "symbol": "XAUUSD", "tf": tf, "price": "4186.20", "risk": "4.30",
         "sl": "4181.90" if b else "4190.50", "ztop": "4191.40", "zbot": "4183.60", "inside": "1"}
    for i in range(1, 6):
        d[f"tp{i}"] = f"{4186.20 + (4.30 * i if b else -4.30 * i):.2f}"
    return d


@app.get("/recap")
def recap_now():
    """/recap?secret=...  (&dry=1 testo, &dry=img immagine)"""
    if not _auth():
        return jsonify(ok=False, error="chiave errata"), 403
    dry = request.args.get("dry")
    if dry == "img":
        return Response(card_recap({**recap_data(), "tp1_pct": TP1_PCT}), mimetype="image/png")
    if dry:
        return "<pre>" + build_recap(recap_data()) + "</pre>"
    mid = send_recap()
    return jsonify(ok=bool(mid), message_id=mid)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
