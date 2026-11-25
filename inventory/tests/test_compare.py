"""Resolution comparisons: decoded effects against the expected ones."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import (BATCHER_FEE, DEPOSIT, FUNDING, OFFERED, Tag, cbor, identity, order_expect, order_output,
                     order_tx, spec)

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


class FailurePaths(unittest.TestCase):
    """Each comparison check fails on its own mismatch."""

    def test_output_at_another_script_address_on_the_same_network(self):
        rec = resolve(order_tx(script=bytes.fromhex("ee" * 28)))
        self.assertEqual((rec["result"], failed(rec)), ("outstanding", ["order output"]))

    def test_direct_lovelace_mismatch(self):
        expect = order_expect()
        del expect["outputs"][0]["lovelace_parts"]
        expect["outputs"][0]["lovelace"] = OFFERED + BATCHER_FEE + DEPOSIT - 1
        self.assertEqual(failed(resolve(order_tx(), s=spec(identity(), expect=expect))), ["order output: lovelace"])

    def test_extra_asset(self):
        tx = order_tx(assets={bytes.fromhex("ab" * 28): {b"X": 1}})
        self.assertEqual(failed(resolve(tx)), ["order output: assets"])

    def test_body_network_id_mismatch(self):
        self.assertEqual(failed(resolve(order_tx(network_id=1))), ["body network id"])

    def test_the_best_candidate_output_is_compared(self):
        tx = order_tx(before=[order_output(min_receive=1)])
        rec = resolve(tx)
        self.assertEqual((rec["result"], failed(rec)), ("pass", []))

    def test_mint_reference_and_signer_mismatches(self):
        key = bytes.fromhex("ab" * 28)
        body = {0: Tag(258, [[FUNDING, 0]]), 1: [], 2: 1, 9: {key: {b"q": 42}}, 14: [key], 18: [[FUNDING, 3]]}
        summary = inventory.decode_tx(cbor([body, {}, True, None]).hex())
        expect = {
            "network": "preprod",
            "references": [{"effect": "config reference", "ref": FUNDING.hex() + "#4"}],
            "signers": [{"effect": "owner signs", "key_hash": "cd" * 28}],
            "mint": [{"effect": "receipt minted", "unit": key.hex() + ".71", "amount": 43}],
        }
        checks = {c["effect"]: c for c in inventory.compare(summary, expect)}
        self.assertEqual([e for e, c in checks.items() if not c["passed"]],
                         ["config reference", "owner signs", "receipt minted"])
        self.assertEqual(checks["receipt minted"]["actual"], 42)


class Replies(unittest.TestCase):
    """Whatever the endpoint answers, the result is a record, never a crash."""

    def record(self, *replies):
        return inventory.resolution_record(spec(identity()), "https://trp.example.test", list(replies),
                                           "2026-11-20T12:00:00Z")

    def test_malformed_replies_are_outstanding(self):
        cases = {
            "endpoint error: Unauthorized": {"error": "Unauthorized"},
            "endpoint error: the reply carries no transaction": {"result": "84a0"},
            "the endpoint returned no decodable transaction: truncated CBOR": {"result": {"tx": "849f"}},
            "the endpoint returned no decodable transaction: not one complete Conway-era transaction":
                {"result": {"tx": "8400000000"}},
        }
        for reason, reply in cases.items():
            with self.subTest(reply=reply):
                rec, tx = self.record(reply, reply)
                self.assertEqual((rec["result"], rec["reason"], tx), ("outstanding", reason, None))
        rec, _ = self.record({"result": {"tx": 42}})
        self.assertEqual(rec["reason"], "endpoint error: the reply carries no transaction")
        rec, _ = self.record()
        self.assertEqual(rec["reason"], "endpoint error: no reply")

    def test_a_summary_json_cannot_hold_still_writes_the_record(self):
        huge = order_output(datum=Tag(2, b"\xff" * 1800))  # about 4,300 decimal digits
        tx = order_tx(before=[huge])
        with tempfile.TemporaryDirectory() as tmp:
            s, reply, out = Path(tmp) / "spec.json", Path(tmp) / "reply.json", Path(tmp) / "out"
            s.write_text(json.dumps(spec(identity())))
            reply.write_text(json.dumps({"result": {"tx": tx, "hash": inventory.decode_tx(tx)["tx_hash"]}}))
            args = ["resolution", "--spec", str(s), "--out", str(out), "--response", str(reply), "--response", str(reply)]
            real = inventory.dump
            refuse = mock.patch.object(inventory, "dump", side_effect=lambda d: (
                (_ for _ in ()).throw(ValueError("Exceeds the limit")) if "summary" in d else real(d)))
            for patch in (contextlib.nullcontext(), refuse):
                with self.subTest(patched=patch is refuse), patch, contextlib.redirect_stdout(io.StringIO()):
                    inventory.main(args)
                    rec = inventory.load(out / "resolution.json")
                    self.assertTrue((out / rec["cbor"]).is_file())
            self.assertEqual(rec["result"], "outstanding")
            self.assertIn("could not be recorded: Exceeds the limit", rec["reason"])
            self.assertNotIn("summary", rec)

    def test_a_check_that_crashes_still_writes_the_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            s, out = Path(tmp) / "spec.json", Path(tmp) / "out"
            s.write_text(json.dumps(spec(identity(), expect={"outputs": []})))  # no network: a KeyError
            reply = Path(tmp) / "reply.json"
            reply.write_text(json.dumps({"result": {"tx": order_tx(), "hash": "-"}}))
            with contextlib.redirect_stdout(io.StringIO()):
                code = inventory.main(["resolution", "--spec", str(s), "--out", str(out), "--response", str(reply)])
            self.assertEqual(code, 1)
            self.assertIn("the resolution check failed: KeyError", inventory.load(out / "resolution.json")["reason"])

    def test_the_endpoint_is_recorded_without_user_information(self):
        rec, _ = inventory.resolution_record(spec(identity()), "https://user:secret@trp.example.test:8443/x?k=1#f",
                                             [], "2026-11-20T12:00:00Z")
        self.assertEqual(rec["endpoint"], "https://trp.example.test:8443/x")
        self.assertNotIn("secret", json.dumps(rec))


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
