"""Servidor do webhook do WhatsApp Cloud API (Meta). Só biblioteca padrão.

Os números listados em MEMBERS compartilham o mesmo caderno de gastos.
Configuração por variáveis de ambiente: veja .env.example e README.md.
"""
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import bot


def env(key, default=""):
    return os.environ.get(key, default).strip()


TOKEN = env("WHATSAPP_TOKEN")
PHONE_ID = env("PHONE_NUMBER_ID")
VERIFY = env("VERIFY_TOKEN")
APP_SECRET = env("APP_SECRET")
TEMPLATE = env("REMINDER_TEMPLATE")  # opcional: template aprovado, para lembretes fora da janela de 24h
REMIND_HOUR = int(env("REMIND_HOUR", "9"))
PORT = int(env("PORT", "8080"))
MEMBERS = {k.strip(): v.strip()
           for k, v in (p.split("=", 1) for p in env("MEMBERS").split(",") if "=" in p)}

BRT = timezone(timedelta(hours=-3))
LOCK = threading.Lock()
DB = bot.connect(env("DB_PATH", "financas.db"))


def _post(payload):
    req = urllib.request.Request(
        f"https://graph.facebook.com/v21.0/{PHONE_ID}/messages",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:  # noqa: BLE001
        detail = getattr(e, "read", lambda: b"")()
        print("Falha ao enviar:", e, detail[:300])


def send_text(to, body):
    _post({"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}})


def send_template(to, body):
    _post({"messaging_product": "whatsapp", "to": to, "type": "template",
           "template": {"name": TEMPLATE, "language": {"code": "pt_BR"},
                        "components": [{"type": "body",
                                        "parameters": [{"type": "text", "text": body.replace("\n", " | ")}]}]}})


def process(sender, text):
    name = MEMBERS.get(sender)
    if name is None:
        print("Número não autorizado:", sender, "(adicione em MEMBERS se for seu)")
        return
    with LOCK:
        reply, notice = bot.handle(DB, name, text, datetime.now(BRT).date())
    send_text(sender, reply)
    if notice:
        for number in MEMBERS:
            if number != sender:
                send_text(number, "🔔 " + notice)


def reminders():
    last = None
    while True:
        now = datetime.now(BRT)
        if now.hour == REMIND_HOUR and last != now.date():
            last = now.date()
            with LOCK:
                text = bot.daily_reminder(DB, now.date())
            if text:
                for number in MEMBERS:
                    (send_template if TEMPLATE else send_text)(number, text)
        time.sleep(300)


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, body="ok"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/webhook" and VERIFY and q.get("hub.mode", [""])[0] == "subscribe" \
                and q.get("hub.verify_token", [""])[0] == VERIFY:
            return self._reply(200, q.get("hub.challenge", [""])[0])
        if url.path == "/webhook":
            return self._reply(403, "forbidden")
        self._reply(200, "ok")

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if APP_SECRET:
            expected = "sha256=" + hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, self.headers.get("X-Hub-Signature-256", "")):
                return self._reply(403, "bad signature")
        self._reply(200)
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            return
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    sender = msg.get("from", "")
                    if msg.get("type") == "text":
                        body = msg["text"]["body"]
                        threading.Thread(target=process, args=(sender, body), daemon=True).start()
                    elif sender in MEMBERS:
                        send_text(sender, "Por enquanto só entendo texto 🙂 Mande 'ajuda'.")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    if not (TOKEN and PHONE_ID and VERIFY and MEMBERS):
        print("Faltam variáveis: WHATSAPP_TOKEN, PHONE_NUMBER_ID, VERIFY_TOKEN, MEMBERS (veja .env.example)")
    threading.Thread(target=reminders, daemon=True).start()
    print(f"Agente financeiro no ar na porta {PORT} — webhook em /webhook")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
