#!/usr/bin/env python3
"""Helpers for the six-language client checks (see README.md).

Subcommands: `render` writes a typed consumer for one language, `mock-trp`
serves a recording TRP resolver, `verify` compares the recorded request with
the interface and input fixture, `row` emits one language record and
`combine` folds the records into one release-scoped result, which `summary`
prints as a Markdown table.
"""
import argparse
import hashlib
import http.server
import json
import pathlib
import re
import sys

LANGUAGES = ["rust", "python", "go", "typescript", "java", "swift"]
IDENTITY = ["scope", "name", "version", "manifest_digest", "tii_digest",
            "git_sha", "network", "operation"]
# Read from the pulled release, so combine takes it from the rows, not the caller.
RELEASE_FIELDS = ["release_date"]
LANGUAGE_FIELDS = ["language", "runtime_package", "runtime_version",
                   "tx3c_version", "trix_version", "run_url", "date", "result"]
PLACEHOLDER_TX = "84a40080018002000300a0f5f6"  # an empty Conway tx body
PLACEHOLDER_HASH = "00" * 32
# Release-supplied names become identifiers in consumer source, so only plain ones pass.
FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SYMBOL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
GO_MODULE = re.compile(r"[A-Za-z0-9_.~/-]+")


def fail(message):
    print(f"client-check: {message}", file=sys.stderr)
    sys.exit(1)


def words(name):
    return [w for w in name.replace("-", "_").split("_") if w]


def camel(name):
    parts = words(name)
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def pascal(name):
    return "".join(p[:1].upper() + p[1:] for p in words(name))


def checked(pattern, what, name):
    if not isinstance(name, str) or not pattern.fullmatch(name):
        fail(f"{what} {json.dumps(name)} is not a plain identifier")
    return name


def kind_of(schema):
    ref = schema.get("$ref", "")
    for kind in ("Bytes", "Address", "UtxoRef"):
        if ref.endswith(f"/$defs/{kind}"):
            return kind.lower()
    if schema.get("type") in ("integer", "boolean"):
        return schema["type"]
    return None


def hex_bytes(value, joiner):
    try:
        data = bytes.fromhex(value)
    except (TypeError, ValueError):
        fail(f"expected a hex string, got {value!r}")
    return joiner.join(f"0x{b:02x}" for b in data)


def utxo_parts(value):
    tx, sep, index = str(value).partition("#")
    if not sep or not index.isdigit() or not re.fullmatch(r"(?:[0-9a-fA-F]{2})+", tx):
        fail(f"expected a UtxoRef of the form <hex tx-hash>#<index>, got {value!r}")
    return tx, int(index)


# Literal renderers per language: kind -> value -> source expression. Values
# are rendered as-is, so a fixture of the wrong type fails the typed build.
def literal(lang, kind, value):
    text = json.dumps(value)
    if kind == "integer":
        return {"java": f"new java.math.BigInteger({json.dumps(str(value))})",
                "swift": f"BigInt({json.dumps(str(value))})"}.get(lang, text)
    if kind == "boolean":
        return {"python": "True" if value is True else "False" if value is False else text}.get(lang, text)
    if kind == "bytes":
        return {"rust": f"vec![{hex_bytes(value, ', ')}]",
                "typescript": f"Uint8Array.from([{hex_bytes(value, ', ')}])",
                "python": f"bytes.fromhex({text})",
                "go": f"[]byte{{{hex_bytes(value, ', ')}}}",
                "java": f"java.util.HexFormat.of().parseHex({text})",
                "swift": f"Data([{hex_bytes(value, ', ')}])"}[lang]
    if kind == "address":
        return {"rust": f"{text}.to_string()",
                "java": f"new land.tx3.sdk.Address({text})",
                "swift": f"try Address({text})"}.get(lang, text)
    if kind == "utxoref":
        tx, index = utxo_parts(value)
        return {"rust": f"{text}.to_string()",
                "java": f"new land.tx3.sdk.UtxoRef(java.util.HexFormat.of().parseHex(\"{tx}\"), {index}L)",
                "swift": f"UtxoRef(txId: Data([{hex_bytes(tx, ', ')}]), index: {index})"}.get(lang, text)
    raise AssertionError(kind)


