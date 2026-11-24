"""Resolution comparisons: decoded effects against the expected ones."""

import unittest

from support import FUNDING, OFFERED, Tag, cbor, identity, order_tx, spec

import inventory


def resolve(tx_hex, s=None, repeat=None, reply_hash=None):
    s = s or spec(identity())
    first = {"result": {"tx": tx_hex, "hash": reply_hash or inventory.decode_tx(tx_hex)["tx_hash"]}}
    second = {"result": {"tx": repeat or tx_hex, "hash": "-"}}
    return inventory.resolution_record(s, "https://trp.example.test/x?k=1", [first, second], "2026-11-20T12:00:00Z")[0]


def failed(rec):
    return [c["effect"] for c in rec["checks"] if not c["passed"]]


class Effects(unittest.TestCase):
    def test_matching_order_passes(self):
        rec = resolve(order_tx())
        self.assertEqual((rec["result"], rec["verdict"], rec["reproducible"]), ("pass", "match", True))
        self.assertEqual(failed(rec), [])
        self.assertEqual(rec["endpoint"], "https://trp.example.test/x")

    def test_wrong_network(self):
        rec = resolve(order_tx(network=1))
        self.assertEqual(rec["result"], "outstanding")
        self.assertIn("network", failed(rec))

    def test_wrong_amount(self):
        rec = resolve(order_tx(offered=OFFERED - 1))
        self.assertEqual(failed(rec), ["order output: lovelace = offered + batcher fee + deposit"])

    def test_wrong_recipient(self):
        rec = resolve(order_tx(receiver=bytes(28)))
        self.assertEqual(failed(rec), ["order output: receiver"])

    def test_wrong_contract_datum(self):
        self.assertEqual(failed(resolve(order_tx(direction=1))), ["order output: asset direction"])
        self.assertEqual(failed(resolve(order_tx(min_receive=1))), ["order output: minimum received"])
        self.assertIn("decoded effects differ", resolve(order_tx(direction=1))["reason"])

    def test_inputs_references_mint_and_signers(self):
        key = bytes.fromhex("ab" * 28)
        body = {0: Tag(258, [[FUNDING, 0]]), 1: [], 2: 1, 9: {key: {b"q": 42}}, 14: [key], 18: [[FUNDING, 3]]}
        summary = inventory.decode_tx(cbor([body, {}, True, None]).hex())
        expect = {
            "network": "preprod",
            "spends": [{"effect": "pool input", "ref": FUNDING.hex() + "#0"}, {"effect": "market input", "ref": "ff#9"}],
            "references": [{"effect": "config reference", "ref": FUNDING.hex() + "#3"}],
            "signers": [{"effect": "owner signs", "key_hash": key.hex()}],
            "mint": [{"effect": "receipt minted", "unit": key.hex() + ".71", "amount": 42}],
        }
        self.assertEqual([c["effect"] for c in inventory.compare(summary, expect) if not c["passed"]], ["market input"])


class Outstanding(unittest.TestCase):
    def test_endpoint_error(self):
        s = spec(identity())
        reply = {"error": {"code": -32002, "message": "Input not resolved"}}
        rec, tx = inventory.resolution_record(s, "https://trp.example.test", [reply], "2026-11-20T12:00:00Z")
        self.assertEqual((rec["result"], tx), ("outstanding", None))
        self.assertEqual(rec["reason"], "endpoint error -32002: Input not resolved")
        rec, _ = inventory.resolution_record(s, "https://trp.example.test", [None], "2026-11-20T12:00:00Z")
        self.assertEqual(rec["reason"], "endpoint error: no JSON-RPC response")

    def test_not_reproduced(self):
        rec = resolve(order_tx(), repeat=order_tx(min_receive=2))
        self.assertEqual((rec["result"], rec["reproducible"]), ("outstanding", False))
        self.assertEqual(rec["reason"], "a repeated resolution returned different CBOR")

    def test_returned_hash_must_be_the_body_hash(self):
        self.assertEqual(failed(resolve(order_tx(), reply_hash="00" * 32)), ["hash the endpoint returned"])

    def test_no_expected_effects(self):
        rec = resolve(order_tx(), s=spec(identity(), expect=None))
        self.assertEqual((rec["result"], rec["verdict"]), ("outstanding", "mismatch"))
        self.assertIn("no expected effects", rec["reason"])


class Request(unittest.TestCase):
    TII = {
        "transactions": {"place_order": {"tir": {"encoding": "hex", "content": "00", "version": "v1beta0"}}},
        "profiles": {"preprod": {"environment": {"pool": "aa#0"}, "parties": {"Batcher": "addr_test1batcher"}}},
    }

    def test_merges_profile_and_public_inputs(self):
        body = inventory.build_request(self.TII, spec(identity()))
        self.assertEqual(body["method"], "trp.resolve")
        self.assertEqual(body["params"]["tir"]["content"], "00")
        self.assertEqual(
            body["params"]["args"],
            {"pool": "aa#0", "batcher": "addr_test1batcher", "sender": "addr_test1example", "offered": OFFERED},
        )

    def test_refuses_an_operation_profile_or_example_it_lacks(self):
        for s in (spec(identity(operation="other")), spec(identity(network="mainnet")), spec(identity(), inputs=None)):
            with self.assertRaises(SystemExit):
                inventory.build_request(self.TII, s)


if __name__ == "__main__":
    unittest.main()
