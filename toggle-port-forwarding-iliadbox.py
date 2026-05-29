#!/usr/bin/env python3
import argparse
import ast
import getpass
import hashlib
import hmac
import http.cookiejar
import json
import math
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_ROUTER = "192.168.1.254"
API_PATH = "/api/latest"
WEB_HEADERS = {
    "X-FBX-FREEBOX0S": "1",
    "X-Fbx-App-Id": "fr.freebox.mafreebox",
}
EDITABLE_RULE_FIELDS = (
    "enabled",
    "wan_port_start",
    "wan_port_end",
    "ip_proto",
    "lan_ip",
    "lan_port",
    "src_ip",
    "comment",
)


class IliadBoxError(RuntimeError):
    pass


def normalize_router_url(value):
    value = value.strip().rstrip("/")
    if not value:
        raise IliadBoxError("URL/IP del router mancante")
    if "://" not in value:
        value = "http://" + value

    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise IliadBoxError("URL router non valido. Esempio: 192.168.1.254")

    return f"{parsed.scheme}://{parsed.netloc}"


def prompt_if_missing(value, label, default=None):
    if value:
        return value
    suffix = f" [{default}]" if default else ""
    answer = input(f"{label}{suffix}: ").strip()
    if not answer and default is not None:
        return default
    return answer


def parse_action(value):
    if value is None:
        return None

    normalized = value.strip().lower()
    enable_values = {"a", "attiva", "attivare", "abilita", "abilitare", "enable", "on", "1", "true"}
    disable_values = {"d", "disattiva", "disattivare", "disabilita", "disabilitare", "disable", "off", "0", "false"}

    if normalized in enable_values:
        return True
    if normalized in disable_values:
        return False
    raise IliadBoxError("Azione non valida: usa 'attiva' o 'disattiva'")


def prompt_action(value):
    if value:
        return parse_action(value)

    while True:
        answer = input("Azione [attiva/disattiva]: ").strip()
        try:
            return parse_action(answer)
        except IliadBoxError as error:
            print(error, file=sys.stderr)


def js_round(value):
    return math.floor(value + 0.5)


def js_unescape(value):
    return urllib.parse.unquote(value)


def js_literal(value):
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError) as error:
        raise IliadBoxError(f"Impossibile leggere stringa JavaScript: {value}") from error


def split_js_statements(script):
    statements = []
    start = 0
    quote = None
    escaped = False

    for index, char in enumerate(script):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in ("'", '"'):
            quote = char
        elif char == ";":
            statements.append(script[start:index].strip())
            start = index + 1

    tail = script[start:].strip()
    if tail:
        statements.append(tail)
    return [statement for statement in statements if statement]


def parse_js_object(value, env):
    inner = value.strip()[1:-1].strip()
    result = {}
    if not inner:
        return result

    for item in inner.split(","):
        key, raw_value = item.split(":", 1)
        result[key.strip().strip("'\"")] = parse_js_value(raw_value.strip(), env)
    return result


def parse_js_value(value, env):
    value = value.strip()
    if value.startswith("{") and value.endswith("}"):
        return parse_js_object(value, env)
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        return js_literal(value)
    return eval_js_expression(value, env)


def parse_js_env(prefix):
    env = {}
    for statement in split_js_statements(prefix):
        match = re.fullmatch(r"var\s+([A-Za-z_$][\w$]*)\s*=\s*(.+)", statement)
        if not match:
            continue
        env[match.group(1)] = parse_js_value(match.group(2), env)
    return env


def prepare_js_expression(expression, env):
    expression = expression.strip().replace("Math.round", "js_round")

    def replace_length(match):
        name = match.group(1)
        if name not in env:
            raise IliadBoxError(f"Variabile JavaScript sconosciuta: {name}")
        return str(len(env[name]))

    def replace_property(match):
        obj_name, prop_name = match.group(1), match.group(2)
        obj = env.get(obj_name)
        if not isinstance(obj, dict) or prop_name not in obj:
            return match.group(0)
        return repr(obj[prop_name])

    expression = re.sub(r"\b([A-Za-z_$][\w$]*)\.length\b", replace_length, expression)
    expression = re.sub(r"\b([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\b", replace_property, expression)
    return expression


def eval_ast_node(node, env):
    if isinstance(node, ast.Expression):
        return eval_ast_node(node.body, env)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise IliadBoxError(f"Variabile JavaScript sconosciuta: {node.id}")
    if isinstance(node, ast.UnaryOp):
        operand = eval_ast_node(node.operand, env)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
    if isinstance(node, ast.BinOp):
        left = eval_ast_node(node.left, env)
        right = eval_ast_node(node.right, env)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Mod):
            return left % right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "js_round":
        if len(node.args) != 1:
            raise IliadBoxError("Math.round non valido nel challenge")
        return js_round(eval_ast_node(node.args[0], env))

    raise IliadBoxError("Espressione JavaScript non supportata nel challenge")


