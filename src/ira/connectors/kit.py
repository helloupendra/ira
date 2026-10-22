"""The connector kit: ``ira connector new <name>`` writes a tool pack for a business's API.

It writes one Python file of ordinary ``@tool`` and ``@action`` functions,
meant to be read and edited, from one of:

* an OpenAPI description (``--openapi``, a file or an https URL, JSON or YAML):
  one tool per operation;
* a REST base URL (``--base-url``) with no description: three general tools,
  read, change and delete, under that address only;
* another Ira (``--ira``): one tool that asks that business's own assistant,
  with an API token that may only ask.

Reading (GET) is Tier 0, and what comes back is untrusted text. POST, PUT and
PATCH are Tier 2, read back and confirmed; DELETE is Tier 3, with the PIN.
Credentials come from environment variables, never the file. Every string
taken from a description is written as a Python literal (``repr``), so a
description can name things but cannot add code.
"""

from __future__ import annotations

import json
import keyword
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

AUTH_KINDS = ("none", "api-key", "bearer", "oauth")
METHODS = ("get", "post", "put", "patch", "delete")
MAX_SPEC_BYTES = 5_000_000
MAX_OPERATIONS = 60


class KitError(Exception):
    pass


@dataclass
class Param:
    py: str  # the Python argument's name
    name: str  # its name in the API
    where: str  # path, query or body
    annotation: str
    required: bool
    description: str = ""


@dataclass
class Operation:
    tool: str
    method: str
    path: str
    description: str
    params: list[Param] = field(default_factory=list)
    whole_body: bool = False  # the body is one argument, not its properties


# Names.


