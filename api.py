"""
Cliente da API publica de disponibilidade do site de agendamento da PCDF
(CIN de brasileiros no exterior). Serve a vigilancia: nao precisa de browser.
"""
import re
import socket
import unicodedata
from datetime import datetime

import requests
import urllib3.util.connection as urllib3_cn

# O container nao tem rota IPv6; forcar IPv4 (mesmo truque do aima-status).
urllib3_cn.allowed_gai_family = lambda: socket.AF_INET

BASE = "https://agendamento-pcdf-exterior.services-valid.com.br"
_S = requests.Session()
_S.headers["User-Agent"] = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)
_S.headers["Accept"] = "application/json"


def _get(path):
    r = _S.get(f"{BASE}/api/ex/availability{path}", timeout=30)
    r.raise_for_status()
    return r.json() if r.content else []


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def stations():
    """Lista plana de postos: [{id, name, city, address}]."""
    out = []
    for group in _get("/stations"):
        for st in group.get("stations", []):
            out.append({"id": st["id"], "name": st["name"],
                        "city": st.get("city") or group.get("city", ""),
                        "address": st.get("address", "")})
    return out


def find_station(city):
    """Primeiro posto cuja cidade ou nome contem 'city' (sem acentos/maiusculas)."""
    want = norm(city)
    for st in stations():
        if want in norm(st["city"]) or want in norm(st["name"]):
            return st
    return None


def dates(station_id):
    """[{id, value:'08/10/2026 (Quinta-feira)', date:date}] por ordem cronologica."""
    out = []
    for d in _get(f"/{station_id}/dates"):
        m = re.match(r"(\d{2}/\d{2}/\d{4})", d["value"])
        if m:
            out.append({"id": d["id"], "value": d["value"],
                        "date": datetime.strptime(m.group(1), "%d/%m/%Y").date()})
    return sorted(out, key=lambda d: d["date"])


def timeslots(station_id, date_id):
    return _get(f"/{station_id}/dates/{date_id}/timeslots")


def _hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def pick_index(n, urgency):
    """Indice da data a escolher entre n candidatas: MAX = primeira, MIN = ultima,
    MED = a do meio (com n par, a maior das duas do meio)."""
    u = (urgency or "MAX").strip().upper()
    if u == "MAX":
        return 0
    if u == "MIN":
        return n - 1
    if u == "MED":
        return n // 2
    raise ValueError(f"DATE_URGENCY invalida: {urgency!r} (usar MAX, MED ou MIN)")


def find_slot(station_id, start="08:00", end="12:00", urgency="MAX"):
    """Entre os dias com horario em [start, end), escolhe um conforme 'urgency'
    (ver pick_index) e devolve o horario mais cedo desse dia. None se nao houver."""
    lo, hi = _hm(start), _hm(end)
    pick_index(1, urgency)  # valida cedo
    cands = []
    for d in dates(station_id):
        slots = [s for s in timeslots(station_id, d["id"]) if lo <= _hm(s["startAt"]) < hi]
        if slots:
            cands.append({"date": d, "slot": min(slots, key=lambda s: _hm(s["startAt"]))})
            if (urgency or "MAX").strip().upper() == "MAX":
                break  # a primeira chega; poupa pedidos
    return cands[pick_index(len(cands), urgency)] if cands else None
