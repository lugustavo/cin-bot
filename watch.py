"""
Processo principal do container: de N em N minutos (e de poucos em poucos segundos
a volta da hora em que o site liberta vagas) consulta a API publica e, quando o posto
alvo (TARGET_CITY) existir e tiver vaga na janela, corre bot.run().
Estado em data/state.json impede agendar duas vezes e limita tentativas falhadas.
"""
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import api
import bot
import notify

log = logging.getLogger("cin-bot")
STATE = bot.DATA_DIR / "state.json"


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"done": False, "attempts": 0, "station_seen": False, "slot_notified": None}


def save_state(s):
    bot.DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1))


def tick(cfg, state):
    if state["done"]:
        log.info("Agendamento ja concluido (state.done); nada a fazer. Apagar data/state.json para reiniciar.")
        return
    if state["attempts"] >= cfg["max_attempts"]:
        log.warning("%d tentativas falhadas; parado ate apagar data/state.json", state["attempts"])
        return

    st = api.find_station(cfg["city"])
    if not st:
        listed = sorted({s["city"] for s in api.stations()})
        log.info("Posto '%s' nao listado (postos com vagas: %s)", cfg["city"], listed or "nenhum")
        state["station_seen"] = False
        return
    if not state["station_seen"]:
        state["station_seen"] = True
        notify.send(f"<b>Posto {st['city']} apareceu</b>\n{st['name']}")

    found = api.find_slot(st["id"], cfg["start"], cfg["end"], cfg["urgency"])
    if not found:
        log.info("Posto %s listado, sem vaga entre %s e %s", st["city"], cfg["start"], cfg["end"])
        return

    date_value, hhmm = found["date"]["value"], found["slot"]["startAt"]
    log.info("Vaga: %s %s (%s)", date_value, hhmm, st["name"])
    notify.send(f"<b>Vaga em {st['city']}</b>: {date_value} as {hhmm}\n"
                f"{'(ensaio, DRY_RUN=1)' if cfg['dry_run'] else 'a agendar...'}")
    state["attempts"] += 1
    save_state(state)
    try:
        bot.run(st, date_value, hhmm, dry_run=cfg["dry_run"], confirm_final=cfg["confirm_final"])
    except (bot.NoVacancies, bot.SlotUnavailable) as e:
        state["attempts"] -= 1  # a vaga foi levada por outra pessoa: nao e falha do bot
        log.info("Vaga desapareceu antes de agendar (%s); volta a vigiar", e)
        return
    except Exception:
        log.exception("Tentativa %d falhou", state["attempts"])
        return
    if cfg["dry_run"]:
        state["attempts"] = cfg["max_attempts"]  # ensaio corre uma vez so
    else:
        state["done"] = True
        notify.send(f"<b>Agendamento concluido</b> em {st['city']}: {date_value} as {hhmm}.\n"
                    "Confirma no email e guarda o comprovativo.")


def window_bounds(cfg, now):
    """(inicio, fim) da janela rapida mais proxima que ainda nao acabou, ou None."""
    if not cfg["burst"]:
        return None
    tz = ZoneInfo(cfg["burst_tz"])
    now = now.astimezone(tz)
    hh, mm = (int(x) for x in cfg["burst_time"].split(":"))
    for add in range(0, 8):
        day = (now + timedelta(days=add)).date()
        if day.weekday() != cfg["burst_day"]:
            continue
        at = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
        start, end = at - timedelta(minutes=cfg["burst_before"]), at + timedelta(minutes=cfg["burst_after"])
        if end > now:
            return start, end
    return None


def next_sleep(cfg, now=None):
    """Segundos ate a proxima consulta: rapido dentro da janela de libertacao,
    lento fora dela (mas sem passar do inicio da janela)."""
    now = now or datetime.now(ZoneInfo("UTC"))
    normal = cfg["interval"] * 60 + random.randint(0, 60)
    win = window_bounds(cfg, now)
    if not win:
        return normal
    start, end = win
    if start <= now < end:
        return cfg["burst_interval_s"] + random.random() * 2
    return max(1, min(normal, (start - now).total_seconds()))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = {
        "city": os.environ.get("TARGET_CITY", "Lisboa"),
        "start": os.environ.get("SLOT_START", "08:00"),
        "end": os.environ.get("SLOT_END", "12:00"),
        "urgency": os.environ.get("DATE_URGENCY", "MAX").strip().upper(),
        "interval": int(os.environ.get("WATCH_INTERVAL_MIN", "10")),
        "max_attempts": int(os.environ.get("MAX_ATTEMPTS", "3")),
        "dry_run": os.environ.get("DRY_RUN", "1") == "1",
        "confirm_final": os.environ.get("CONFIRM_FINAL", "1") == "1",
        # janela de vigilancia rapida: o site liberta vagas as quintas 16h (Lisboa)
        "burst": os.environ.get("BURST", "1") == "1",
        "burst_day": int(os.environ.get("BURST_DAY", "3")),  # 0=segunda ... 3=quinta
        "burst_time": os.environ.get("BURST_TIME", "16:00"),
        "burst_tz": os.environ.get("BURST_TZ", "Europe/Lisbon"),
        "burst_before": int(os.environ.get("BURST_BEFORE_MIN", "5")),
        "burst_after": int(os.environ.get("BURST_AFTER_MIN", "30")),
        "burst_interval_s": int(os.environ.get("BURST_INTERVAL_S", "30")),
    }
    api.pick_index(1, cfg["urgency"])  # falha ja no arranque se a variavel for invalida
    log.info("cin-bot iniciado: %s", cfg)
    win = window_bounds(cfg, datetime.now(ZoneInfo("UTC")))
    if win:
        log.info("Proxima janela rapida: %s -> %s (%s)", win[0].strftime("%a %d/%m %H:%M"),
                 win[1].strftime("%H:%M"), cfg["burst_tz"])
    while True:
        state = load_state()
        try:
            tick(cfg, state)
        except Exception:
            log.exception("Tick falhou")
        save_state(state)
        time.sleep(next_sleep(cfg))


if __name__ == "__main__":
    main()
