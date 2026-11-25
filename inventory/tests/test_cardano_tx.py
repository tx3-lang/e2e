import unittest

from support import FIXTURES, POOL_LP, USER_KEY, Tag, cbor, constr, order_tx

from cardano_tx import CborMap, decode_tx

# A real unsigned Transfer resolved on the preprod public TRP (open-tx3/transfer:0.1.0)
# on 2026-11-24; the endpoint returned this hash for it.
TRANSFER_HASH = "a36c4914b9d2a036c791224bc9bd8ac4f694697d9abc21e02927742c71215b62"
TRANSFER_PARTY = (
    "addr_test1qz3ql06nvc602eem2af4aefp7w5ce4ja7nuuarzavnkd06ljl64qlwn"
    "lynjwzevdrufxslpe29y47u5wxmv6nad026lqvehpe5"
)


class RealTransaction(unittest.TestCase):
    def test_decodes_a_public_trp_result(self):
        tx = decode_tx((FIXTURES / "transfer-preprod.hex").read_text())
        self.assertEqual(tx["tx_hash"], TRANSFER_HASH)
        self.assertEqual(tx["inputs"], ["3e424e75b030997151045a36571942a9e28e95b2f2b411371bda8cedc1537cc7#0"])
        self.assertEqual([o["address"] for o in tx["outputs"]], [TRANSFER_PARTY, TRANSFER_PARTY])
        self.assertEqual([o["lovelace"] for o in tx["outputs"]], [2_000_000, 47_091_734])
        self.assertEqual((tx["fee"], tx["network_id"], tx["mint"]), (1_663_741, 0, {}))


class SyntheticTransactions(unittest.TestCase):
    def test_inline_datum_and_script_address(self):
        order = decode_tx(order_tx())["outputs"][0]
        self.assertTrue(order["address"].startswith("addr_test1z"))
        self.assertEqual(order["datum"]["fields"][1], {"constructor": 0, "fields": [{"bytes": USER_KEY.hex()}]})
        self.assertEqual(order["datum"]["fields"][2], {"bytes": POOL_LP.hex()})
        self.assertTrue(decode_tx(order_tx(network=1))["outputs"][0]["address"].startswith("addr1z"))

    def test_body_fields(self):
        policy = bytes.fromhex("f6" * 28)
        datum = constr(
            0,
            Tag(1280 + 1, []),  # constructor 8
            Tag(2, (2**70).to_bytes(9, "big")),
            CborMap([(b"k", -5)]),
            [1, 2],
        )
        legacy = [bytes([0x61]) + policy, [5_000_000, {policy: {b"A": 7}}], bytes(32)]
        body = {
            0: [[bytes(32), 1]],
            1: [legacy, {0: bytes([0x60]) + policy, 1: 2_000_000, 2: [1, Tag(24, cbor(datum))]}],
            2: 200_000,
            3: 999,
            8: 100,
            9: {policy: {b"A": 7, b"B": -1}},
            14: Tag(258, [policy]),
            18: [[bytes.fromhex("aa" * 32), 2]],
        }
        tx = decode_tx(cbor([body, {}, True, None]).hex())
        self.assertEqual(tx["outputs"][0]["datum_hash"], "00" * 32)
        self.assertEqual(tx["outputs"][0]["assets"], {f"{policy.hex()}.41": 7})
        self.assertEqual(tx["mint"], {f"{policy.hex()}.41": 7, f"{policy.hex()}.42": -1})
        self.assertEqual(tx["reference_inputs"], ["aa" * 32 + "#2"])
        self.assertEqual(tx["required_signers"], [policy.hex()])
        self.assertEqual((tx["ttl"], tx["validity_start"]), (999, 100))
        fields = tx["outputs"][1]["datum"]["fields"]
        self.assertEqual(fields[0], {"constructor": 8, "fields": []})
        self.assertEqual(fields[1], {"int": 2**70})
        self.assertEqual(fields[2], {"map": [{"k": {"bytes": "6b"}, "v": {"int": -5}}]})
        self.assertEqual(fields[3], {"list": [{"int": 1}, {"int": 2}]})

    def test_indefinite_lengths(self):
        # [body, {}, true, null] with the outputs as an indefinite array
        body = cbor({0: [[bytes(32), 0]], 2: 1}).hex()
        output = cbor([bytes([0x60]) + bytes(28), 1_000_000]).hex()
        tx_hex = "84" + "a3" + body[2:] + "01" + "9f" + output + "ff" + "a0f5f6"
        self.assertEqual(decode_tx(tx_hex)["outputs"][0]["lovelace"], 1_000_000)

    def test_rejects_what_is_not_one_transaction(self):
        whole = order_tx()
        for bad in (whole[:-4], whole + "00", cbor([1, 2]).hex(), ""):
            with self.assertRaises(ValueError):
                decode_tx(bad)

    def test_malformed_input_is_a_value_error(self):
        # truncated indefinite array, a body that is not a map, a non-string, deep nesting, short bytes
        for bad in ("849f", "8400000000", 42, None, "9f" * 3000, "8458ff", "84a1007f", "84a100d9"):
            with self.subTest(bad=bad if not isinstance(bad, str) else bad[:12]):
                with self.assertRaises(ValueError):
                    decode_tx(bad)


if __name__ == "__main__":
    unittest.main()