def party(lang, address):
    text = json.dumps(address)
    return {"rust": f"Party::address({text})",
            "typescript": f"Party.address({text})",
            "python": f"Party.address({text})",
            "go": f"facade.AddressParty({text})",
            "java": f"land.tx3.sdk.Party.address(new land.tx3.sdk.Address({text}))",
            "swift": f".address(try Address({text}))"}[lang]


def field_name(lang, name):
    return {"typescript": camel(name), "java": camel(name), "swift": camel(name),
            "go": pascal(name)}.get(lang, name)


def binding(tii, operation, profile, args):
    """Classify the operation's params and parties against the input fixture."""
    tx = tii.get("transactions", {}).get(operation)
    if tx is None:
        fail(f"operation '{operation}' is not declared by the interface")
    if profile not in tii.get("profiles", {}):
        fail(f"profile '{profile}' is not declared by the interface")
    checked(SYMBOL_NAME, "protocol name", tii.get("protocol", {}).get("name"))
    checked(SYMBOL_NAME, "operation", operation)
    checked(SYMBOL_NAME, "profile", profile)
    for name in tii.get("parties", {}):
        checked(FIELD_NAME, "party", name)
    schema = tx.get("params", {})
    params = []
    for name in schema.get("required", []):
        checked(FIELD_NAME, "parameter", name)
        kind = kind_of(schema["properties"][name])
        if kind is None:
            fail(f"parameter '{name}' has a type the harness cannot bind yet: "
                 f"{json.dumps(schema['properties'][name])}")
        if name not in args:
            fail(f"input fixture is missing parameter '{name}'")
        params.append((name, kind, args[name]))
    bound = tii["profiles"][profile].get("parties", {})
    parties = [(p, args[p]) for p in sorted(tii.get("parties", {})) if p in args]
    missing = [p for p in tii.get("parties", {}) if p not in args and p not in bound]
    if missing:
        fail(f"input fixture binds no address for parties {missing}")
    unknown = sorted(set(args) - set(schema.get("properties", {})) - set(tii.get("parties", {})))
    if unknown:
        fail(f"input fixture names unknown arguments {unknown}")
    return params, parties


TEMPLATES = {
    "rust": """use {crate}::{{Client, Profile, {params_type}}};
use tx3_sdk::{{trp::ClientOptions, Party}};

#[tokio::main]
async fn main() {{
    let endpoint = std::env::args().nth(1).expect("usage: consumer <trp-endpoint>");
    let client = Client::new(ClientOptions {{ endpoint, headers: None }}, Profile::{profile_pascal}){parties};
    let params = {params_type} {{ {fields} }};
    let resolved = client.{op}(params).resolve().await.expect("resolve");
    println!("resolved {{}}", resolved.hash);
}}
""",
    "typescript": """import {{ Party }} from "tx3-sdk";
import {{ Client, type {params_type} }} from "./protocol.js";

const endpoint = process.argv[2];
const params: {params_type} = {{ {fields} }};
const client = new Client({{ endpoint }}, {profile_json}){parties};
const resolved = await client.{op_camel}(params).resolve();
console.log(`resolved ${{resolved.hash}}`);
""",
    "python": """import asyncio
import sys

from tx3_sdk import Party
from tx3_sdk.trp.client import ClientOptions

from generated_client import Client, Profile, {params_type}


async def main() -> None:
    client = Client(ClientOptions(endpoint=sys.argv[1]), Profile({profile_json})){parties}
    params = {params_type}({fields})
    resolved = await client.{op}(params).resolve()
    print("resolved", resolved.hash)


asyncio.run(main())
""",
    "go": """package main

import (
\t"context"
\t"fmt"
\t"os"

\tprotocol "{module}"
\t"github.com/tx3-lang/go-sdk/sdk/facade"
\t"github.com/tx3-lang/go-sdk/sdk/trp"
)

func main() {{
\tclient := protocol.NewClient(trp.ClientOptions{{Endpoint: os.Args[1]}}, protocol.Profile({profile_json})){parties}
\tparams := protocol.{params_type}{{ {fields} }}
\tresolved, err := client.{op_pascal}(params).Resolve(context.Background())
\tif err != nil {{
\t\tfmt.Fprintln(os.Stderr, err)
\t\tos.Exit(1)
\t}}
\tfmt.Println("resolved", resolved.Hash)
\t_ = facade.AddressParty
}}
""",
    "java": """package e2e;

import {package}.{client};

public final class Consumer {{
  public static void main(String[] args) {{
    var client = new {client}(
        land.tx3.sdk.ClientOptions.forEndpoint(java.net.URI.create(args[0])),
        {client}.Profile.{profile_upper}){parties};
    var params = new {client}.{params_type}({positional});
    var resolved = client.{op_camel}(params).resolve().join();
    System.out.println("resolved " + resolved.hash());
  }}
}}
""",
    "swift": """{bigint}import Foundation
import {client}
import Tx3SDK

let endpoint = URL(string: CommandLine.arguments[1])!
let client = {client}(options: ClientOptions(endpoint: endpoint), profile: .{profile_camel}){parties}
let params = {params_type}({labelled})
let resolved = try await client.{op_camel}(params).resolve()
print("resolved \\(resolved.hash)")
""",
}