def ident(text: str, fallback: str = "value") -> str:
    """A snake_case Python identifier from any text."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(text))
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower() or fallback
    if text[0].isdigit():
        text = f"n_{text}"
    return f"{text}_" if keyword.iskeyword(text) else text


def lit(value: str) -> str:
    """A Python string literal for any text, in double quotes when it can be."""
    text = repr(str(value))
    if text.startswith("'") and '"' not in value:
        return '"' + text[1:-1] + '"'
    return text


def env_prefix(name: str) -> str:
    return ident(name).upper()


def title(name: str) -> str:
    return " ".join(part.capitalize() for part in ident(name).split("_"))


def _unique(name: str, taken: set[str], limit: int = 64) -> str:
    name, n = name[:limit], 2
    candidate = name
    while candidate in taken:
        suffix = f"_{n}"
        candidate, n = name[: limit - len(suffix)] + suffix, n + 1
    taken.add(candidate)
    return candidate


# Reading a description.


def load_spec(source: str) -> dict[str, Any]:
    if source.startswith(("http://", "https://")):
        if not source.startswith("https://"):
            raise KitError("fetch descriptions over https only")
        try:
            response = httpx.get(source, timeout=30, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise KitError(f"could not fetch {source} ({type(exc).__name__})") from None
        if response.status_code != 200:
            raise KitError(f"{source} answered HTTP {response.status_code}")
        text = response.text
    else:
        path = Path(source).expanduser()
        if not path.is_file():
            raise KitError(f"no file {source}")
        text = path.read_text(encoding="utf-8")
    if len(text) > MAX_SPEC_BYTES:
        raise KitError("that description is too large (5 MB at most)")
    try:
        spec = json.loads(text) if text.lstrip().startswith("{") else yaml.safe_load(text)
    except (ValueError, yaml.YAMLError) as exc:
        raise KitError(f"not JSON or YAML: {exc}") from None
    if not isinstance(spec, dict) or "paths" not in spec:
        raise KitError("not an OpenAPI description (it has no paths)")
    if not str(spec.get("openapi") or spec.get("swagger") or "").startswith(("3", "2")):
        raise KitError("an OpenAPI 3 (or Swagger 2) description is needed")
    return spec


def _resolve(spec: dict[str, Any], node: Any, depth: int = 0) -> Any:
    """Follow local ``$ref``s ("#/components/schemas/Order"), a few levels deep."""
    while isinstance(node, dict) and "$ref" in node and depth < 8:
        ref = str(node["$ref"])
        if not ref.startswith("#/"):
            return {}
        target: Any = spec
        for part in ref[2:].split("/"):
            target = target.get(part.replace("~1", "/").replace("~0", "~"), {})
            if not isinstance(target, dict):
                return {}
        node, depth = target, depth + 1
    return node if isinstance(node, dict) else {}


SIMPLE = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}


def annotation(spec: dict[str, Any], schema: Any) -> str:
    schema = _resolve(spec, schema)
    enum = schema.get("enum")
    if enum and all(isinstance(v, str) for v in enum) and len(enum) <= 30:
        return "Literal[" + ", ".join(lit(v) for v in enum) + "]"
    kind = schema.get("type")
    if isinstance(kind, list):  # OpenAPI 3.1: ["string", "null"]
        kind = next((k for k in kind if k != "null"), None)
    if kind in SIMPLE:
        return SIMPLE[kind]
    if kind == "array":
        item = _resolve(spec, schema.get("items") or {}).get("type")
        return f"list[{SIMPLE.get(item, 'Any')}]"
    if kind == "object" or "properties" in schema:
        return "dict[str, Any]"
    return "Any"


def _text(*values: Any, limit: int = 300) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:limit]
    return ""


def operations(spec: dict[str, Any], prefix: str) -> list[Operation]:
    found: list[Operation] = []
    names: set[str] = set()
    for path, item in (spec.get("paths") or {}).items():
        item = _resolve(spec, item)
        shared = item.get("parameters") or []
        for method in METHODS:
            op = item.get(method)
            if not isinstance(op, dict) or op.get("deprecated"):
                continue
            base = ident(op.get("operationId") or f"{method}_{path}", "call")
            operation = Operation(
                tool=_unique(f"{ident(prefix)}_{base}", names),
                method=method.upper(),
                path=str(path),
                description=_text(op.get("summary"), op.get("description"))
                or f"{method.upper()} {path}",
            )
            taken: set[str] = set()
            for raw in [*shared, *(op.get("parameters") or [])]:
                p = _resolve(spec, raw)
                where = p.get("in")
                if where not in ("path", "query") or not p.get("name"):
                    continue  # headers and cookies are the pack's own business
                if any(q.name == p["name"] and q.where == where for q in operation.params):
                    continue  # an operation's parameter overrides the path's
                schema = p.get("schema") or {"type": p.get("type", "string")}  # Swagger 2
                operation.params.append(
                    Param(
                        py=_unique(ident(p["name"]), taken),
                        name=str(p["name"]),
                        where=where,
                        annotation=annotation(spec, schema),
                        required=bool(p.get("required")) or where == "path",
                        description=_text(p.get("description")),
                    )
                )
            _body(spec, op, operation, taken)
            found.append(operation)
            if len(found) >= MAX_OPERATIONS:
                return found
    return found


def _body(spec: dict[str, Any], op: dict[str, Any], operation: Operation, taken: set[str]) -> None:
    body = _resolve(spec, op.get("requestBody"))
    content = body.get("content") or {}
    media = content.get("application/json") or next(iter(content.values()), None)
    schema = None
    if isinstance(media, dict):
        schema = media.get("schema")
    else:  # Swagger 2: a parameter "in: body"
        for raw in op.get("parameters") or []:
            p = _resolve(spec, raw)
            if p.get("in") == "body":
                schema, body = p.get("schema"), {"required": p.get("required")}
    if schema is None:
        return
    schema = _resolve(spec, schema)
    properties = schema.get("properties")
    if isinstance(properties, dict) and properties and len(properties) <= 20:
        required = set(schema.get("required") or [])
        for name, prop in properties.items():
            prop = _resolve(spec, prop)
            if prop.get("readOnly"):
                continue
            py = ident(name)
            operation.params.append(
                Param(
                    py=_unique(py if py not in taken else f"body_{py}", taken),
                    name=str(name),
                    where="body",
                    annotation=annotation(spec, prop),
                    required=name in required,
                    description=_text(prop.get("description")),
                )
            )
        return
    operation.whole_body = True
    operation.params.append(
        Param(
            py=_unique("body", taken),
            name="body",
            where="body",
            annotation=annotation(spec, schema),
            required=bool(body.get("required", True)),
            description="The request's JSON body.",
        )
    )


def auth_from(spec: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """(kind, api-key header, OAuth token URL) from a description's security schemes."""
    schemes = (spec.get("components") or {}).get("securitySchemes") or spec.get(
        "securityDefinitions"
    )
    for scheme in (schemes or {}).values():
        scheme = _resolve(spec, scheme)
        kind = scheme.get("type")
        if kind == "apiKey" and scheme.get("in") == "header":
            return "api-key", str(scheme.get("name") or "X-API-Key"), None
        if kind == "http" and str(scheme.get("scheme", "")).lower() == "bearer":
            return "bearer", None, None
        if kind == "oauth2":
            flows = scheme.get("flows") or {}
            flow = flows.get("clientCredentials") or {}
            url = flow.get("tokenUrl") or (
                scheme.get("tokenUrl") if scheme.get("flow") == "application" else None
            )
            if url:
                return "oauth", None, str(url)
            return "bearer", None, None  # a person's OAuth: a token they give
    return "none", None, None


