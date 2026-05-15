# IliadBox-Zabbix

Template Zabbix per monitorare una IliadBox/Freebox tramite API Freebox OS.

## Contenuto

- `Iliad Template Zabbix.yaml`: template Zabbix 7.2 da importare.
- `session-token-iliadbox.py`: external check usato dal template per generare un session token.
- `app-token-gen-and-session-token.sh`: utility per registrare l'app sul box e ottenere l'app token.

## Requisiti

- Zabbix 7.2 o compatibile con template export 7.2.
- Python 3 sul server o proxy Zabbix che esegue gli external check.
- `curl`, `jq` e `openssl` solo per lo script di generazione dell'app token.
- Accesso HTTP dal server/proxy Zabbix verso la IliadBox/Freebox.

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
ILIADBOX_TIMEOUT=20 /usr/lib/zabbix/externalscripts/session-token-iliadbox.py '<APP_TOKEN>' 192.168.1.254 v8 zabbix.monitoring
```

## Import Template

1. Importare `Iliad Template Zabbix.yaml` in Zabbix.
2. Creare o selezionare l'host della IliadBox/Freebox.
3. Associare il template `IliadBox` all'host.
4. Configurare le macro sull'host, se diverse dai default.

## Macro

| Macro | Default | Descrizione |
| --- | --- | --- |
| `{$APPTOKEN}` | vuoto | App token generato con `app-token-gen-and-session-token.sh`. |
| `{$APP_ID}` | `zabbix.monitoring` | Deve coincidere con l'App ID usato per generare l'app token. |
| `{$APIVER}` | `v8` | Versione API usata per login e session token. |
| `{$FREEBOXIP}` | `192.168.1.254` | IP o hostname locale del box, senza protocollo. |

## Verifica Rapida

Test manuale dello script external check:

```bash
/usr/lib/zabbix/externalscripts/session-token-iliadbox.py '<APP_TOKEN>' 192.168.1.254 v8 zabbix.monitoring
```

Se il login riesce, il comando stampa solo il session token. Gli errori sono scritti su `stderr`, cosi' l'item Zabbix non riceve testo non valido al posto del token.

## Note Di Sicurezza

- Non inserire app token o session token nel repository.
- Preferire macro host di tipo secret per `{$APPTOKEN}`.
- Limitare l'accesso agli external script ai soli utenti di sistema necessari.
