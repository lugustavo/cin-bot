"""Obtem o PIN de verificacao: primeiro por IMAP (Gmail), senao pergunta por Telegram."""
import email
import html
import imaplib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import notify

log = logging.getLogger("cin-bot")

_KEYED = re.compile(r"(?:pin|c[oó]digo|codigo|code|token)\D{0,60}?(\d{4,8})", re.I)
_BARE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def _clean(txt):
    """Texto visivel: o remetente marca HTML como text/plain, por isso limpa-se sempre."""
    txt = re.sub(r"(?is)<!--.*?-->|<head.*?</head>|<style.*?</style>|<script.*?</script>", " ", txt)
    return html.unescape(re.sub(r"<[^>]+>", " ", txt))


def _body(msg):
    parts = []
    for p in msg.walk():
        if p.get_content_type() in ("text/plain", "text/html"):
            try:
                txt = p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
            except Exception:
                continue
            parts.append(_clean(txt))
    return " ".join(parts)


def extract_pin(text):
    m = _KEYED.search(text) or _BARE.search(text)
    return m.group(1) if m else None


def _imap_poll(since, timeout):
    host = os.environ.get("IMAP_HOST", "imap.gmail.com")
    user, pw = os.environ.get("IMAP_USER"), os.environ.get("IMAP_PASSWORD")
    hint = re.compile(os.environ.get("PIN_HINT", r"valid\.com|pcdf|services-valid|pol[ií]cia civil|c[oó]digo de valida"), re.I)
    imap = imaplib.IMAP4_SSL(host)
    imap.login(user, pw)
    deadline = time.time() + timeout
    day = (since - timedelta(days=1)).strftime("%d-%b-%Y")
    try:
        while time.time() < deadline:
            for folder in ("INBOX", "[Gmail]/Spam"):
                if imap.select(f'"{folder}"', readonly=True)[0] != "OK":
                    continue
                _, data = imap.search(None, "SINCE", day)
                for num in reversed(data[0].split()[-20:]):
                    _, raw = imap.fetch(num, "(RFC822)")
                    msg = email.message_from_bytes(raw[0][1])
                    try:
                        when = parsedate_to_datetime(msg["Date"])
                    except Exception:
                        continue
                    if when < since - timedelta(seconds=60):
                        continue
                    text = f"{msg.get('From', '')} {msg.get('Subject', '')} {_body(msg)}"
                    if not hint.search(text):
                        continue
                    pin = extract_pin(text)
                    if pin:
                        log.info("PIN encontrado por IMAP em '%s'", folder)
                        return pin
            time.sleep(6)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return None


def get_pin(since=None):
    """'since' = instante (aware) em que o formulario foi submetido."""
    since = since or datetime.now(timezone.utc)
    timeout = int(os.environ.get("PIN_TIMEOUT_S", "240"))
    if os.environ.get("IMAP_USER") and os.environ.get("IMAP_PASSWORD"):
        try:
            pin = _imap_poll(since, timeout)
            if pin:
                return pin
            log.warning("PIN nao chegou por IMAP em %ss", timeout)
        except Exception:
            log.exception("IMAP falhou")
    reply = notify.ask_text(
        "<b>PIN do agendamento</b>\nResponde com o PIN que chegou ao teu email "
        "(o bot esta parado na pagina de verificacao).", timeout=480)
    if reply:
        m = re.search(r"\d{4,8}", reply)
        return m.group(0) if m else reply
    return None