def eval_js_expression(expression, env=None):
    env = env or {}
    expression = prepare_js_expression(expression, env)
    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise IliadBoxError(f"Espressione JavaScript non valida: {expression}") from error
    return eval_ast_node(parsed, env)


def eval_js_script_number(script):
    env = parse_js_env(script)
    statements = split_js_statements(script)
    expression = statements[-1]
    value = eval_js_expression(expression, env)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return int(value)


def int_to_base(value, base):
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if base < 2 or base > len(digits):
        raise IliadBoxError(f"Base numerica non supportata nel challenge: {base}")
    if value == 0:
        return "0"

    sign = ""
    if value < 0:
        sign = "-"
        value = -value

    result = ""
    while value:
        value, remainder = divmod(value, base)
        result = digits[remainder] + result
    return sign + result


def eval_decode_uri_component(part):
    encoded = re.findall(r"unescape\('([^']+)'\)", part)
    if len(encoded) < 2:
        raise IliadBoxError("Challenge decodeURIComponent non riconosciuto")

    char_code = eval_js_script_number(js_unescape(encoded[0]))
    base = eval_js_script_number(js_unescape(encoded[1]))
    escaped = "%" + int_to_base(char_code, base)
    return urllib.parse.unquote(escaped)


def eval_char_at(part):
    match = re.fullmatch(
        r"(?P<prefix>.*;\s*)?(?P<obj>[A-Za-z_$][\w$]*)\.(?P<prop>[A-Za-z_$][\w$]*)"
        r"\.charAt\(eval\(unescape\('(?P<index>[^']+)'\)\)\)",
        part.strip(),
    )
    if not match:
        raise IliadBoxError("Challenge charAt non riconosciuto")

    env = parse_js_env(match.group("prefix") or "")
    obj = env.get(match.group("obj"))
    if not isinstance(obj, dict):
        raise IliadBoxError("Oggetto JavaScript non riconosciuto nel challenge")

    value = obj.get(match.group("prop"))
    if not isinstance(value, str):
        raise IliadBoxError("Proprieta' JavaScript non riconosciuta nel challenge")

    index = eval_js_script_number(js_unescape(match.group("index")))
    return value[index]


def eval_from_char_code(part):
    match = re.fullmatch(
        r"var\s+(?P<strvar>[A-Za-z_$][\w$]*)\s*=\s*(?P<string>'[^']*'|\"[^\"]*\")\s*;\s*"
        r"var\s+(?P<regexvar>[A-Za-z_$][\w$]*)\s*=\s*new RegExp\(\s*(?P=strvar)"
        r"\.charAt\(eval\(unescape\('(?P<replace_index>[^']+)'\)\)\)\s*,\s*['\"]g['\"]\s*\)\s*;\s*"
        r"String\.fromCharCode\(\s*(?P=strvar)\.replace\(\s*(?P=regexvar)\s*,\s*"
        r"(?P<replacement>'[^']*'|\"[^\"]*\")\s*\)\.charCodeAt\(eval\(unescape\('(?P<char_index>[^']+)'\)\)\)\s*\)",
        part.strip(),
    )
    if not match:
        raise IliadBoxError("Challenge fromCharCode non riconosciuto")

    value = js_literal(match.group("string"))
    replacement = js_literal(match.group("replacement"))
    replace_index = eval_js_script_number(js_unescape(match.group("replace_index")))
    char_index = eval_js_script_number(js_unescape(match.group("char_index")))

    replaced = value.replace(value[replace_index], replacement)
    return chr(ord(replaced[char_index]))


def eval_challenge_part(part):
    part = part.strip()
    if (part.startswith("'") and part.endswith("'")) or (part.startswith('"') and part.endswith('"')):
        return js_literal(part)
    if part.startswith("decodeURIComponent"):
        return eval_decode_uri_component(part)
    if part.startswith("String.fromCharCode") or "String.fromCharCode" in part:
        return eval_from_char_code(part)
    if ".charAt(" in part:
        return eval_char_at(part)
    raise IliadBoxError("Formato challenge non supportato")


def build_challenge(challenge):
    if isinstance(challenge, str):
        return challenge
    if isinstance(challenge, list):
        return "".join(eval_challenge_part(part) for part in challenge)
    raise IliadBoxError("Challenge di login non valido")