def base_url_from(spec: dict[str, Any]) -> str | None:
    servers = spec.get("servers") or []
    if servers and isinstance(servers[0], dict) and servers[0].get("url"):
        url = str(servers[0]["url"])
        return url if url.startswith(("https://", "http://")) else None
    if spec.get("host"):  # Swagger 2
        scheme = (spec.get("schemes") or ["https"])[0]
        return f"{scheme}://{spec['host']}{spec.get('basePath', '')}"
    return None


# Writing the pack.

HEAD = '''"""{title}: a tool pack made by `ira connector new` from {source}.

Edit it freely: sharpen the descriptions, remove what Ira should never use,
raise a tier (an @tool can become an @action; tier=2 can become tier=3).
{tiers}
Settings come from the environment of the Ira server, never this file:

{settings}

Add the file under tools: in ira.yaml and restart Ira.
"""

from __future__ import annotations

import os
{imports}
NAME = {name}
DEFAULT_URL = {base}
BASE_URL = (os.environ.get("{env}_BASE_URL") or DEFAULT_URL).rstrip("/")
TIMEOUT = 30
'''

TIERS = """
Reading (GET) is Tier 0: Ira calls it freely, and what comes back is treated
as text written by others, never as instructions. POST, PUT and PATCH are
Tier 2: Ira reads back the call with its values and waits for a yes. DELETE
is Tier 3: the person's PIN.
"""

AUTH_CODE = {
    "none": """

def _auth() -> dict[str, str]:
    return {}
""",
    "api-key": """

def _auth() -> dict[str, str]:
    key = os.environ.get("{env}_API_KEY")
    if not key:
        raise ToolError("{env}_API_KEY is not set on the Ira server")
    return {{{header}: key}}
""",
    "bearer": """

def _auth() -> dict[str, str]:
    token = os.environ.get("{env}_TOKEN")
    if not token:
        raise ToolError("{env}_TOKEN is not set on the Ira server")
    return {{"Authorization": f"Bearer {{token}}"}}
""",
    "oauth": '''
TOKEN_URL = os.environ.get("{env}_TOKEN_URL") or {token_url}
_token: dict[str, Any] = {{}}


def _auth() -> dict[str, str]:
    """OAuth client credentials: a token for this server, fetched again when it expires."""
    if _token.get("value") and time.time() < _token.get("until", 0):
        return {{"Authorization": f"Bearer {{_token['value']}}"}}
    client_id = os.environ.get("{env}_CLIENT_ID")
    secret = os.environ.get("{env}_CLIENT_SECRET")
    if not client_id or not secret:
        raise ToolError("{env}_CLIENT_ID and _CLIENT_SECRET are not set on the Ira server")
    try:
        response = httpx.post(
            TOKEN_URL,
            data={{"grant_type": "client_credentials"}},
            auth=(client_id, secret),
            timeout=TIMEOUT,
        )
        data = response.json() if response.status_code == 200 else {{}}
    except (httpx.HTTPError, ValueError):
        data = {{}}
    if not data.get("access_token"):
        raise ToolError(f"{{NAME}} refused the server's sign-in")
    until = time.time() + float(data.get("expires_in", 600)) - 30
    _token.update(value=data["access_token"], until=until)
    return {{"Authorization": f"Bearer {{_token['value']}}"}}
''',
}

