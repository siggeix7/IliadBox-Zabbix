# IliadBox-Zabbix

Template Zabbix per monitorare una IliadBox/Freebox tramite API Freebox OS.

## Monitoraggio Incluso

- WAN/FTTH: stato connessione, rate up/down, banda disponibile, traffico totale, tipo/media connessione.
- FTTH/SFP: link fibra, presenza modulo SFP, segnale ottico, potenza RX/TX in dBm.
- Sistema: firmware, uptime, autenticazione rete operatore, stato disco, temperature e ventole anche tramite discovery.
- LAN: numero host totali, attivi e raggiungibili.
- Switch: discovery porte Ethernet con link, velocita', duplex e numero MAC collegati.
- Wi-Fi: stato globale, power saving, MAC filter, discovery BSS con stato, client associati/autorizzati, cifratura e WPS.
- DHCP, UPnP IGD, DMZ e Samba: stato dei servizi e trigger informativi/di sicurezza.
- Dashboard e grafici: overview con pagine Connessione, Sistema e Rete locale, piu' graph prototype per sensori, ventole, porte switch e BSS Wi-Fi.

## Contenuto

- `Iliad Template Zabbix.yaml`: template Zabbix 7.2 da importare.
- `session-token-iliadbox.py`: external check usato dal template per generare un session token.
- `app-token-gen-and-session-token.sh`: utility per registrare l'app sul box e ottenere l'app token.
- `toggle-port-forwarding-iliadbox.py`: utility interattiva per attivare o disattivare una regola di port forwarding via web UI.

## Requisiti

- Zabbix 7.2 o compatibile con template export 7.2.
- Python 3 sul server o proxy Zabbix che esegue gli external check.
- `curl`, `jq` e `openssl` solo per lo script di generazione dell'app token.
- Accesso HTTP dal server/proxy Zabbix verso la IliadBox/Freebox. HTTPS e' supportato impostando `{$FREEBOX_PROTOCOL}=https`, ma richiede certificati Freebox attendibili per il server/proxy Zabbix.

## Generazione App Token

Lo script usa questi valori predefiniti:

- `FREEBOX_IP=192.168.1.254`
- `API_VER=v8`
- `APP_ID=zabbix.monitoring`
- `APP_NAME="Freebox Monitor Zabbix"`
- `DEVICE_NAME=ZABBIX`

Esecuzione con i valori predefiniti:

```bash
./app-token-gen-and-session-token.sh
```

Esecuzione con IP personalizzato:

```bash
FREEBOX_IP=192.168.1.254 ./app-token-gen-and-session-token.sh
```

Durante l'esecuzione confermare l'autorizzazione dal display o dall'interfaccia del box. Conservare l'`App token`: andra' inserito nella macro `{$APPTOKEN}` del template o dell'host.

## Installazione External Check

Installare lo script Python nella directory `ExternalScripts` del server/proxy Zabbix, ad esempio:

```bash
sudo install -m 0755 session-token-iliadbox.py /usr/lib/zabbix/externalscripts/
```

Verificare il percorso effettivo nel file di configurazione Zabbix:

```bash
grep '^ExternalScripts=' /etc/zabbix/zabbix_server.conf
```

Lo script non richiede pacchetti Python esterni. In caso di rete lenta si puo' aumentare il timeout con `ILIADBOX_TIMEOUT`, ad esempio:

```bash
ILIADBOX_TIMEOUT=20 /usr/lib/zabbix/externalscripts/session-token-iliadbox.py '<APP_TOKEN>' 192.168.1.254 v8 zabbix.monitoring http
```

## Import Template

1. Importare `Iliad Template Zabbix.yaml` in Zabbix.
2. Creare o selezionare l'host della IliadBox/Freebox.
3. Associare il template `IliadBox` all'host.
4. Configurare le macro sull'host, se diverse dai default.

## Gestione Port Forwarding

Lo script `toggle-port-forwarding-iliadbox.py` permette di attivare o disattivare una regola di port forwarding gia' presente sulla IliadBox.

Esecuzione interattiva:

```bash
python3 toggle-port-forwarding-iliadbox.py
```

Lo script chiede:

- URL o IP del router, ad esempio `192.168.1.254`.
- Password web della IliadBox.
- Nome/commento della regola oppure ID numerico.
- Azione: `attiva` o `disattiva`.

Esecuzione con alcuni parametri gia' impostati:

```bash
python3 toggle-port-forwarding-iliadbox.py --router 192.168.1.254 --rule 'test abilitazione' --action attiva
```

La password viene sempre richiesta in modo nascosto. Lo script usa il login della web UI (`/api/latest/login/`) e l'endpoint `/api/latest/fw/redir/`; non usa app token e non salva password o token su disco. La regola viene cercata nel campo commento/nome mostrato nella gestione porte; se piu' regole hanno lo stesso nome, usare l'ID numerico indicato dallo script.

## Dashboard E Grafici

- Dashboard template `IliadBox Overview` con le pagine `Connessione`, `Sistema` e `Rete locale`.
- Grafici classici per traffico WAN, banda disponibile, traffico totale, potenza SFP FTTH, temperature, ventola e host LAN.
- Graph prototype per temperature sensori, velocita ventole, stato porte switch e client BSS Wi-Fi generati dalle discovery rule.

## Macro

| Macro | Default | Descrizione |
| --- | --- | --- |
| `{$APPTOKEN}` | vuoto | App token generato con `app-token-gen-and-session-token.sh`. |
| `{$APP_ID}` | `zabbix.monitoring` | Deve coincidere con l'App ID usato per generare l'app token. |
| `{$APIVER}` | `v8` | Versione API usata per login e session token. |
| `{$FREEBOXIP}` | `192.168.1.254` | IP o hostname locale del box, senza protocollo. |
| `{$FREEBOX_PROTOCOL}` | `http` | Protocollo usato da external check e item JavaScript. Usare `https` solo se la CA Freebox e' trusted da Zabbix. |
| `{$TEMP_WARN}` | `70` | Soglia warning temperatura sensori in gradi Celsius. |
| `{$TEMP_HIGH}` | `80` | Soglia high temperatura sensori in gradi Celsius. |
| `{$FAN_SPEED_MIN}` | `500` | Soglia minima ventola in rpm, valutata dopo 10 minuti di uptime. |

## Trigger Principali

- FTTH down, link fibra non attivo, SFP assente o senza segnale.
- Router riavviato (`uptime < 10m`) e cambio firmware.
- Box non autenticata sulla rete operatore o disco interno in errore.
- Temperature sensori oltre soglia e ventola sotto soglia.

## Verifica Rapida

Test manuale dello script external check:

```bash
/usr/lib/zabbix/externalscripts/session-token-iliadbox.py '<APP_TOKEN>' 192.168.1.254 v8 zabbix.monitoring http
```

Se il login riesce, il comando stampa solo il session token. Gli errori sono scritti su `stderr`, cosi' l'item Zabbix non riceve testo non valido al posto del token.

## Note Di Sicurezza

- Non inserire app token o session token nel repository.
- Non salvare la password web della IliadBox in script, shell history o file di configurazione.
- Preferire macro host di tipo secret per `{$APPTOKEN}`.
- Limitare l'accesso agli external script ai soli utenti di sistema necessari.
- Il master item `wifi.bss.js` rimuove le chiavi Wi-Fi (`key`) dalla risposta prima di restituire il JSON a Zabbix.
- I master item JSON usano `history=0`; i dati storicizzati sono solo gli item dipendenti necessari al monitoraggio.
