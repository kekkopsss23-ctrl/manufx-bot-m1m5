# Bot MANUFX M1 · M5 — secondo gruppo segnali

Bot **separato** dal bot principale (`manufx-bot`): codice, server Railway, token, gruppo e memoria propri.
Il bot principale non viene toccato.

**Cosa fa:** pubblica **sempre** le zone dell'indicatore MANUFX SELL/BUY ZONE su **M1 e M5** (gli altri timeframe vengono ignorati), con la stessa logica del bot principale:
preavviso "in formazione" → zona → TP1…TP5 → stop / pareggio / annullo → report giornaliero alle 21:00.
Formato dei segnali (solo testo):

```
Xauusd sell 4021-4023

Tp 4014
Tp 3946

Sl 4037
```
- I due Tp sono TP1 e TP5 dell'indicatore (`TP_SHOW=1,5`); oro senza decimali (`PRICE_DECIMALS` per cambiarlo).
- TP raggiunti, stop e annulli arrivano in risposta al segnale, nello stesso stile.
- Le card grafiche ci sono ancora ma spente: per attivarle `CARD_EVENTS=ZONE,TP,SL,CLOSE,RECAP`.
- `SHOW_TF=on` aggiunge M1/M5 dopo il simbolo (utile se M1 e M5 vanno nello stesso topic).

Differenze rispetto al bot principale:
- niente filtro volatilità: M1 e M5 escono entrambi (si può riattivare con `FOLLOW_TFREC=on`)
- si può dare un topic diverso a M1 e a M5 (`TOPIC_M1`, `TOPIC_M5`)
- resta la regola "un solo setup per direzione" (`ONE_SIDE=on`): con un BUY aperto non esce un SELL sullo stesso simbolo

## 1. Telegram
1. Crea il **nuovo bot** con @BotFather → copia il token.
2. Aggiungilo al **nuovo gruppo** come amministratore.
3. Prendi gli id: tieni premuto un messaggio → *Copia link* → `https://t.me/c/1234567890/45/678`
   - `CHAT_ID` = `-100` + primo numero → `-1001234567890`
   - topic = secondo numero (`45`). Senza topic, lascia vuoto e pubblica nella chat generale.

## 2. Server (Railway, progetto nuovo)
1. Crea un repo GitHub nuovo (es. `manufx-bot-m1m5`) e carica tutti i file di questa cartella.
2. Railway → *New Project → Deploy from GitHub* → scegli il repo nuovo.
3. *Variables*: copia da `.env.example` (token nuovo, CHAT_ID nuovo, **stessa WEBHOOK_SECRET dell'indicatore**).
4. *Volume* montato su `/data` (così dopo un aggiornamento ricorda le zone aperte).
5. *Settings → Networking → Generate Domain*.
6. Prova: `https://NUOVO-DOMINIO/test?secret=...` (arriva un messaggio per M1 e uno per M5)
   e `https://NUOVO-DOMINIO/test-card?secret=...&side=SELL&tf=1`.

## 3. TradingView
Ogni alert può mandare a un solo indirizzo, quindi per il nuovo gruppo servono **alert nuovi** (quelli del bot principale restano come sono):
1. Grafico XAUUSD **M1** con l'indicatore `MANUFX_ZONE_telegram.pine` → nuovo alert → condizione *Any alert() function call* → Webhook URL = `https://NUOVO-DOMINIO/webhook`.
2. Stessa cosa sul grafico **M5**.

Se hai già alert M1/M5 per il bot principale, lasciali: i nuovi si aggiungono e mandano gli stessi segnali anche al nuovo server.

## Indirizzi utili
| Indirizzo | |
|---|---|
| `/` | stato del bot (timeframe, topic) |
| `/test?secret=` | messaggio di prova nei topic M1 e M5 |
| `/test-card?secret=&side=BUY&tf=5` | card di prova (`&dry=1` per vederla senza inviarla) |
| `/recap?secret=` | report del giorno adesso (`&dry=1` testo, `&dry=img` immagine) |

`python cards.py` genera gli esempi delle card nella cartella `samples/`.