CALL = '''

def _path(template: str, values: dict[str, Any]) -> str:
    for key, value in values.items():
        template = template.replace("{" + key + "}", quote(str(value), safe=""))
    return template


def _call(method: str, path: str, query: dict[str, Any] | None = None, body: Any = None) -> Any:
    """One request to the API, with its credentials; errors become a sentence for Ira."""
    params = {k: v for k, v in (query or {}).items() if v is not None}
    if isinstance(body, dict):
        body = {k: v for k, v in body.items() if v is not None}
    try:
        response = httpx.request(
            method,
            BASE_URL + path,
            params=params,
            json=body,
            headers={"Accept": "application/json", **_auth()},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise ToolError(f"{NAME} did not answer ({type(exc).__name__})") from None
    if response.status_code >= 400:
        raise ToolError(f"{NAME} answered HTTP {response.status_code}: {response.text[:300]}")
    if not response.content:
        return {"ok": True, "status": response.status_code}
    try:
        return response.json()
    except ValueError:
        return {"text": response.text[:20000]}
'''


def _settings(env: str, auth: str, header: str | None) -> str:
    lines = [f"    {env}_BASE_URL       the API's address (the default is below)"]
    lines += {
        "none": [],
        "api-key": [f"    {env}_API_KEY        the key, sent as the {header} header"],
        "bearer": [f"    {env}_TOKEN          a token, sent as Authorization: Bearer"],
        "oauth": [
            f"    {env}_CLIENT_ID      OAuth client credentials for this server",
            f"    {env}_CLIENT_SECRET",
            f"    {env}_TOKEN_URL      (optional) where to get the token",
        ],
    }[auth]
    return "\n".join(lines)


def _imports(body: str) -> str:
    """Only the imports the pack's code uses."""
    lines = ["import time"] if "time.time()" in body else []
    typing = [n for n in ("Annotated", "Any", "Literal") if re.search(rf"\b{n}\[|-> {n}\b", body)]
    lines += [f"from typing import {', '.join(typing)}"] if typing else []
    lines += ["from urllib.parse import quote", ""] if "quote(" in body else [""]
    lines += ["import httpx"]
    lines += ["from pydantic import Field", ""] if "Field(" in body else [""]
    used = [n for n in ("ToolError", "action", "tool") if re.search(rf"(^@|\b){n}\(", body, re.M)]
    lines += [f"from ira import {', '.join(used)}", ""]
    return "\n".join(lines)


def _head(
    name: str, source: str, base: str, auth: str, header: str | None, tiers: str, body: str
) -> str:
    env = env_prefix(name)
    return HEAD.format(
        imports=_imports(body),
        title=title(name),
        source=re.sub(r"[^\w./:?=&%~+-]", "", source)[:200],
        tiers=tiers,
        settings=_settings(env, auth, header),
        name=lit(title(name)),
        env=env,
        base=lit(base),
    )


def _auth_code(name: str, auth: str, header: str | None, token_url: str | None) -> str:
    return AUTH_CODE[auth].format(
        env=env_prefix(name), header=lit(header or "X-API-Key"), token_url=lit(token_url or "")
    )


def _signature(param: Param) -> str:
    kind = param.annotation if param.required else f"{param.annotation} | None"
    if param.description:
        kind = f"Annotated[{kind}, Field(description={lit(param.description)})]"
    return f"{param.py}: {kind}" + ("" if param.required else " = None")


def _summary(operation: Operation, name: str) -> str:
    """The read-back of an action: what it does, the exact address, and every value."""
    path = operation.path
    for p in operation.params:
        if p.where == "path":
            path = path.replace("{" + p.name + "}", "\0" + p.py + "\1")
    path = path.replace("{", "{{").replace("}", "}}").replace("\0", "{").replace("\1", "}")
    what = operation.description.replace("{", "{{").replace("}", "}}")
    values = ", ".join(f"{p.name} {{{p.py}}}" for p in operation.params if p.where != "path")
    return f"{title(name)}: {what} ({operation.method} {path})" + (f": {values}" if values else "")


