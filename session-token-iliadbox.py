#!/usr/bin/python3
import sys
import requests
import hashlib
import hmac
import json

# === CHECK ARGOMENTI ===
if len(sys.argv) < 2:
    print("[❌] Nessun argomento fornito")
    sys.exit(1)

APP_TOKEN = sys.argv[1]
FREEBOX_IP = sys.argv[2]
API_VER = sys.argv[3]
APP_ID = sys.argv[4]

# === RICHIESTA CHALLENGE ===
try:
    response = requests.get(f"http://{FREEBOX_IP}/api/{API_VER}/login/")
    challenge = response.json().get("result", {}).get("challenge")
    if not challenge:
        raise ValueError("Challenge non ricevuto o nullo.")
except Exception as e:
    print(f"[❌] Errore nella richiesta del challenge: {e}")
    sys.exit(1)

# === CALCOLO HMAC ===
try:
    digest = hmac.new(APP_TOKEN.encode(), challenge.encode(), hashlib.sha1).hexdigest()
except Exception as e:
    print(f"[❌] Errore nel calcolo dell'HMAC: {e}")
    sys.exit(1)

# === LOGIN ===
try:
    url_login = f"http://{FREEBOX_IP}/api/{API_VER}/login/session/"
    payload = {
        "app_id": APP_ID,
        "password": digest
    }
    response = requests.post(url_login, headers={"Content-Type": "application/json"}, data=json.dumps(payload))
    data = response.json()
    if data.get("success") == True:
        session_token = data.get("result", {}).get("session_token")
        if session_token:
            print(session_token)
            sys.exit(0)
        else:
            raise ValueError("Session token non presente nella risposta.")
    else:
        print("[❌] Login fallito:")
        print(json.dumps(data, indent=2))
        sys.exit(1)
except Exception as e:
    print(f"[❌] Errore nella richiesta di login: {e}")
    sys.exit(1)