PARTY_CALL = {"rust": ".with_{p}({v})", "typescript": ".with{P}({v})",
              "python": ".with_{p}({v})", "go": ".With{P}({v})",
              "java": ".with{P}({v})", "swift": ".with{P}({v})"}
FIELD = {"rust": "{f}: {v}", "typescript": "{f}: {v}", "python": "{f}={v}",
         "go": "{f}: {v}", "java": "{v}", "swift": "{f}: {v}"}


def render(ns):
    tii = json.loads(pathlib.Path(ns.tii).read_text())
    args = json.loads(pathlib.Path(ns.args).read_text())
    params, parties = binding(tii, ns.operation, ns.profile, args)
    lang = ns.lang
    fields = [FIELD[lang].format(f=field_name(lang, n), v=literal(lang, k, v)) for n, k, v in params]
    calls = "".join(PARTY_CALL[lang].format(p=p, P=pascal(p), v=party(lang, a)) for p, a in parties)
    protocol = tii["protocol"]["name"]
    source = TEMPLATES[lang].format(
        crate=protocol.replace("-", "_"),
        module=checked(GO_MODULE, "Go module", ns.module) if ns.module else protocol,
        package=f"land.tx3.generated.{camel(protocol)}", client=f"{pascal(protocol)}Client",
        params_type=f"{pascal(ns.operation)}Params", op=ns.operation,
        op_camel=camel(ns.operation), op_pascal=pascal(ns.operation),
        profile_json=json.dumps(ns.profile), profile_pascal=pascal(ns.profile),
        profile_upper=ns.profile.upper().replace("-", "_"), profile_camel=camel(ns.profile),
        parties=calls, fields=", ".join(fields), positional=", ".join(fields),
        labelled=", ".join(fields), bigint="import BigInt\n" if ns.bigint else "")
    pathlib.Path(ns.out).write_text(source)


def mock_trp(ns):
    record = pathlib.Path(ns.record)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            with record.open("a") as out:
                out.write(json.dumps(body) + "\n")
            if body.get("method") == "trp.resolve":
                reply = {"result": {"tx": PLACEHOLDER_TX, "hash": PLACEHOLDER_HASH}}
            else:
                reply = {"error": {"code": -32601, "message": "method not found"}}
            data = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), **reply}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    pathlib.Path(ns.port_file).write_text(str(server.server_port))
    server.serve_forever()


WIRE_TAGS = {"integer": "int", "boolean": "bool", "bytes": "bytes",
             "address": "address", "utxoref": "utxoRef"}