def render_operation(operation: Operation, name: str) -> str:
    required = [p for p in operation.params if p.required]
    optional = [p for p in operation.params if not p.required]
    args = ",\n    ".join(_signature(p) for p in [*required, *optional])
    named = f"\n    name={lit(operation.tool)},\n    description={lit(operation.description)},"
    if operation.method == "GET":
        decorator = f"@tool({named}\n    untrusted=True,\n)"
    else:
        tier = 3 if operation.method == "DELETE" else 2
        summary = lit(_summary(operation, name))
        decorator = f"@action({named}\n    summary={summary},\n    tier={tier},\n)"

    def mapping(where: str) -> str:
        items = [f"{lit(p.name)}: {p.py}" for p in operation.params if p.where == where]
        return "{" + ", ".join(items) + "}"

    path = lit(operation.path)
    if any(p.where == "path" for p in operation.params):
        path = f"_path({path}, {mapping('path')})"
    call = [lit(operation.method), path]
    if any(p.where == "query" for p in operation.params):
        call.append(f"query={mapping('query')}")
    if operation.whole_body:
        call.append(f"body={operation.params[-1].py}")
    elif any(p.where == "body" for p in operation.params):
        call.append(f"body={mapping('body')}")
    signature = f"(\n    {args},\n)" if args else "()"
    line = f"    return _call({', '.join(call)})"
    if len(line) > 100:  # one argument a line, and a long mapping one item a line
        parts = [_explode(part) if len(part) > 88 else part for part in call]
        line = "    return _call(\n" + "".join(f"        {part},\n" for part in parts) + "    )"
    return f"\n\n{decorator}\ndef {operation.tool}{signature} -> Any:\n{line}\n"


def _explode(part: str) -> str:
    """``body={'a': a, 'b': b}`` written one item a line."""
    head, _, rest = part.partition("{")
    if not rest.endswith("}") or rest.endswith("})"):
        return part
    items = [item.strip() for item in rest[:-1].split(", ") if item.strip()]
    return head + "{\n" + "".join(f"            {item},\n" for item in items) + "        }"


def render_openapi(
    name: str,
    spec: dict[str, Any],
    *,
    source: str,
    base_url: str | None = None,
    auth: str | None = None,
    header: str | None = None,
    token_url: str | None = None,
) -> str:
    found_auth, found_header, found_token = auth_from(spec)
    auth = auth or found_auth
    header = header or found_header or "X-API-Key"
    base = base_url or base_url_from(spec)
    if not base:
        raise KitError("the description names no server: give --base-url")
    if auth == "oauth" and not (token_url or found_token):
        raise KitError("OAuth needs a token URL: give --token-url")
    ops = operations(spec, name)
    if not ops:
        raise KitError("the description has no operations")
    body = _auth_code(name, auth, header, token_url or found_token) + CALL
    body += "".join(render_operation(op, name) for op in ops)
    return _head(name, source, base, auth, header, TIERS, body) + body


REST = '''

def _below(path: str) -> str:
    """A path under BASE_URL, and nowhere else."""
    path = "/" + path.strip().lstrip("/")
    if "//" in path or ".." in path or "@" in path or "\\\\" in path:
        raise ToolError("give a path under the API, such as /orders/42")
    return path


@tool(
    name="{read}",
    description="Read from {title}'s API: GET a path under it, such as /orders?status=open, "
    "with optional query values.",
    untrusted=True,
)
def {read}(path: str, query: dict[str, str] | None = None) -> Any:
    return _call("GET", _below(path), query=query)


@action(
    name="{change}",
    description="Change something through {title}'s API: POST, PUT or PATCH a JSON body "
    "to a path under it. Read back the method, the path and the body.",
    summary="{title}: {{method}} {{path}} with {{body}}",
    tier=2,
)
def {change}(method: Literal["POST", "PUT", "PATCH"], path: str, body: dict[str, Any]) -> Any:
    return _call(method, _below(path), body=body)


@action(
    name="{delete}",
    description="Delete something through {title}'s API: DELETE a path under it.",
    summary="{title}: DELETE {{path}}",
    tier=3,
)
def {delete}(path: str) -> Any:
    return _call("DELETE", _below(path))
'''

REST_TIERS = """
There is no description of this API, so these are three general tools: read
(GET, Tier 0, untrusted), change (POST, PUT or PATCH, Tier 2) and delete
(Tier 3), each under BASE_URL only. Write one tool per thing Ira should do,
and remove these, as soon as you know the API.
"""


