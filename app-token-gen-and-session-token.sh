#!/usr/bin/env bash
set -euo pipefail

FREEBOX_IP="${FREEBOX_IP:-192.168.1.254}"
API_VER="${API_VER:-v8}"
APP_ID="${APP_ID:-zabbix.monitoring}"
APP_NAME="${APP_NAME:-Freebox Monitor Zabbix}"
APP_VERSION="${APP_VERSION:-1.0}"
DEVICE_NAME="${DEVICE_NAME:-ZABBIX}"
POLL_ATTEMPTS="${POLL_ATTEMPTS:-12}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"

BASE_URL="http://${FREEBOX_IP}/api/${API_VER}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'ERROR: required command not found: %s\n' "$1" >&2
    exit 1
  fi
}

for command_name in curl jq openssl; do
  require_command "$command_name"
done

printf '[*] Registering app on IliadBox/Freebox at %s\n' "$FREEBOX_IP"

AUTH_PAYLOAD=$(jq -n \
  --arg app_id "$APP_ID" \
  --arg app_name "$APP_NAME" \
  --arg app_version "$APP_VERSION" \
  --arg device_name "$DEVICE_NAME" \
  '{app_id: $app_id, app_name: $app_name, app_version: $app_version, device_name: $device_name}')

AUTH_RESPONSE=$(curl --fail --silent --show-error \
  --request POST "${BASE_URL}/login/authorize/" \
  --header "Content-Type: application/json" \
  --data "$AUTH_PAYLOAD")

if ! APP_TOKEN=$(printf '%s' "$AUTH_RESPONSE" | jq -er '.result.app_token'); then
  printf 'ERROR: unable to register app:\n%s\n' "$AUTH_RESPONSE" >&2
  exit 1
fi

if ! TRACK_ID=$(printf '%s' "$AUTH_RESPONSE" | jq -er '.result.track_id'); then
  printf 'ERROR: missing authorization track_id:\n%s\n' "$AUTH_RESPONSE" >&2
  exit 1
fi

printf '[+] App registered. App token: %s\n' "$APP_TOKEN"
printf '[+] Track ID: %s\n' "$TRACK_ID"

printf '[*] Waiting for authorization on the box (%ss max)...\n' "$((POLL_ATTEMPTS * POLL_INTERVAL))"
STATUS=""
for ((attempt = 1; attempt <= POLL_ATTEMPTS; attempt++)); do
  AUTH_STATUS_RESPONSE=$(curl --fail --silent --show-error \
    "${BASE_URL}/login/authorize/${TRACK_ID}")
  STATUS=$(printf '%s' "$AUTH_STATUS_RESPONSE" | jq -r '.result.status // empty')
  ELAPSED="$(((attempt - 1) * POLL_INTERVAL))"

  printf '  [%ss] Authorization status: %s\n' "$ELAPSED" "${STATUS:-unknown}"
  case "$STATUS" in
    granted)
      printf '[+] Authorization granted.\n'
      break
      ;;
    denied)
      printf 'ERROR: authorization denied on the box.\n' >&2
      exit 1
      ;;
  esac

  if ((attempt < POLL_ATTEMPTS)); then
    sleep "$POLL_INTERVAL"
  fi
done

if [[ "$STATUS" != "granted" ]]; then
  printf 'ERROR: authorization not received within %s seconds.\n' "$((POLL_ATTEMPTS * POLL_INTERVAL))" >&2
  exit 1
fi

printf '[*] Requesting challenge...\n'
CHALLENGE_RESPONSE=$(curl --fail --silent --show-error "${BASE_URL}/login/")
if ! CHALLENGE=$(printf '%s' "$CHALLENGE_RESPONSE" | jq -er '.result.challenge'); then
  printf 'ERROR: challenge not found in response:\n%s\n' "$CHALLENGE_RESPONSE" >&2
  exit 1
fi

PASSWORD=$(printf '%s' "$CHALLENGE" | openssl dgst -sha1 -hmac "$APP_TOKEN" | sed 's/^.*= //')

printf '[*] Logging in...\n'
LOGIN_PAYLOAD=$(jq -n \
  --arg app_id "$APP_ID" \
  --arg password "$PASSWORD" \
  '{app_id: $app_id, password: $password}')

RESPONSE=$(curl --fail --silent --show-error \
  --request POST "${BASE_URL}/login/session/" \
  --header "Content-Type: application/json" \
  --data "$LOGIN_PAYLOAD")

if printf '%s' "$RESPONSE" | jq -e '.success == true' >/dev/null; then
  SESSION_TOKEN=$(printf '%s' "$RESPONSE" | jq -r '.result.session_token')
  printf '[+] Login successful.\n'
  printf '[+] Session token:\n%s\n' "$SESSION_TOKEN"
else
  printf 'ERROR: login failed:\n%s\n' "$RESPONSE" >&2
  exit 1
fi
