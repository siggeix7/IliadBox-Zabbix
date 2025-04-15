#!/bin/bash

FREEBOX_IP="192.168.1.254"
API_VER="v8"
APP_ID="zabbix.moitoring"
APP_NAME="Freebox Monitor Zabbix"
APP_VERSION="1.0"
DEVICE_NAME="ZABBIX"

echo "[*] Registrazione app al Freebox..."

AUTH_RESPONSE=$(curl -s -X POST http://$FREEBOX_IP/api/$API_VER/login/authorize/ \
  -H "Content-Type: application/json" \
  -d "{
    \"app_id\": \"$APP_ID\",
    \"app_name\": \"$APP_NAME\",
    \"app_version\": \"$APP_VERSION\",
    \"device_name\": \"$DEVICE_NAME\"
}")

APP_TOKEN=$(echo "$AUTH_RESPONSE" | jq -r '.result.app_token')
TRACK_ID=$(echo "$AUTH_RESPONSE" | jq -r '.result.track_id')

if [ "$APP_TOKEN" == "null" ]; then
    echo "[!] Errore durante la registrazione dell'app:"
    echo "$AUTH_RESPONSE"
    exit 1
fi

echo "[✅] App registrata. App token: $APP_TOKEN"
echo "[🔁] Track ID: $TRACK_ID"

# === STEP 2: Polling autorizzazione ===
echo "[🕒] In attesa dell'autorizzazione sul box (60s max)..."
for i in {1..12}; do
  STATUS=$(curl -s http://$FREEBOX_IP/api/$API_VER/login/authorize/$TRACK_ID | jq -r '.result.status')
  echo "  [${i}0s] Stato autorizzazione: $STATUS"
  if [ "$STATUS" == "granted" ]; then
    echo "[✅] Autorizzazione concessa!"
    break
  elif [ "$STATUS" == "denied" ]; then
    echo "[❌] Autorizzazione negata sul box!"
    exit 1
  fi
  sleep 5
done

if [ "$STATUS" != "granted" ]; then
    echo "[!] Timeout: autorizzazione non ricevuta entro 60 secondi."
    exit 1
fi

# === STEP 3: Richiesta challenge ===
echo "[*] Richiesta challenge..."
CHALLENGE=$(curl -s http://$FREEBOX_IP/api/$API_VER/login/ | jq -r '.result.challenge')

if [ -z "$CHALLENGE" ] || [ "$CHALLENGE" == "null" ]; then
    echo "[!] Errore: challenge non ricevuto"
    exit 1
fi

echo "[+] Challenge ricevuto: $CHALLENGE"

# === STEP 4: Calcolo HMAC ===
PASSWORD=$(echo -n "$CHALLENGE" | openssl dgst -sha1 -hmac "$APP_TOKEN" | sed 's/^.*= //')
echo "[+] HMAC calcolato: $PASSWORD"

# === STEP 5: Login sessione ===
echo "[*] Login in corso..."
RESPONSE=$(curl -s -X POST http://$FREEBOX_IP/api/$API_VER/login/session/ \
  -H "Content-Type: application/json" \
  -d "{\"app_id\": \"$APP_ID\", \"password\": \"$PASSWORD\"}")

SUCCESS=$(echo "$RESPONSE" | jq -r '.success')

if [ "$SUCCESS" == "true" ]; then
    SESSION_TOKEN=$(echo "$RESPONSE" | jq -r '.result.session_token')
    echo "[✅] Login riuscito!"
    echo "[🔐] Session token:"
    echo "$SESSION_TOKEN"
else
    echo "[❌] Login fallito:"
    echo "$RESPONSE"
fi