def wire_matches(kind, expected, actual):
    """Compare one fixture value with its TRP wire form: bare, or tagged by its kind."""
    if isinstance(actual, dict):
        if list(actual) != [WIRE_TAGS[kind]]:
            return False
        actual = actual[WIRE_TAGS[kind]]
    if kind in ("bytes", "utxoref", "address") and isinstance(actual, str):
        return actual.lower().removeprefix("0x") == str(expected).lower().removeprefix("0x")
    if kind == "integer":
        return isinstance(actual, (int, str)) and not isinstance(actual, bool) and str(actual) == str(expected)
    if kind == "boolean":
        return isinstance(actual, bool) and actual is expected
    return actual == expected


def verify(ns):
    tii = json.loads(pathlib.Path(ns.tii).read_text())
    args = json.loads(pathlib.Path(ns.args).read_text())
    params, parties = binding(tii, ns.operation, ns.profile, args)
    lines = [json.loads(l) for l in pathlib.Path(ns.record).read_text().splitlines() if l.strip()]
    resolves = [l for l in lines if l.get("method") == "trp.resolve"]
    if len(resolves) != 1:
        fail(f"expected exactly one trp.resolve request, recorded {len(resolves)}")
    sent = resolves[0].get("params", {})
    expected_tir = tii["transactions"][ns.operation]["tir"]
    if sent.get("tir", {}).get("content") != expected_tir["content"]:
        fail(f"resolved TIR is not the TIR of operation '{ns.operation}'")
    wire = {k.lower(): v for k, v in sent.get("args", {}).items()}
    for name, kind, value in params:
        if name.lower() not in wire or not wire_matches(kind, value, wire[name.lower()]):
            fail(f"argument '{name}' was sent as {json.dumps(wire.get(name.lower()))}, "
                 f"fixture has {json.dumps(value)}")
    for name, address in parties:
        if not wire_matches("address", address, wire.get(name.lower())):
            fail(f"party '{name}' was sent as {json.dumps(wire.get(name.lower()))}")
    print(f"recorded trp.resolve matches operation '{ns.operation}' and the input fixture")


def row(ns):
    record = {k: getattr(ns, k) for k in IDENTITY + RELEASE_FIELDS + LANGUAGE_FIELDS}
    record["reason"] = ns.reason or ""
    pathlib.Path(ns.out).write_text(json.dumps(record, indent=2) + "\n")


def combine(ns):
    """Fold language records into one result. A row given as <language>=<path>
    must carry that language, and every row must come from this run (--run-url)."""
    rows = []
    if ns.artifact_root:
        for lang in LANGUAGES:
            path = pathlib.Path(f"{ns.artifact_root}{lang}") / f"{lang}.json"
            if path.exists():
                ns.rows.append(f"{lang}={path}")
    for arg in ns.rows:
        expected, sep, path = arg.partition("=")
        if not sep:
            expected, path = None, arg
        try:
            r = json.loads(pathlib.Path(path).read_text())
        except (OSError, ValueError) as exc:
            r = {"language": expected, "result": "fail", "reason": f"unreadable record {path}: {exc}"}
        if expected and r.get("language") != expected:
            r = {**r, "language": expected, "result": "fail",
                 "reason": f"record {path} names language {json.dumps(r.get('language'))}"}
        rows.append(r)
    identity = {k: getattr(ns, k) for k in IDENTITY}
    if ns.release:
        scope, _, rest = ns.release.partition("/")
        name, _, version = rest.partition(":")
        identity.update(scope=scope, name=name, version=version)
    identity["network"] = identity["network"] or ns.profile
    if ns.identity_from:
        try:
            source = json.loads(pathlib.Path(ns.identity_from).read_text())
        except (OSError, ValueError):
            source = {}
        identity = {k: source.get(k, "") for k in IDENTITY}
    dates = {r.get("release_date") for r in rows if r.get("release_date")}
    identity["release_date"] = dates.pop() if len(dates) == 1 else ""
    by_language = {}
    for r in rows:
        problems = [f for f in IDENTITY + RELEASE_FIELDS + LANGUAGE_FIELDS if not r.get(f)]
        problems += [f for f in IDENTITY + RELEASE_FIELDS if r.get(f) and r[f] != identity[f]]
        if ns.run_url and r.get("run_url") and r["run_url"] != ns.run_url:
            problems.append("run_url")
        if r.get("result") == "pass" and problems:
            r = {**r, "result": "fail", "reason": f"missing or mismatched fields: {problems}"}
        if r.get("language") in by_language:
            r = {**r, "result": "fail", "reason": "duplicate record for this language"}
        by_language[r.get("language") or f"unknown-{len(by_language)}"] = r
    languages = []
    for lang in LANGUAGES:
        languages.append(by_language.pop(lang, {
            **identity, "language": lang, "result": "fail", "reason": "no record produced"}))
    languages += list(by_language.values())
    passed = sum(1 for r in languages if r.get("result") == "pass")
    result = {**identity, "date": ns.date, "run_url": ns.run_url,
              "result": "pass" if passed == len(LANGUAGES) == len(languages) else "fail",
              "passed": passed, "languages": languages}
    pathlib.Path(ns.out).write_text(json.dumps(result, indent=2) + "\n")
    print(f"{passed}/{len(LANGUAGES)} languages passed; overall {result['result']}")
    if result["result"] != "pass":
        sys.exit(1)