class IliadBoxClient:
    def __init__(self, router_url, timeout=15):
        self.router_url = normalize_router_url(router_url)
        self.base_url = self.router_url + API_PATH
        self.timeout = timeout
        self.cookie_jar = http.cookiejar.CookieJar()
        handlers = [urllib.request.HTTPCookieProcessor(self.cookie_jar)]
        if self.router_url.startswith("https://"):
            handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        self.opener = urllib.request.build_opener(*handlers)

    def request_json(self, path, method="GET", form=None, payload=None):
        url = self.base_url + path
        headers = {
            "Accept": "application/json",
            **WEB_HEADERS,
        }
        data = None

        if form is not None:
            data = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        elif payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as error:
            raise IliadBoxError(f"Impossibile raggiungere il router: {error.reason}") from error

        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise IliadBoxError(f"Risposta non JSON da {url}: {body}") from error

    def login(self, password):
        login_state = self.request_json("/login/")
        if login_state.get("success") is not True:
            raise IliadBoxError(login_state.get("msg") or "Impossibile ottenere il challenge di login")

        result = login_state.get("result") or {}
        challenge = build_challenge(result.get("challenge"))
        password_salt = result.get("password_salt")
        if not challenge or not password_salt:
            raise IliadBoxError("Challenge o password_salt mancanti nella risposta del router")

        salted_password = hashlib.sha1((password_salt + password).encode("utf-8")).hexdigest()
        digest = hmac.new(
            salted_password.encode("utf-8"),
            challenge.encode("utf-8"),
            hashlib.sha1,
        ).hexdigest()

        login_response = self.request_json("/login/", method="POST", form={"password": digest})
        if login_response.get("success") is not True:
            raise IliadBoxError(login_response.get("msg") or "Login fallito")

    def list_port_forwarding_rules(self):
        data = self.request_json("/fw/redir/")
        if data.get("success") is not True:
            raise IliadBoxError(data.get("msg") or "Impossibile leggere le regole di port forwarding")
        return data.get("result") or []

    def update_rule_enabled(self, rule, enabled):
        rule_id = rule.get("id")
        if rule_id is None:
            raise IliadBoxError("La regola trovata non ha un ID")

        payload = {field: rule[field] for field in EDITABLE_RULE_FIELDS if field in rule}
        payload["enabled"] = enabled

        data = self.request_json(f"/fw/redir/{rule_id}", method="PUT", payload=payload)
        if data.get("success") is not True:
            raise IliadBoxError(data.get("msg") or "Aggiornamento della regola fallito")


def find_rule(rules, selector):
    selector = selector.strip()
    if not selector:
        raise IliadBoxError("Nome/ID della regola mancante")

    if selector.isdigit():
        matches = [rule for rule in rules if str(rule.get("id")) == selector]
        if matches:
            return matches[0]

    exact = [rule for rule in rules if str(rule.get("comment", "")) == selector]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        ids = ", ".join(str(rule.get("id")) for rule in exact)
        raise IliadBoxError(f"Piu' regole hanno questo nome. Usa l'ID numerico: {ids}")

    selector_lower = selector.lower()
    insensitive = [rule for rule in rules if str(rule.get("comment", "")).lower() == selector_lower]
    if len(insensitive) == 1:
        return insensitive[0]
    if len(insensitive) > 1:
        ids = ", ".join(str(rule.get("id")) for rule in insensitive)
        raise IliadBoxError(f"Piu' regole corrispondono a questo nome. Usa l'ID numerico: {ids}")

    available = ", ".join(
        f"{rule.get('id')}:{rule.get('comment', '')}" for rule in rules if rule.get("id") is not None
    )
    detail = f" Regole disponibili: {available}" if available else ""
    raise IliadBoxError(f"Regola non trovata: {selector}.{detail}")


def state_label(enabled):
    return "attiva" if enabled else "disattivata"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Attiva o disattiva una regola di port forwarding su IliadBox tramite web UI."
    )
    parser.add_argument("--router", help="URL o IP del router, es. 192.168.1.254")
    parser.add_argument("--rule", help="Nome/commento della regola oppure ID numerico")
    parser.add_argument("--action", help="attiva oppure disattiva")
    parser.add_argument("--timeout", type=float, default=15, help="Timeout HTTP in secondi (default: 15)")
    args = parser.parse_args(argv)

    try:
        router = prompt_if_missing(args.router, "URL o IP del router Iliad", DEFAULT_ROUTER)
        password = getpass.getpass("Password router Iliad: ")
        rule_selector = prompt_if_missing(args.rule, "Regola port forwarding (nome/commento o ID)")
        enabled = prompt_action(args.action)

        client = IliadBoxClient(router, timeout=args.timeout)
        client.login(password)
        rules = client.list_port_forwarding_rules()
        rule = find_rule(rules, rule_selector)

        current_state = bool(rule.get("enabled"))
        print(
            "Regola trovata: "
            f"id={rule.get('id')} comment='{rule.get('comment', '')}' stato={state_label(current_state)}"
        )

        if current_state == enabled:
            print(f"Nessuna modifica: la regola e' gia' {state_label(enabled)}.")
            return 0

        client.update_rule_enabled(rule, enabled)
        refreshed_rules = client.list_port_forwarding_rules()
        refreshed_rule = find_rule(refreshed_rules, str(rule.get("id")))
        verified_state = bool(refreshed_rule.get("enabled"))
        if verified_state != enabled:
            raise IliadBoxError("La modifica e' stata inviata, ma la verifica finale non torna")

        print(f"Regola aggiornata: id={rule.get('id')} stato={state_label(verified_state)}")
        return 0
    except KeyboardInterrupt:
        print("\nOperazione annullata.", file=sys.stderr)
        return 130
    except IliadBoxError as error:
        print(f"ERRORE: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
