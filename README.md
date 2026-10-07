# cin-bot

Bot que **vigia o site de agendamento da CIN (Carteira de Identidade Nacional) no exterior**
da Polícia Civil do Distrito Federal e, quando o posto desejado (por omissão, o **Consulado de
Lisboa**) aparece com vaga, **faz o agendamento sozinho**: escolhe o dia e o horário, preenche o
formulário, lê o PIN que chega ao email e confirma. Avisa tudo por Telegram.

Site alvo: <https://agendamento-pcdf-exterior.services-valid.com.br/>

> **Uso pessoal.** Serve para marcar *o teu* atendimento quando as vagas abrem. Não o uses para
> reservar vagas em massa nem para outras pessoas sem autorização. O bot consulta a API pública
> de disponibilidade de 10 em 10 minutos (configurável) e não contorna nenhum captcha.

---

## Índice

1. [Como funciona](#1-como-funciona)
2. [Requisitos](#2-requisitos)
3. [Passo a passo: instalação](#3-passo-a-passo-instalação)
   - [3.1 Obter o projeto](#31-obter-o-projeto)
   - [3.2 Criar o bot do Telegram](#32-criar-o-bot-do-telegram)
   - [3.3 Preparar o Gmail para ler o PIN](#33-preparar-o-gmail-para-ler-o-pin)
   - [3.4 Dados pessoais e anexo](#34-dados-pessoais-e-anexo)
   - [3.5 Ficheiro `.env`](#35-ficheiro-env)
   - [3.6 Arrancar](#36-arrancar)
4. [Referência do `.env`](#4-referência-do-env)
5. [Escolher o dia: `DATE_URGENCY`](#5-escolher-o-dia-date_urgency)
6. [Testar antes de depender dele](#6-testar-antes-de-depender-dele)
7. [Operação do dia a dia](#7-operação-do-dia-a-dia)
8. [Resolução de problemas](#8-resolução-de-problemas)
9. [Segurança e privacidade](#9-segurança-e-privacidade)
10. [Estrutura do projeto](#10-estrutura-do-projeto)
11. [Notas técnicas do site](#11-notas-técnicas-do-site)

---

## 1. Como funciona

```
 a cada WATCH_INTERVAL_MIN minutos (watch.py)
        │
        ▼
 GET /api/ex/availability/stations ──► posto TARGET_CITY listado?  ──não──► espera
        │ sim
        ▼
 GET /{posto}/dates  +  /dates/{id}/timeslots
        │
        ▼
 dias com horário em [SLOT_START, SLOT_END) ──nenhum──► espera
        │
        ▼
 DATE_URGENCY escolhe o dia (MAX / MED / MIN) e o horário mais cedo desse dia
        │
        ▼
 bot.py (Playwright / Chromium sem interface)
   Agendar → posto → dia/hora → formulário (+ PDF) → Continuar
        │
        ▼
 página "Verificação": o site manda um PIN por email
   pin.py lê o PIN no Gmail (IMAP) ── falhou? ──► pede-te o PIN por Telegram
        │
        ▼
 "Validar e-mail" → página de Revisão → botão final → "Solicitação em análise"
        │
        ▼
 Telegram: resultado + captura de ecrã   │   data/state.json: done = true
```

Salvaguardas:

- **Nunca agenda duas vezes**: depois de um sucesso, `data/state.json` fica com `"done": true`.
- **Limite de tentativas**: após `MAX_ATTEMPTS` falhas seguidas o bot pára (evita encher o teu
  email de PINs). Apagar `data/state.json` recomeça.
- **Cada passo e cada erro** ficam em captura de ecrã em `data/shots/` (e as falhas vão ao Telegram).
- Só conta um dia se tiver **vaga dentro da janela horária**; nunca escolhe um dia onde não pode marcar.

## 2. Requisitos

- Uma máquina que fique ligada (servidor, Raspberry, VM, contentor LXC…) com **Docker** e
  **Docker Compose v2.24+** (a variável `env_file` usa `required: false`).
- ~2 GB de RAM livres e ~2,5 GB de disco (a imagem do Playwright/Chromium é grande).
- Acesso à internet (HTTPS) a partir dessa máquina.
- Uma conta **Gmail** (a que vais usar no site; o PIN chega lá) e uma conta **Telegram**.
- O **PDF da certidão** (nascimento/casamento) com até 2 MB, em PDF, JPG ou PNG.

## 3. Passo a passo: instalação

### 3.1 Obter o projeto

```bash
git clone <URL-DO-TEU-REPOSITORIO> cin-bot
cd cin-bot
```

### 3.2 Criar o bot do Telegram

1. No Telegram, abre uma conversa com **@BotFather** e envia `/newbot`. Escolhe nome e
   utilizador; ele devolve o **token** (`123456:ABC...`). Guarda-o; é uma palavra-passe.
2. Descobre o teu **chat id**:
   - Conversa privada: manda qualquer mensagem ao teu bot e abre
     `https://api.telegram.org/bot<TOKEN>/getUpdates`; o número em `"chat":{"id":...}` é o chat id.
   - Canal ou grupo: adiciona o bot como **administrador** e usa o id (os canais começam por `-100`).
3. Mantém o token só no `.env` (ver 3.5). Nunca o colocar no git.

> Se não configurares o Telegram o bot funciona na mesma, mas só escreve nos logs, e o fallback
> de pedir o PIN por Telegram deixa de existir.

### 3.3 Preparar o Gmail para ler o PIN

O PIN chega por email ao endereço que indicares no formulário. O bot lê-o por IMAP.

1. Na conta Google ativa a **verificação em 2 passos**.
2. Ativa o **IMAP**: Gmail → Definições → *Ver todas as definições* → *Reencaminhamento e POP/IMAP*
   → *Ativar IMAP*.
3. Gera uma **palavra-passe de aplicação** em <https://myaccount.google.com/apppasswords>
   (16 caracteres, **sem espaços**). **Não** uses a palavra-passe normal da conta: o Gmail recusa-a em IMAP.
4. Põe `IMAP_USER` (o teu email) e `IMAP_PASSWORD` (a app password) no `.env`.

O bot só procura mensagens **chegadas depois** de submeter o formulário, na caixa de entrada e no
spam, cujo remetente/assunto/corpo casem com `PIN_HINT`. Se o IMAP falhar ou o PIN não chegar a
tempo, o bot **pergunta-te por Telegram** e preenche o que responderes.

### 3.4 Dados pessoais e anexo

A pasta `config/` **não vai para o git** (tem dados pessoais). Cria-a a partir do exemplo:

```bash
cp -r config.example config
cp /caminho/da/tua/certidao.pdf config/certidao.pdf
```

Edita `config/dados.json`:

| Campo | Significado | Valores aceites |
|---|---|---|
| `nome` | Nome completo | texto |
| `cpf` | CPF, só dígitos ou com pontuação | 11 dígitos |
| `cor_pele` | Cor da pele | `Amarela`, `Branca`, `Parda`, `Indígena`, `Preta` |
| `doador_orgaos` | Doador de órgãos | `Sim`, `Não` |
| `telefone_pais` | Indicativo do telemóvel | `BR (+55)`, `PY (+595)`, `PT (+351)` |
| `celular` | Telemóvel, sem indicativo | só dígitos |
| `email` | Email (onde chega o PIN; deve ser o do passo 3.3) | email |
| `logradouro` | Morada | até 200 caracteres |
| `frente` | Nome do ficheiro em `config/` | PDF/JPG/PNG, ≤ 2 MB |
| `verso` | Verso do documento, ou `null` | idem |
| `cin_material` | Material da CIN | `Papel`, `Cartão` |
| `cin_ativo` | Marca a declaração da opção por cartão (renúncia ao papel) | `true`/`false` |

Atenção: escolher **Cartão** implica pagar a taxa **no momento do atendimento**; `cin_ativo: true`
marca a declaração que o site exige para essa opção. Confirma no site o que te interessa antes de
deixares o bot correr.

### 3.5 Ficheiro `.env`

```bash
cp .env.example .env
nano .env        # preenche os valores (ver a tabela na secção 4)
```

Mínimo para funcionar a sério:

```ini
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
IMAP_USER=o.teu@gmail.com
IMAP_PASSWORD=app-password-de-16-caracteres
TARGET_CITY=Lisboa
DATE_URGENCY=MAX
DRY_RUN=0
```

Regras do ficheiro: uma variável por linha, **sem espaços** à volta do `=`, sem comentários na
mesma linha do valor e **sem linhas repetidas** (se houver duas, ganha a última).

### 3.6 Arrancar

```bash
docker compose up -d --build
docker logs -f cin-bot
```

Deves ver uma linha como:

```
cin-bot iniciado: {'city': 'Lisboa', 'start': '08:00', 'end': '13:00', 'urgency': 'MIN', 'interval': 10, ... 'dry_run': False, ...}
Posto 'Lisboa' ainda nao listado
```

Confirma sempre aqui que os valores são os que escreveste no `.env`. Esta linha é a fonte da verdade.

## 4. Referência do `.env`

| Variável | Por omissão | Descrição |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | – | Token do bot (BotFather). Sem ele não há alertas. |
| `TELEGRAM_CHAT_ID` | – | Chat/canal que recebe os alertas. |
| `TARGET_CITY` | `Lisboa` | Texto procurado na cidade/nome do posto (sem distinguir acentos/maiúsculas). |
| `SLOT_START` | `08:00` | Início da janela horária (inclusivo). |
| `SLOT_END` | `12:00` | Fim da janela (**exclusivo**): `13:00` aceita 12:00 e 12:30, mas não 13:00. |
| `DATE_URGENCY` | `MAX` | Que dia escolher: `MAX`, `MED` ou `MIN` (secção 5). Valor inválido impede o arranque. |
| `DRY_RUN` | `1` | `1` = preenche o formulário mas **não submete**. `0` = agenda a sério. |
| `CONFIRM_FINAL` | `1` | `1` = carrega também no botão final da Revisão. `0` = pára na Revisão e manda captura. |
| `WATCH_INTERVAL_MIN` | `10` | Minutos entre consultas (mais um jitter de até 60 s). |
| `MAX_ATTEMPTS` | `3` | Tentativas falhadas antes de parar. |
| `IMAP_HOST` | `imap.gmail.com` | Servidor IMAP. |
| `IMAP_USER` / `IMAP_PASSWORD` | – | Conta e app password. Sem elas, o PIN é pedido por Telegram. |
| `PIN_TIMEOUT_S` | `240` | Segundos à espera do PIN por IMAP antes de recorrer ao Telegram. |
| `PIN_HINT` | `valid\.com\|pcdf\|services-valid\|pol[ií]cia civil\|c[oó]digo de valida` | Regex que identifica o email do PIN (remetente, assunto ou corpo). |

Depois de alterar o `.env`, **reinicia** o container (secção 7); não há recarga automática.

## 5. Escolher o dia: `DATE_URGENCY`

O site pode listar vários dias. O bot considera só os dias **com pelo menos um horário na janela**
(`SLOT_START` a `SLOT_END`) e escolhe entre eles; no dia escolhido apanha sempre o **horário mais cedo**.

| Valor | Escolhe | Exemplo com 5 dias com vaga |
|---|---|---|
| `MAX` | o **primeiro** dia (mais urgente) | 1.º |
| `MED` | o dia **do meio**; com número par, o maior dos dois do meio | 3.º (e com 4 dias, o 3.º) |
| `MIN` | o **último** dia (menos urgente) | 5.º |

Com 1 dia disponível os três dão o mesmo resultado.

## 6. Testar antes de depender dele

Corre sempre um ensaio antes de contares com o bot. Há duas formas, ambas dentro do container.

**Ensaio sem submeter** (preenche tudo, tira uma captura e **não** carrega em *Continuar*):

```bash
docker compose run --rm -T cin-bot python bot.py --city <OutroPosto>
# captura em data/shots/*-formulario.png
```

Usa um posto que exista hoje no site (a lista está em `/api/ex/availability/stations`).

**Ensaio a sério** (cria um agendamento real, útil para validar PIN e Revisão):

```bash
docker compose run --rm -T cin-bot python bot.py --city <OutroPosto> --live
```

⚠️ Isto **marca de verdade**. Só o faças se conseguires **cancelar logo a seguir** em
*Cancelar ou consultar agendamento* (precisas do CPF e do email). O site só deixa cancelar **até
4 horas antes** do atendimento; depois disso, ou se faltares, há **15 dias de espera** para
reagendar. Um pedido ativo no teu CPF pode também impedir um novo agendamento: cancela os testes
antes de o posto real abrir. Estes ensaios usam o `.env` (Telegram e IMAP) e `CONFIRM_FINAL` tal como está.

## 7. Operação do dia a dia

```bash
docker logs -f cin-bot                              # ver o que está a fazer
docker compose up -d --force-recreate               # reiniciar (aplica alterações do .env)
docker compose up -d --build                        # reconstruir depois de mudar código
docker compose stop                                 # parar o vigia
cat data/state.json                                 # estado: done / attempts / station_seen
rm data/state.json                                  # recomeçar (limpa done e tentativas)
ls data/shots/                                      # capturas de cada passo e de erros
```

Alertas que recebes por Telegram:

| Mensagem | Quando |
|---|---|
| **Posto … apareceu** | o posto alvo passou a constar da lista |
| **Vaga em …** | há dia/horário na janela (e vai tentar agendar) |
| **Pagina final** + captura | resposta do site depois do botão final |
| **Agendamento concluido** | sucesso; confirma o email e guarda o comprovativo |
| **Falha no agendamento** + captura | erro num passo (URL onde parou) |
| **PIN do agendamento** | o IMAP não achou o PIN; responde com o código |

## 8. Resolução de problemas

| Sintoma | Causa provável e solução |
|---|---|
| `Posto 'Lisboa' ainda nao listado` | Normal enquanto o consulado não abre agenda. O bot continua a vigiar. |
| Arranque mostra um valor diferente do que escreveste no `.env` | Linha repetida, erro de gravação ou ficheiro errado. Corre `grep -n NOME_DA_VARIAVEL .env` e deixa só uma linha. Reinicia e confere a linha `cin-bot iniciado`. |
| `ValueError: DATE_URGENCY invalida` | Usa exatamente `MAX`, `MED` ou `MIN`. |
| Telegram não recebe nada | Token ou chat id errados; no caso de canais, o bot tem de ser administrador. Teste: `python bot.py --city <Posto>` envia uma mensagem "Ensaio ok". |
| `login IMAP: FALHOU` | IMAP desativado, 2 passos desligados, ou a app password tem espaços/está errada. |
| O PIN não é encontrado por IMAP | O email caiu noutra pasta, ou `PIN_HINT` não casa. O bot recorre ao Telegram; se quiseres IMAP, ajusta `PIN_HINT`. |
| Falha no formulário | Vê `data/shots/*-erro.png`. Costuma ser um campo novo ou um texto de opção que mudou no site. |
| O bot parou e não tenta mais | Atingiu `MAX_ATTEMPTS` ou `done`. Vê `data/state.json`; apaga-o para recomeçar. |
| `docker compose` recusa `required: false` | Compose antigo. Atualiza para v2.24+ ou remove essa opção e cria um `.env` (mesmo vazio). |

## 9. Segurança e privacidade

- **Nunca** coloques no git: `.env`, `config/`, `data/` (tudo já está no `.gitignore`).
  Contêm o token do Telegram, a app password do Gmail, o teu CPF/morada, o documento e capturas
  com os teus dados.
- O `.env` do servidor tem permissões `rw-rw-r--` por omissão; se a máquina for partilhada, aperta com
  `chmod 600 .env`.
- A **app password** só dá acesso ao Gmail por IMAP/SMTP e pode ser revogada a qualquer momento em
  <https://myaccount.google.com/apppasswords>. Se o token do Telegram vazar, revoga-o no BotFather
  com `/revoke`.
- As capturas em `data/shots/` mostram CPF, nome e morada: apaga-as quando já não precisares.
- Ao reportar um problema (issue, chat), **tapa** token, e-mails e documentos nas capturas e nos logs.

## 10. Estrutura do projeto

```
cin-bot/
├── watch.py            # processo principal: loop de vigilância + estado + limites
├── bot.py              # fluxo no browser (Playwright): posto, data, formulário, PIN, revisão
├── api.py              # cliente da API pública de disponibilidade (postos, dias, horários, DATE_URGENCY)
├── pin.py              # obtém o PIN: IMAP (Gmail) → fallback Telegram
├── notify.py           # Telegram: mensagens, fotos, pedido de texto
├── Dockerfile          # imagem baseada em mcr.microsoft.com/playwright/python
├── docker-compose.yml  # serviço cin-bot; monta ./data e ./config
├── requirements.txt    # playwright, requests, python-dotenv
├── .env.example        # modelo do .env (copiar para .env)
├── config.example/     # modelo de config/dados.json (dados fictícios)
├── config/             # (NÃO versionado) dados.json + anexo (PDF)
└── data/               # (NÃO versionado) state.json, shots/ (capturas)
```

## 11. Notas técnicas do site

Úteis se o site mudar e for preciso ajustar o bot.

- Frontend Next.js; páginas: `/` → `/agendamento/localizacao` → `/agendamento/data-hora` →
  `/agendamento/dados-pessoais` → verificação (PIN) → revisão.
- API de leitura (sem autenticação): `GET /api/ex/availability/stations`,
  `/api/ex/availability/{posto}/dates`, `/api/ex/availability/{posto}/dates/{id}/timeslots`.
- Os selects são componentes **Radix** (botão `role=combobox` + lista `role=option`); o posto é um
  `button[role=radio]` com `id` igual ao id do posto; o formulário é um acordeão de 4 secções.
- Botões que o bot usa: **Agendar**, **Continuar**, **Validar e-mail** (na verificação) e um
  botão final na Revisão (`confirmar|finalizar|concluir|agendar|enviar|solicitar`, ignorando
  "Reenviar código"). Se o site renomear algum, o passo falha com captura de ecrã.
- O email do PIN vem de `noreply-plataforma@valid.com`, assunto *"Código de validação da
  solicitação"*, com 6 dígitos. O corpo vem marcado como `text/plain` mas é **HTML**, por isso o
  `pin.py` limpa sempre as tags, estilos e comentários antes de procurar o código.
- Validado de ponta a ponta em 07/10/2026 com um agendamento real de teste (posto de Assunção),
  depois cancelado. O posto de Lisboa ainda não existia na lista nessa data.