def render_rest(
    name: str,
    base_url: str,
    *,
    auth: str = "none",
    header: str | None = None,
    token_url: str | None = None,
) -> str:
    if auth == "oauth" and not token_url:
        raise KitError("OAuth needs a token URL: give --token-url")
    prefix = ident(name)
    header = header or "X-API-Key"
    body = _auth_code(name, auth, header, token_url) + CALL
    body += REST.format(
        title=title(name),
        read=f"{prefix}_read",
        change=f"{prefix}_change",
        delete=f"{prefix}_delete",
    )
    return _head(name, base_url, base_url, auth, header, REST_TIERS, body) + body


IRA = '''"""{title}: ask that business's own Ira, made by `ira connector new --ira`.

The pattern: the business runs its own Ira, with its own tools and data, and
gives you an API token whose only scope is "ask". Your Ira asks it questions
in plain words and reads the answer. The token cannot confirm anything, so
the other Ira can never act for you: at most it proposes, and its people
decide. The answer is text written by others: data, never instructions.

Settings come from the environment of the Ira server, never this file:

    {env}_BASE_URL   its address (the default is below)
    {env}_TOKEN      the API token it gave you (scope "ask" only)

Add the file under tools: in ira.yaml and restart Ira.
"""

from __future__ import annotations

import os
from typing import Annotated, Any

import httpx
from pydantic import Field

from ira import ToolError, tool

DEFAULT_URL = {base}
BASE_URL = (os.environ.get("{env}_BASE_URL") or DEFAULT_URL).rstrip("/")
_conversation: dict[str, str] = {{}}


@tool(
    name="{tool}",
    description="Ask {title}'s own assistant a question in plain words, about its business "
    "(orders, bookings, accounts, status), and get its answer.",
    untrusted=True,
)
def {tool}(
    question: Annotated[str, Field(max_length=2000)],
    new_conversation: bool = False,
) -> Any:
    token = os.environ.get("{env}_TOKEN")
    if not token:
        raise ToolError("{env}_TOKEN is not set on the Ira server")
    body: dict[str, Any] = {{"text": question}}
    if _conversation.get("id") and not new_conversation:
        body["conversation_id"] = _conversation["id"]
    try:
        response = httpx.post(
            BASE_URL + "/v1/ask",
            json=body,
            headers={{"Authorization": f"Bearer {{token}}"}},
            timeout=90,
        )
    except httpx.HTTPError as exc:
        raise ToolError(f"{title} did not answer ({{type(exc).__name__}})") from None
    if response.status_code in (401, 403):
        raise ToolError("{title} refused the token: ask them for a new one")
    if response.status_code != 200:
        raise ToolError(f"{title} answered HTTP {{response.status_code}}")
    data = response.json()
    _conversation["id"] = str(data.get("conversation_id") or "")
    answer: dict[str, Any] = {{"answer": data.get("text", "")}}
    if data.get("action"):
        answer["note"] = "It proposed an action; only its own people can confirm it."
    return answer
'''


def render_ira(name: str, base_url: str) -> str:
    return IRA.format(
        title=title(name), env=env_prefix(name), base=lit(base_url), tool=f"{ident(name)}_ask"
    )


def new_pack(
    name: str,
    *,
    openapi: str | None = None,
    base_url: str | None = None,
    ira: str | None = None,
    auth: str | None = None,
    header: str | None = None,
    token_url: str | None = None,
) -> str:
    """The pack's source code, from exactly one of an OpenAPI description, a base URL or an Ira."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]{0,39}", name):
        raise KitError("name it with letters, digits, spaces, - or _ (40 at most)")
    if sum(x is not None for x in (openapi, ira)) > 1 or not (openapi or base_url or ira):
        raise KitError("give one of --openapi, --base-url or --ira")
    if auth is not None and auth not in AUTH_KINDS:
        raise KitError(f"--auth is one of {', '.join(AUTH_KINDS)}")
    for url in (base_url, ira, token_url):
        if url and not url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise KitError(f"{url}: use https (http only for this computer)")
    if ira:
        return render_ira(name, ira.rstrip("/"))
    if openapi:
        return render_openapi(
            name,
            load_spec(openapi),
            source=openapi if openapi.startswith("https://") else Path(openapi).name,
            base_url=base_url,
            auth=auth,
            header=header,
            token_url=token_url,
        )
    assert base_url is not None
    return render_rest(name, base_url, auth=auth or "none", header=header, token_url=token_url)
