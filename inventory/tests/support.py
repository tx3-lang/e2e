"""Shared fixtures: a minimal CBOR encoder, a synthetic swap-order
transaction and a complete set of evidence records for one release."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))

import inventory  # noqa: E402
from cardano_tx import CborMap, Tag, address  # noqa: E402

FIXTURES = HERE / "fixtures"


def _head(major: int, n: int) -> bytes:
    if n < 24:
        return bytes([major << 5 | n])
    for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
        if n < 1 << (8 * size):
            return bytes([major << 5 | info]) + n.to_bytes(size, "big")
    raise ValueError("integer too large")


def cbor(value) -> bytes:
    """Encode ints, bytes, str, lists, CborMap/dict, Tag, bool and None."""
    if value is None:
        return b"\xf6"
    if isinstance(value, bool):
        return b"\xf5" if value else b"\xf4"
    if isinstance(value, int):
        return _head(0, value) if value >= 0 else _head(1, -1 - value)
    if isinstance(value, bytes):
        return _head(2, len(value)) + value
    if isinstance(value, str):
        return _head(3, len(value.encode())) + value.encode()
    if isinstance(value, Tag):
        return _head(6, value.tag) + cbor(value.value)
    if isinstance(value, dict):
        value = CborMap(value.items())
    if isinstance(value, CborMap):
        return _head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value)
    if isinstance(value, list):
        return _head(4, len(value)) + b"".join(cbor(v) for v in value)
    raise TypeError(type(value))


def constr(index: int, *fields):
    return Tag(121 + index, list(fields))


ORDER_SCRIPT = bytes.fromhex("a1" * 28)
USER_KEY = bytes.fromhex("b2" * 28)
USER_STAKE = bytes.fromhex("c3" * 28)
POOL_LP = bytes.fromhex("d4" * 28) + b"LP"
FUNDING = bytes.fromhex("e5" * 32)
OFFERED, BATCHER_FEE, DEPOSIT, MIN_RECEIVE = 10_000_000, 2_000_000, 2_000_000, 4_321_000


def order_tx(network=0, offered=OFFERED, receiver=USER_KEY, direction=0, min_receive=MIN_RECEIVE) -> str:
    """A swap order paid to a script address with an inline datum (hex)."""
    order_address = bytes([0x10 | network]) + ORDER_SCRIPT + USER_STAKE
    user_address = bytes([0x00 | network]) + USER_KEY + USER_STAKE
    datum = constr(0, constr(0, USER_KEY), constr(0, receiver), POOL_LP, constr(direction), min_receive, BATCHER_FEE)
    order = {0: order_address, 1: offered + BATCHER_FEE + DEPOSIT, 2: [1, Tag(24, cbor(datum))]}
    body = {0: Tag(258, [[FUNDING, 0]]), 1: [order, [user_address, 30_000_000]], 2: 180_000}
    return cbor([body, {}, True, None]).hex()


def order_expect(network="preprod") -> dict:
    return {
        "network": network,
        "outputs": [{
            "effect": "order output",
            "address": address(bytes([0x10]) + ORDER_SCRIPT + USER_STAKE),
            "lovelace_parts": {"offered": OFFERED, "batcher fee": BATCHER_FEE, "deposit": DEPOSIT},
            "assets": {},
            "datum": [
                {"effect": "receiver", "path": "fields.1.fields.0.bytes", "equals": USER_KEY.hex()},
                {"effect": "pool identity", "path": "fields.2.bytes", "equals": POOL_LP.hex()},
                {"effect": "asset direction", "path": "fields.3.constructor", "equals": 0},
                {"effect": "minimum received", "path": "fields.4.int", "equals": MIN_RECEIVE},
            ],
        }],
    }


def identity(coordinate="example/swap", version="0.1.0", network="preprod", operation="place_order") -> dict:
    scope, name = coordinate.split("/")
    return {"scope": scope, "name": name, "version": version, "manifest_digest": "sha256:" + "1" * 64,
            "tii_digest": "sha256:" + "2" * 64, "git_sha": "3" * 40, "network": network, "operation": operation}


def spec(ident, **overrides) -> dict:
    base = f"https://example.test/{ident['name']}"
    out = {
        "protocol": ident["name"], "identity": ident, "profile": ident["network"],
        "inputs": {"sender": "addr_test1example", "offered": OFFERED},
        "expect": order_expect(ident["network"]),
        "packages": dict(LANGUAGES),
        "links": {"registry_url": f"{base}/registry", "source_url": f"{base}/tree/v{ident['version']}",
                  "ci_run": f"{base}/actions/1", "docs_url": f"{base}/docs", "example_url": f"{base}/docs/example",
                  "tools_url": f"{base}/tools", "skill_url": f"{base}/skill"},
    }
    out.update(overrides)
    return out


LANGUAGES = inventory.load(HERE.parent / "protocols.json")["clients"]


def readme_for(s) -> str:
    lines = [f"# {s['protocol']} {s['identity']['version']}"]
    lines += [f"- {language}: {marker}" for language, marker in s["packages"].items()]
    lines += [s["links"][k] for k in ("docs_url", "example_url", "tools_url", "skill_url")]
    return "\n".join(lines)


def complete_records(ident, day="2026-11-20") -> list:
    """Every record a complete row needs, for one release."""
    s = spec(ident)
    stamp = lambda hour: f"{day}T{hour:02d}:00:00Z"  # noqa: E731
    tx = order_tx()
    reply = {"result": {"tx": tx, "hash": inventory.decode_tx(tx)["tx_hash"]}}
    resolution, _ = inventory.resolution_record(s, "https://trp.example.test", [reply, reply], stamp(12))
    registry = inventory.registry_record(s, readme_for(s), stamp(13), get=lambda url: {"status": 200, "ok": True})
    clients = [
        {"language": language, "package": marker, "package_version": "0.15.0", "tx3c": "0.25.0", "trix": "0.28.0",
         "run_url": f"{s['links']['ci_run']}/{language}", "date": stamp(11), "result": "pass"}
        for language, marker in LANGUAGES.items()
    ]
    return [
        {"kind": "release", "date": stamp(9), "identity": ident, "source_tag": f"v{ident['version']}",
         "source_url": s["links"]["source_url"], "ci_run": s["links"]["ci_run"],
         "registry_url": s["links"]["registry_url"], "sign_off": {"status": "recorded", "date": day}},
        {"kind": "reconciliation", "date": stamp(10), "coordinate": f"{ident['scope']}/{ident['name']}",
         "result": "new", "checked": ["existing source", "historical catalog", "all registry namespaces"]},
        {"kind": "clients", "date": stamp(11), "identity": ident, "languages": clients, "result": "pass"},
        resolution,
        registry,
        {"kind": "docs", "date": stamp(14), "identity": ident, "docs_url": s["links"]["docs_url"],
         "example_url": s["links"]["example_url"], "result": "pass"},
        {"kind": "tools", "date": stamp(15), "identity": ident, "tools_url": s["links"]["tools_url"],
         "skill_url": s["links"]["skill_url"], "verification_url": f"{s['links']['tools_url']}/verification",
         "tool_operation": ident["operation"], "result": "pass"},
    ]


def proto(coordinate="example/swap", network="preprod", operation="place_order", **extra) -> dict:
    return {"id": coordinate.split("/")[1], "protocol": coordinate, "team": "Example team",
            "operation": operation, "network": network, "coordinate": coordinate, **extra}


CONFIG = {"milestone": {"period": {"start": "2026-10-01", "end": "2026-11-30"}}, "clients": LANGUAGES}
BASELINE = {"groups": [{"title": "Milestone 1.1", "entries": [
    {"protocol": "Transfer", "coordinate": "open-tx3/transfer", "version": "0.1.0"}]}]}


def row(records, **proto_overrides) -> dict:
    """Join records (dates sorted as the inventory reads them) into a row."""
    recs = [dict(r, _file=f"evidence/x/{i:02d}-{r['kind']}.json") for i, r in enumerate(records)]
    recs.sort(key=lambda r: (r.get("date") or "", r["_file"]))
    return inventory.build_row(CONFIG, BASELINE, proto(**proto_overrides), recs)
