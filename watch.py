"""
Processo principal do container: de N em N minutos consulta a API publica e,
quando o posto alvo (TARGET_CITY) existir e tiver vaga de manha, corre bot.run().
Estado em data/state.json impede agendar duas vezes e limita tentativas falhadas.
"""
import json
import logging
import os
import random
import time

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
        log.info("Posto '%s' ainda nao listado", cfg["city"])
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
    except Exception:
        log.exception("Tentativa %d falhou", state["attempts"])
        return
    if cfg["dry_run"]:
        state["attempts"] = cfg["max_attempts"]  # ensaio corre uma vez so
    else:
        state["done"] = True
        notify.send(f"<b>Agendamento concluido</b> em {st['city']}: {date_value} as {hhmm}.\n"
                    "Confirma no email e guarda o comprovativo.")


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
    }
    api.pick_index(1, cfg["urgency"])  # falha ja no arranque se a variavel for invalida
    log.info("cin-bot iniciado: %s", cfg)
    while True:
        state = load_state()
        try:
            tick(cfg, state)
        except Exception:
            log.exception("Tick falhou")
        save_state(state)
        time.sleep(cfg["interval"] * 60 + random.randint(0, 60))


if __name__ == "__main__":
    main()