def summary(ns):
    result = json.loads(pathlib.Path(ns.result).read_text())
    print(f"### Client checks: {result['scope']}/{result['name']}:{result['version']} "
          f"(released {result.get('release_date') or 'unknown'}; {result['operation']}, "
          f"{result['network']}) — {result['result']}\n")
    print("| Language | Result | Runtime package | Reason |\n|---|---|---|---|")
    for r in result["languages"]:
        package = f"{r.get('runtime_package', '')} {r.get('runtime_version', '')}".strip()
        print(f"| {r.get('language')} | {r.get('result')} | {package} | {r.get('reason', '')} |")


def call_key(ns):
    print(hashlib.sha256(json.dumps(ns.inputs).encode()).hexdigest()[:12])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("render", "verify"):
        p = sub.add_parser(name)
        for flag in ("tii", "operation", "profile", "args"):
            p.add_argument(f"--{flag}", required=True)
    sub.choices["render"].add_argument("--lang", required=True, choices=LANGUAGES)
    sub.choices["render"].add_argument("--module", default="")
    sub.choices["render"].add_argument("--bigint", action="store_true",
                                       help="Swift: the generated package depends on BigInt")
    sub.choices["render"].add_argument("--out", required=True)
    sub.choices["verify"].add_argument("--record", required=True)
    p = sub.add_parser("mock-trp")
    p.add_argument("--record", required=True)
    p.add_argument("--port-file", required=True)
    p = sub.add_parser("row")
    for flag in IDENTITY + RELEASE_FIELDS + LANGUAGE_FIELDS + ["reason", "out"]:
        p.add_argument(f"--{flag.replace('_', '-')}", dest=flag, default="")
    p = sub.add_parser("combine")
    for flag in IDENTITY + ["release", "profile", "date", "run_url", "out"]:
        p.add_argument(f"--{flag.replace('_', '-')}", dest=flag, default="")
    p.add_argument("--identity-from", default="", help="take the release identity from a record")
    p.add_argument("--artifact-root", default="",
                   help="read <root><language>/<language>.json for each language")
    p.add_argument("rows", nargs="*", help="records, each <path> or <language>=<path>")
    sub.add_parser("summary").add_argument("result")
    sub.add_parser("call-key", help="short key for one workflow call's inputs").add_argument("inputs", nargs="*")
    ns = parser.parse_args()
    {"render": render, "verify": verify, "mock-trp": mock_trp,
     "row": row, "combine": combine, "summary": summary, "call-key": call_key}[ns.command](ns)


if __name__ == "__main__":
    main()
