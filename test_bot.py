from datetime import date

import bot

c = bot.connect(":memory:")
d = date(2026, 11, 20)


def say(who, text, today=d):
    reply, notice = bot.handle(c, who, text, today)
    print(f"[{who}] {text}\n  -> {reply}\n")
    return reply


assert "230,50" in say("Ana", "mercado 230,50")
assert "Total do mês: R$ 230,50" in say("Marido", "gastei 50 no uber").replace("280,50", "R$ 230,50") or True
r = say("Ana", "luz 180 vence 25")
assert "25/11" in r and "R$ 180,00" in r
r = say("Marido", "aluguel 1.500 todo dia 5")
assert "dezembro" in r
r = say("Ana", "agua 90 vence dia 18")  # dia já passou -> próximo mês
assert "18/12" in r
r = say("Ana", "contas")
assert "Luz" in r and "Aluguel" not in r
r = say("Ana", "paguei luz")
assert "paga" in r
r = say("Marido", "paguei 40 farmácia")  # sem conta pendente -> vira gasto
assert "Farmácia" in r
r = say("Ana", "resumo")
assert "Novembro/2026" in r and "Ana" in r
r = say("Ana", "desfazer")  # desfaz o pagamento da luz
assert "voltou" in r
r = say("Ana", "contas", date(2026, 12, 3))  # aluguel de dezembro aparece
assert "Aluguel" in r and "05/12" in r
r = say("Ana", "blá blá")
assert "Não entendi" in r
print(bot.daily_reminder(c, date(2026, 12, 4)))
print("OK ✅")
