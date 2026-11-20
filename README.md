# Agente financeiro do casal (WhatsApp)

Cada um conversa com o bot em privado; os dois números compartilham o mesmo caderno.
Quando um registra algo, o outro recebe um aviso. Só usa a biblioteca padrão do Python 3.9+.

## Como usar no WhatsApp

| Mensagem | O que faz |
|---|---|
| `mercado 230` / `gastei 50 no uber` | registra gasto |
| `luz 180 vence 25` / `agua 90 vence 18/12` | conta a pagar |
| `aluguel 1500 todo dia 5` | conta fixa, gerada todo mês |
| `paguei luz` / `paguei luz 185` | dá baixa (opcionalmente corrige o valor) |
| `contas` | o que falta pagar, com atrasadas e próximos vencimentos |
| `resumo` | gastos do mês, por pessoa, maiores gastos e o que falta |
| `desfazer` | desfaz o seu último lançamento |
| `cancelar fixa aluguel` | para de repetir a conta fixa |

Todo dia às 9h (Brasília) ele manda as contas atrasadas ou que vencem em até 2 dias.

## Colocar no ar

1. Em developers.facebook.com, crie um app do tipo **Business** e adicione o produto **WhatsApp**.
2. Em *API Setup* você ganha um número de teste gratuito. Adicione o seu número e o do seu marido como destinatários permitidos.
3. Copie o **token de acesso** e o **Phone number ID**. Copie o **App Secret** em *Settings → Basic*.
4. Configure as variáveis de `.env.example` no seu servidor (Railway, Render, Fly.io ou uma VPS). Em `MEMBERS`, use os números como a Meta envia: DDI+DDD+número, sem `+`. Se um número não funcionar, olhe o log: ele imprime `Número não autorizado: ...` com o formato exato (alguns números antigos chegam sem o 9).
5. Rode `python3 server.py`. É preciso um endereço **https** público.
6. Na Meta, em *WhatsApp → Configuration → Webhook*: URL `https://SEU-ENDERECO/webhook`, token igual a `VERIFY_TOKEN`, e assine o campo **messages**.
7. Mande `ajuda` para o número do bot.

Para testar a lógica sem WhatsApp: `python3 test_bot.py`.

## Limites importantes

- **Janela de 24 horas:** a API só deixa o bot mandar texto livre até 24h depois da sua última mensagem. Os avisos para o outro e o lembrete das 9h podem falhar se ninguém falou com o bot no dia. A solução é criar na Meta um *template* de mensagem com uma variável no corpo (por exemplo, `Lembrete de contas: {{1}}`), aprová-lo e colocar o nome em `REMINDER_TEMPLATE`.
- **Backup:** tudo fica no arquivo `financas.db`. Em hospedagens que apagam o disco a cada deploy, use um volume persistente e faça cópias.
- Sem categorias: o bot usa a primeira palavra como descrição (`Mercado`, `Uber`). Dá para adicionar categorias depois.
