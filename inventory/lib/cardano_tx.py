"""Independent decoder for one Conway-era Cardano transaction.

It reads the CBOR bytes only: no resolver, SDK or network. It returns a
JSON-ready summary of inputs, reference inputs, outputs with bech32
addresses, values and inline datums as Plutus data, fee, mint, required
signers and the hash of the body bytes.
"""

from __future__ import annotations

import hashlib


class Tag:
    """A tagged CBOR item."""

    def __init__(self, tag: int, value):
        self.tag, self.value = tag, value


class CborMap(list):
    """A CBOR map kept as (key, value) pairs: Plutus map keys may be lists."""


def _decode(buf: bytes, i: int):
    """Decode the item at offset `i`; return (value, offset after it)."""
    if i >= len(buf):
        raise ValueError("truncated CBOR")
    major, info = buf[i] >> 5, buf[i] & 31
    i += 1
    if info < 24:
        arg = info
    elif info <= 27:
        size = 1 << (info - 24)
        arg = int.from_bytes(buf[i : i + size], "big")
        i += size
    elif info == 31 and major in (2, 3, 4, 5):
        arg = None
    else:
        raise ValueError(f"unsupported CBOR item at offset {i - 1}")

    if major == 0:
        return arg, i
    if major == 1:
        return -1 - arg, i
    if major in (2, 3):
        if arg is None:
            chunks = []
            while buf[i] != 0xFF:
                chunk, i = _decode(buf, i)
                chunks.append(chunk)
            data = b"".join(chunks) if major == 2 else "".join(chunks)
            return data, i + 1
        data = bytes(buf[i : i + arg])
        return (data if major == 2 else data.decode()), i + arg
    if major in (4, 5):
        items = [] if major == 4 else CborMap()
        while (len(items) < arg) if arg is not None else buf[i] != 0xFF:
            item, i = _decode(buf, i)
            if major == 5:
                value, i = _decode(buf, i)
                item = (item, value)
            items.append(item)
        return items, (i if arg is not None else i + 1)
    if major == 6:
        value, i = _decode(buf, i)
        return Tag(arg, value), i
    if info in (20, 21):
        return info == 21, i
    if info in (22, 23):
        return None, i
    raise ValueError(f"unsupported CBOR simple value at offset {i - 1}")


_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ value
        for bit in range(5):
            chk ^= gen[bit] if (top >> bit) & 1 else 0
    return chk


def bech32(hrp: str, data: bytes) -> str:
    words, acc, bits = [], 0, 0
    for byte in data:
        acc, bits = (acc << 8) | byte, bits + 8
        while bits >= 5:
            bits -= 5
            words.append((acc >> bits) & 31)
    if bits:
        words.append((acc << (5 - bits)) & 31)
    expanded = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    mod = _polymod(expanded + words + [0] * 6) ^ 1
    checksum = [(mod >> 5 * (5 - n)) & 31 for n in range(6)]
    return hrp + "1" + "".join(_CHARSET[w] for w in words + checksum)


def address(raw: bytes) -> str:
    """Shelley addresses as bech32; Byron addresses as `byron:<hex>`."""
    kind, network = raw[0] >> 4, raw[0] & 0x0F
    if kind == 8:
        return "byron:" + raw.hex()
    hrp = "stake" if kind in (14, 15) else "addr"
    return bech32(hrp if network == 1 else hrp + "_test", raw)


def plutus(item):
    """Plutus data in the detailed JSON schema (`constructor`/`fields`, `int`...)."""
    if isinstance(item, Tag):
        if 121 <= item.tag <= 127 or 1280 <= item.tag <= 1400:
            index = item.tag - 121 if item.tag <= 127 else item.tag - 1280 + 7
            return {"constructor": index, "fields": [plutus(f) for f in item.value]}
        if item.tag == 102:
            return {"constructor": item.value[0], "fields": [plutus(f) for f in item.value[1]]}
        if item.tag in (2, 3):
            magnitude = int.from_bytes(item.value, "big")
            return {"int": magnitude if item.tag == 2 else -1 - magnitude}
        raise ValueError(f"unexpected CBOR tag {item.tag} in Plutus data")
    if isinstance(item, CborMap):
        return {"map": [{"k": plutus(k), "v": plutus(v)} for k, v in item]}
    if isinstance(item, list):
        return {"list": [plutus(x) for x in item]}
    if isinstance(item, bytes):
        return {"bytes": item.hex()}
    if isinstance(item, int) and not isinstance(item, bool):
        return {"int": item}
    raise ValueError("value is not Plutus data")


def _set(item) -> list:
    return item.value if isinstance(item, Tag) and item.tag == 258 else (item or [])


def _refs(item) -> list:
    return [f"{tx.hex()}#{ix}" for tx, ix in _set(item)]


def _assets(multiasset) -> dict:
    return {
        f"{policy.hex()}.{name.hex()}": amount
        for policy, names in (multiasset or [])
        for name, amount in names
    }


def _output(item) -> dict:
    if isinstance(item, CborMap):
        fields = dict(item)
        raw_address, value, datum = fields[0], fields[1], fields.get(2)
    else:
        raw_address, value = item[0], item[1]
        datum = [0, item[2]] if len(item) > 2 else None
    lovelace, multiasset = (value, None) if isinstance(value, int) else value
    out = {"address": address(raw_address), "lovelace": lovelace, "assets": _assets(multiasset)}
    if datum and datum[0] == 0:
        out["datum_hash"] = datum[1].hex()
    elif datum:
        out["datum"] = plutus(_decode(datum[1].value, 0)[0])
    return out


def decode_tx(tx_hex: str) -> dict:
    """Summarize one complete transaction given as hex."""
    raw = bytes.fromhex(tx_hex.strip())
    tx, end = _decode(raw, 0)
    if end != len(raw) or not isinstance(tx, list) or len(tx) != 4:
        raise ValueError("not one complete Conway-era transaction")
    _, body_end = _decode(raw, 1)
    body = dict(tx[0])
    return {
        "tx_hash": hashlib.blake2b(raw[1:body_end], digest_size=32).hexdigest(),
        "inputs": _refs(body.get(0)),
        "reference_inputs": _refs(body.get(18)),
        "outputs": [_output(o) for o in body.get(1, [])],
        "fee": body.get(2),
        "mint": _assets(body.get(9)),
        "required_signers": [h.hex() for h in _set(body.get(14))],
        "network_id": body.get(15),
        "validity_start": body.get(8),
        "ttl": body.get(3),
    }


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(decode_tx(sys.stdin.read()), indent=2, sort_keys=True))
