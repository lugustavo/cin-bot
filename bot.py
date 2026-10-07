"""
Fluxo de agendamento no site da PCDF (CIN no exterior), via Playwright:
  Agendar -> posto -> dia/horario -> dados pessoais -> PIN (email) -> revisao.

Uso manual (dentro do container):
  python bot.py --city Assuncao            # ensaio: preenche e NAO submete
  python bot.py --city Lisboa --live       # agenda a serio
"""
import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import expect, sync_playwright

import api
import notify
import pin as pinmod

log = logging.getLogger("cin-bot")

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "config"))
SHOTS = DATA_DIR / "shots"
STEP_TIMEOUT = 45_000


def load_dados():
    return json.loads((CONFIG_DIR / "dados.json").read_text(encoding="utf-8"))


def shot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{datetime.now():%Y%m%d-%H%M%S}-{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:
        log.exception("screenshot falhou")
        return None
    return str(path)


def choose(page, combo, text):
    """Abre um select Radix e escolhe a opcao cujo texto e exatamente 'text'."""
    combo.click()
    pattern = re.compile(rf"^\s*{re.escape(text)}\s*$")
    opt = page.locator('[role="option"]:visible').filter(has_text=pattern)
    try:
        opt.first.wait_for(timeout=30_000)
    except PWTimeout:
        opt = page.get_by_text(text, exact=True).locator("visible=true")
    opt.first.click()


def type_into(page, selector, value):
    el = page.locator(selector).first
    el.click()
    el.fill("")
    el.press_sequentially(value, delay=25)
    el.blur()


def open_section(page, title):
    trigger = page.locator('button[id^="radix-"]').filter(has_text=title).first
    if trigger.get_attribute("aria-expanded") != "true":
        trigger.click()
        page.wait_for_timeout(400)


def step_inicio(page):
    page.goto(api.BASE + "/", wait_until="domcontentloaded", timeout=60_000)
    page.get_by_role("button", name="Agendar", exact=True).click()
    page.wait_for_url("**/agendamento/localizacao", timeout=STEP_TIMEOUT)


def step_posto(page, station_id):
    radio = page.locator(f'button[role="radio"][id="{station_id}"]')
    radio.wait_for(timeout=STEP_TIMEOUT)
    radio.click()
    page.get_by_role("button", name="Continuar").click()
    page.wait_for_url("**/agendamento/data-hora", timeout=STEP_TIMEOUT)


def step_data_hora(page, date_value, time_str):
    choose(page, page.get_by_role("combobox", name="Selecione o dia"), date_value)
    choose(page, page.get_by_role("combobox", name="Selecione o horário"), time_str)
    page.get_by_role("button", name="Continuar").click()
    page.wait_for_url("**/agendamento/dados-pessoais", timeout=STEP_TIMEOUT)


def step_dados(page, d):
    open_section(page, "Dados pessoais")
    type_into(page, 'input[name="name"]', d["nome"])
    type_into(page, 'input[name="cpf"]', re.sub(r"\D", "", d["cpf"]))
    choose(page, page.get_by_role("combobox", name="Cor da pele"), d["cor_pele"])
    choose(page, page.get_by_role("combobox", name="Doador de órgãos"), d["doador_orgaos"])

    open_section(page, "Contato e endereço")
    choose(page, page.get_by_role("combobox").filter(has_text=re.compile(r"\(\+\d+\)")).first,
           d["telefone_pais"])
    type_into(page, 'input[name="phone"]', re.sub(r"\D", "", d["celular"]))
    type_into(page, 'input[name="email"]', d["email"])
    type_into(page, 'input[name="address"]', d["logradouro"])

    open_section(page, "Anexos")
    files = page.locator('input[type="file"]')
    files.nth(0).set_input_files(str(CONFIG_DIR / d["frente"]))
    if d.get("verso"):
        files.nth(1).set_input_files(str(CONFIG_DIR / d["verso"]))
    page.wait_for_timeout(1500)  # upload

    open_section(page, "Tipo da CIN")
    choose(page, page.get_by_role("combobox", name="Escolha o material da CIN"), d["cin_material"])
    page.wait_for_timeout(500)
    if d.get("cin_ativo"):
        box = page.get_by_role("checkbox")
        if box.count():
            if box.first.get_attribute("aria-checked") != "true" and not box.first.is_checked():
                box.first.check()
        else:
            sw = page.get_by_role("switch")
            if sw.count():
                sw.first.click()
            else:
                log.warning("Checkbox 'Ativo' nao encontrada na pagina")


def form_errors(page):
    try:
        return [t.strip() for t in page.locator(
            '[role="alert"], [aria-invalid="true"] ~ *, p[id$="-message"], [class*="error"]'
        ).all_inner_texts() if t.strip()][:10]
    except Exception:
        return []


def step_pin(page, since):
    page.wait_for_load_state("networkidle", timeout=STEP_TIMEOUT)
    inputs = page.locator("main input:visible")
    inputs.first.wait_for(timeout=STEP_TIMEOUT)
    log.info("Pagina de verificacao: %s (%d inputs)", page.url, inputs.count())
    shot(page, "verificacao")
    code = pinmod.get_pin(since)
    if not code:
        raise RuntimeError("PIN nao obtido")
    if inputs.count() == 1:
        inputs.first.fill(code)
    else:  # um input por digito
        inputs.first.click()
        page.keyboard.type(code, delay=120)
    page.wait_for_timeout(500)
    url_before = page.url
    page.get_by_role("button", name=re.compile(r"^\s*(validar|continuar|confirmar|verificar)", re.I)).first.click()
    try:
        page.wait_for_url(lambda u: u != url_before, timeout=STEP_TIMEOUT)
    except PWTimeout:
        raise RuntimeError(f"PIN nao aceite (pagina nao avancou): {form_errors(page)}")


def step_revisao(page, confirm):
    page.wait_for_load_state("networkidle", timeout=STEP_TIMEOUT)
    img = shot(page, "revisao")
    text = page.locator("main").inner_text()[:900]
    if not confirm:
        notify.send(f"<b>Revisao (sem confirmar)</b>\n{text}", img)
        return text
    names = [t.strip() for t in page.locator("main button:visible").all_inner_texts()]
    log.info("Revisao: botoes %s", names)
    btn = page.get_by_role("button", name=re.compile(r"^\s*(confirmar|finalizar|concluir|agendar|enviar|solicitar)", re.I))
    if not btn.count():
        raise RuntimeError(f"Botao final nao encontrado na Revisao; botoes: {names}")
    btn.last.click()
    page.wait_for_load_state("networkidle", timeout=STEP_TIMEOUT)
    page.wait_for_timeout(2500)
    final = page.locator("main").inner_text()[:900]
    notify.send(f"<b>Pagina final</b>\n{final}", shot(page, "final"))
    return final


def run(station, date_value, time_str, dry_run=True, confirm_final=True):
    """Devolve texto final da pagina; levanta excecao se algum passo falhar."""
    dados = load_dados()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo",
                                  viewport={"width": 1280, "height": 1000})
        ctx.set_default_timeout(STEP_TIMEOUT)
        page = ctx.new_page()
        try:
            step_inicio(page)
            step_posto(page, station["id"])
            step_data_hora(page, date_value, time_str)
            step_dados(page, dados)
            img = shot(page, "formulario")
            if dry_run:
                notify.send(f"<b>Ensaio ok</b> ({station['city']} {date_value} {time_str})\n"
                            "Formulario preenchido; nao submetido (DRY_RUN=1).", img)
                return "dry-run"
            since = datetime.now(timezone.utc)
            page.get_by_role("button", name="Continuar").click()
            try:
                page.wait_for_url(lambda u: "dados-pessoais" not in u, timeout=STEP_TIMEOUT)
            except PWTimeout:
                raise RuntimeError(f"Formulario nao avancou: {form_errors(page)}")
            step_pin(page, since)
            return step_revisao(page, confirm_final)
        except Exception:
            img = shot(page, "erro")
            notify.send(f"<b>Falha no agendamento</b>\npasso em {page.url}", img)
            raise
        finally:
            browser.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default=os.environ.get("TARGET_CITY", "Lisboa"))
    ap.add_argument("--live", action="store_true", help="submete a serio (DRY_RUN=0)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    st = api.find_station(a.city)
    if not st:
        sys.exit(f"Posto '{a.city}' nao listado: {[s['city'] for s in api.stations()]}")
    found = api.find_slot(st["id"], os.environ.get("SLOT_START", "08:00"), os.environ.get("SLOT_END", "12:00"),
                         os.environ.get("DATE_URGENCY", "MAX"))
    if not found:
        sys.exit("Sem vaga de manha neste momento")
    dry = not a.live
    log.info("Posto %s | %s %s | dry_run=%s", st["name"], found["date"]["value"], found["slot"]["startAt"], dry)
    print(run(st, found["date"]["value"], found["slot"]["startAt"], dry_run=dry,
              confirm_final=os.environ.get("CONFIRM_FINAL", "1") == "1"))


if __name__ == "__main__":
    main()
