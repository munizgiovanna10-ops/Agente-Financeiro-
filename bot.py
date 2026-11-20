"""Cérebro do agente financeiro do casal: texto entra, banco muda, resposta sai.

Só usa a biblioteca padrão do Python (sqlite3, re, datetime).
"""
import calendar
import re
import sqlite3
import unicodedata
from datetime import date, timedelta

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

HELP = """💰 Como usar:
• mercado 230 → registra um gasto
• luz 180 vence 25 → conta a pagar
• aluguel 1500 todo dia 5 → conta fixa todo mês
• paguei luz → dá baixa na conta
• contas → o que falta pagar
• resumo → gastos do mês
• desfazer → apaga seu último lançamento
• cancelar fixa aluguel → para de repetir"""

SCHEMA = """
create table if not exists expenses(id integer primary key, day text, who text, cents integer, descr text);
create table if not exists bills(id integer primary key, descr text, cents integer, due text,
                                 paid integer default 0, paid_day text, who text, rec_id integer);
create table if not exists recurring(id integer primary key, descr text, cents integer, dom integer, since text);
create table if not exists log(id integer primary key, who text, kind text, ref integer);
"""

HELP_WORDS = {"ajuda", "help", "menu", "oi", "ola", "comandos"}
RESUMO_WORDS = {"resumo", "mes", "gastos", "saldo", "total"}
CONTAS_WORDS = {"contas", "falta", "falta pagar", "pendentes", "pendente", "o que falta", "o que falta pagar"}

AMOUNT_RE = re.compile(r"(?:r\$\s*)?(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)")
REC_RE = re.compile(r"\btodo\s+(?:mes\s+)?dia\s+(\d{1,2})\b")
DUE_RE = re.compile(r"\b(?:venc\w*|dia)(?:\s+(?:em|dia))?\s+(\d{1,2})(?:/(\d{1,2}))?\b")
FILLER_RE = re.compile(
    r"^(?:(?:gastei|gastamos|comprei|compramos|paguei|foi|deu)\s+)?"
    r"(?:(?:de|do|da|no|na|em|com|um|uma|o|a)\s+)*", re.I)


# ---------- utilidades ----------

def connect(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    return conn


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def prep(text):
    """Devolve (original, normalizado) com o mesmo tamanho, para cortar os dois juntos."""
    ro = text.strip()
    t = norm(ro)
    if len(t) != len(ro):
        ro = t
    return ro, t


def blank(s, span):
    a, b = span
    return s[:a] + " " * (b - a) + s[b:]


def brl(cents):
    s = f"{cents / 100:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def to_cents(s):
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    return int(round(float(s) * 100))


def last_day(y, m):
    return calendar.monthrange(y, m)[1]


def next_month(today):
    y = today.year + (1 if today.month == 12 else 0)
    m = today.month % 12 + 1
    return y, m


def parse_entry(text):
    """Devolve (centavos|None, descrição, {'rec': dia|None, 'due': (dia, mês|None)|None})."""
    ro, t = prep(text)
    info = {"rec": None, "due": None}
    m = REC_RE.search(t)
    if m:
        info["rec"] = int(m.group(1))
        t, ro = blank(t, m.span()), blank(ro, m.span())
    m = DUE_RE.search(t)
    if m:
        info["due"] = (int(m.group(1)), int(m.group(2)) if m.group(2) else None)
        t, ro = blank(t, m.span()), blank(ro, m.span())
    cents = None
    m = AMOUNT_RE.search(t)
    if m:
        cents = to_cents(m.group(1))
        t, ro = blank(t, m.span()), blank(ro, m.span())
    desc = re.sub(r"\s+", " ", ro).strip(" -–:,.")
    desc = FILLER_RE.sub("", desc).strip(" -–:,.")
    desc = desc[:1].upper() + desc[1:]
    return cents, desc, info


def resolve_due(day, month, today):
    if not 1 <= day <= 31:
        return None
    if month:
        if not 1 <= month <= 12:
            return None
        try:
            due = date(today.year, month, day)
        except ValueError:
            return None
        if (today - due).days > 31:
            due = date(today.year + 1, month, day)
        return due
    y, m = today.year, today.month
    if day < today.day:
        y, m = next_month(today)
    return date(y, m, min(day, last_day(y, m)))


def log(conn, who, kind, ref):
    conn.execute("insert into log(who, kind, ref) values(?,?,?)", (who, kind, ref))


def fmt_bill(descr, cents, due, today):
    d = date.fromisoformat(due)
    n = (d - today).days
    if n < 0:
        icon, when = "🔴", f"atrasada {-n} dia{'s' if n != -1 else ''}"
    elif n == 0:
        icon, when = "🟠", "vence hoje"
    elif n == 1:
        icon, when = "🟡", "vence amanhã"
    elif n <= 3:
        icon, when = "🟡", f"em {n} dias"
    else:
        icon, when = "⚪", f"em {n} dias"
    return f"{icon} {descr} — {brl(cents)} — {d:%d/%m} ({when})"


# ---------- consultas ----------

def pending(conn):
    return conn.execute("select id, descr, cents, due from bills where paid=0 order by due, id").fetchall()


def falta_line(conn):
    rows = pending(conn)
    if not rows:
        return "Nenhuma conta pendente 🎉"
    total = sum(r[2] for r in rows)
    return f"Falta pagar: {brl(total)} ({len(rows)} conta{'s' if len(rows) != 1 else ''})."


def month_total(conn, today):
    ym = f"{today:%Y-%m}"
    e = conn.execute("select coalesce(sum(cents),0) from expenses where substr(day,1,7)=?", (ym,)).fetchone()[0]
    b = conn.execute("select coalesce(sum(cents),0) from bills where paid=1 and substr(paid_day,1,7)=?", (ym,)).fetchone()[0]
    return e + b


def contas(conn, today):
    rows = pending(conn)
    if not rows:
        return "Nenhuma conta pendente 🎉"
    total = sum(r[2] for r in rows)
    lines = [f"🧾 Falta pagar: {brl(total)}"]
    lines += [fmt_bill(r[1], r[2], r[3], today) for r in rows[:15]]
    if len(rows) > 15:
        lines.append(f"… e mais {len(rows) - 15}")
    return "\n".join(lines)


def resumo(conn, today):
    ym = f"{today:%Y-%m}"
    total = month_total(conn, today)
    union = ("select who, descr, cents c from expenses where substr(day,1,7)=:ym "
             "union all select who, descr, cents c from bills where paid=1 and substr(paid_day,1,7)=:ym")
    by_who = conn.execute(f"select who, sum(c) from ({union}) group by who order by 2 desc", {"ym": ym}).fetchall()
    top = conn.execute(f"select min(descr), sum(c) from ({union}) group by lower(descr) order by 2 desc limit 5",
                       {"ym": ym}).fetchall()
    lines = [f"📊 {MESES[today.month - 1].capitalize()}/{today.year}", f"Gasto até agora: {brl(total)}"]
    lines += [f"• {w or '?'}: {brl(c)}" for w, c in by_who]
    if top:
        lines.append("Maiores: " + ", ".join(f"{d} {brl(c)}" for d, c in top))
    lines.append(falta_line(conn))
    return "\n".join(lines)


def daily_reminder(conn, today, days=2):
    """Texto de lembrete (vencidas + vencendo em até `days` dias) ou None."""
    ensure_recurring(conn, today)
    conn.commit()
    limit = (today + timedelta(days=days)).isoformat()
    rows = conn.execute("select descr, cents, due from bills where paid=0 and due<=? order by due", (limit,)).fetchall()
    if not rows:
        return None
    return "⏰ Contas para olhar:\n" + "\n".join(fmt_bill(d, c, due, today) for d, c, due in rows)


# ---------- ações ----------

def ensure_recurring(conn, today):
    ym = f"{today:%Y-%m}"
    for rid, descr, cents, dom, since in conn.execute(
            "select id, descr, cents, dom, since from recurring").fetchall():
        if ym < since:
            continue
        if conn.execute("select 1 from bills where rec_id=? and substr(due,1,7)=?", (rid, ym)).fetchone():
            continue
        due = date(today.year, today.month, min(dom, last_day(today.year, today.month)))
        conn.execute("insert into bills(descr, cents, due, rec_id) values(?,?,?,?)",
                     (descr, cents, due.isoformat(), rid))


def add_expense(conn, who, cents, desc, today):
    cur = conn.execute("insert into expenses(day, who, cents, descr) values(?,?,?,?)",
                       (today.isoformat(), who, cents, desc))
    log(conn, who, "expense", cur.lastrowid)
    reply = f"✔️ {desc} {brl(cents)}. Total do mês: {brl(month_total(conn, today))}"
    return reply, f"{who} registrou: {desc} {brl(cents)}"


def add_entry(conn, who, text, today):
    cents, desc, info = parse_entry(text)
    if cents is None:
        return "Não entendi 🤔 Exemplo: mercado 230 ou luz 180 vence 25. Mande 'ajuda'.", None
    desc = desc or "Outros"

    if info["rec"]:
        dom = info["rec"]
        if not 1 <= dom <= 31:
            return "Dia inválido. Exemplo: aluguel 1500 todo dia 5", None
        if dom >= today.day:
            since = f"{today:%Y-%m}"
        else:
            y, m = next_month(today)
            since = f"{y}-{m:02d}"
        cur = conn.execute("insert into recurring(descr, cents, dom, since) values(?,?,?,?)",
                           (desc, cents, dom, since))
        log(conn, who, "rec", cur.lastrowid)
        ensure_recurring(conn, today)
        if since == f"{today:%Y-%m}":
            when = "já está em 'contas' neste mês"
        else:
            when = f"começa em {MESES[int(since[5:]) - 1]}"
        return (f"🔁 {desc} {brl(cents)} todo dia {dom} ({when}).",
                f"{who} criou conta fixa: {desc} {brl(cents)} todo dia {dom}")

    if info["due"]:
        due = resolve_due(info["due"][0], info["due"][1], today)
        if due is None:
            return "Data inválida. Exemplo: luz 180 vence 25 ou luz 180 vence 25/12", None
        cur = conn.execute("insert into bills(descr, cents, due, who) values(?,?,?,?)",
                           (desc, cents, due.isoformat(), who))
        log(conn, who, "bill", cur.lastrowid)
        return (f"🧾 {desc} {brl(cents)} vence {due:%d/%m}. {falta_line(conn)}",
                f"{who} anotou conta: {desc} {brl(cents)} vence {due:%d/%m}")

    return add_expense(conn, who, cents, desc, today)


def pay(conn, who, rest, today):
    cents, desc, _ = parse_entry(rest)
    key = norm(desc)
    row = None
    if key:
        for r in pending(conn):
            n = norm(r[1])
            if key in n or n in key:
                row = r
                break
    if row is None:
        if cents:
            return add_expense(conn, who, cents, desc or "Outros", today)
        if not key:
            return "Qual conta você pagou? Veja com 'contas'.", None
        return f"Não achei conta pendente '{desc}'. Veja com 'contas'.", None
    final = cents or row[2]
    conn.execute("update bills set paid=1, paid_day=?, who=?, cents=? where id=?",
                 (today.isoformat(), who, final, row[0]))
    log(conn, who, "pay", row[0])
    return (f"✅ {row[1]} paga ({brl(final)}). {falta_line(conn)}",
            f"{who} pagou: {row[1]} {brl(final)}")


def undo(conn, who):
    row = conn.execute("select id, kind, ref from log where who=? order by id desc limit 1", (who,)).fetchone()
    if not row:
        return "Nada para desfazer."
    lid, kind, ref = row
    msg = "↩️ Desfeito."
    if kind == "expense":
        r = conn.execute("select descr, cents from expenses where id=?", (ref,)).fetchone()
        conn.execute("delete from expenses where id=?", (ref,))
        if r:
            msg = f"↩️ Apaguei o gasto: {r[0]} {brl(r[1])}"
    elif kind == "bill":
        r = conn.execute("select descr, cents from bills where id=?", (ref,)).fetchone()
        conn.execute("delete from bills where id=?", (ref,))
        if r:
            msg = f"↩️ Apaguei a conta: {r[0]} {brl(r[1])}"
    elif kind == "rec":
        r = conn.execute("select descr from recurring where id=?", (ref,)).fetchone()
        conn.execute("delete from recurring where id=?", (ref,))
        conn.execute("delete from bills where rec_id=? and paid=0", (ref,))
        if r:
            msg = f"↩️ Apaguei a conta fixa: {r[0]}"
    elif kind == "pay":
        r = conn.execute("select descr from bills where id=?", (ref,)).fetchone()
        conn.execute("update bills set paid=0, paid_day=null where id=?", (ref,))
        if r:
            msg = f"↩️ {r[0]} voltou para 'a pagar'."
    conn.execute("delete from log where id=?", (lid,))
    return msg


def cancel_fixa(conn, key):
    key = norm(key).strip()
    for rid, descr in conn.execute("select id, descr from recurring").fetchall():
        n = norm(descr)
        if key in n or n in key:
            conn.execute("delete from recurring where id=?", (rid,))
            return f"🛑 Parei de repetir: {descr}. A conta deste mês continua em 'contas' até ser paga."
    return f"Não achei conta fixa '{key}'."


# ---------- entrada principal ----------

def handle(conn, who, text, today=None):
    """Processa uma mensagem. Devolve (resposta, aviso_para_o_outro|None)."""
    today = today or date.today()
    try:
        out = _handle(conn, who, text, today)
        conn.commit()
        return out
    except Exception:
        conn.rollback()
        raise


def _handle(conn, who, text, today):
    ensure_recurring(conn, today)
    ro, t = prep(text)
    t1 = t.rstrip("?!. ")
    if t1 in HELP_WORDS:
        return HELP, None
    if t1 in RESUMO_WORDS:
        return resumo(conn, today), None
    if t1 in CONTAS_WORDS:
        return contas(conn, today), None
    if t1.startswith("desfazer"):
        return undo(conn, who), None
    m = re.match(r"(?:cancelar|parar|remover)\s+fix[ao]s?\s+(.+)", t1)
    if m:
        return cancel_fixa(conn, m.group(1)), None
    m = re.match(r"(?:paguei|pago|pagamos|quitei)\b\s*(.*)", t1)
    if m:
        return pay(conn, who, ro[m.start(1):], today)
    return add_entry(conn, who, ro, today)
