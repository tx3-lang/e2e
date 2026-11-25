"""Journey 13 offline, through run.sh: a fake trix serves the pull and a
loopback server plays the public TRP, returning the golden preprod Transfer."""

import hashlib
import http.server
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from support import FIXTURES, LANGUAGES, order_tx

import inventory

REPO = Path(inventory.__file__).resolve().parents[2]
GOLDEN = (FIXTURES / "transfer-preprod.hex").read_text().strip()
GOLDEN_HASH = inventory.decode_tx(GOLDEN)["tx_hash"]
PARTY = (
    "addr_test1qz3ql06nvc602eem2af4aefp7w5ce4ja7nuuarzavnkd06ljl64qlwn"
    "lynjwzevdrufxslpe29y47u5wxmv6nad026lqvehpe5"
)
TOOLS = [shutil.which(tool) for tool in ("bash", "jq", "curl")]
REQUIRED = os.environ.get("INVENTORY_JOURNEY_REQUIRED") == "1"

FAKE_TRIX = """#!/usr/bin/env bash
# Stands in for trix: `--version`, and `use <scope>/<name>:<version>` copying $FAKE_PULL into the cache.
case "$1" in
  --version) echo "trix 0.0.0 (offline fake)" ;;
  use)
    [[ -n "${FAKE_PULL_ERROR:-}" ]] && { echo "error: ${FAKE_PULL_ERROR}" >&2; exit 1; }
    scope="${2%%/*}"; rest="${2#*/}"; dir=".tx3/tii/${scope}/${rest%%:*}/${rest#*:}"
    mkdir -p "${dir}" && cp "${FAKE_PULL}"/* "${dir}/" ;;
  *) exit 2 ;;
esac
"""

TII = {
    "transactions": {"transfer": {"tir": {"encoding": "hex", "content": "00", "version": "v1beta0"}}},
    "profiles": {"preprod": {"environment": {}, "parties": {}}},
}


class TRP(http.server.BaseHTTPRequestHandler):
    """Answers the n-th POST with replies[n] (the last one once they run out) and
    records each request body, path and `dmtr-api-key` header."""

    replies = []
    requests = []
    seen = []

    def do_POST(self):
        TRP.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        TRP.seen.append((self.path, self.headers.get("dmtr-api-key")))
        self._send(json.dumps(TRP.replies[min(len(TRP.requests), len(TRP.replies)) - 1]).encode())

    def do_GET(self):
        self._send(b"ok", 200 if self.path.startswith("/ok/") else 404)

    def _send(self, body, status=200):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@unittest.skipUnless(all(TOOLS) or REQUIRED, "journey 13 needs bash, jq and curl")
class Journey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), TRP)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        TRP.replies[:] = [{"jsonrpc": "2.0", "id": "1", "result": {"tx": GOLDEN, "hash": GOLDEN_HASH}}]
        TRP.requests[:], TRP.seen[:] = [], []
        self.pull = self.dir / "pull"
        self.pull.mkdir()
        (self.pull / "main.tii").write_text(json.dumps(TII))
        (self.pull / "metadata.json").write_text(json.dumps({"digest": "sha256:" + "a" * 64, "commit_sha": "3" * 40}))
        links = {k: f"{self.base}/ok/{k}" for k in ("registry_url", "source_url", "ci_run", *inventory.LINKS)}
        (self.pull / "README.md").write_text("\n".join(["# transfer 0.1.0", *LANGUAGES.values(), *links.values()]))
        self.spec = {
            "protocol": "transfer",
            "identity": {"scope": "open-tx3", "name": "transfer", "version": "0.1.0",
                         "manifest_digest": "sha256:" + "a" * 64,
                         "tii_digest": "sha256:" + hashlib.sha256((self.pull / "main.tii").read_bytes()).hexdigest(),
                         "git_sha": "3" * 40, "network": "preprod", "operation": "transfer"},
            "resolve": True, "profile": "preprod", "inputs": {"quantity": 2_000_000},
            "expect": {"network": "preprod",
                       "spends": [{"effect": "funding input",
                                   "ref": "3e424e75b030997151045a36571942a9e28e95b2f2b411371bda8cedc1537cc7#0"}],
                       "outputs": [{"effect": "payment", "address": PARTY, "lovelace": 2_000_000, "assets": {}}]},
            "packages": dict(LANGUAGES), "links": links,
        }
        self.trix = self.dir / "trix"
        self.trix.write_text(FAKE_TRIX)
        self.trix.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_journey(self, **overrides):
        """Run journey 13; an override of None unsets that variable."""
        spec, out = self.dir / "spec.json", self.dir / "evidence"
        spec.write_text(json.dumps(self.spec))
        env = dict(os.environ, TX3_TRIX_PATH=str(self.trix), FAKE_PULL=str(self.pull), TMPDIR=str(self.dir),
                   PUBLIC_RESOLUTION_SPEC=str(spec), PUBLIC_RESOLUTION_OUT=str(out),
                   TRP_ENDPOINT=f"{self.base}/trp", NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")
        env = {k: v for k, v in {**env, **overrides}.items() if v is not None}
        done = subprocess.run(["bash", str(REPO / "run.sh"), "--journey", "13-public-resolution"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
        found = {p.stem: inventory.load(p) for p in out.glob("*.json")} if out.is_dir() else {}
        return done, found

    def test_release_verified_resolved_and_compared(self):
        done, found = self.run_journey()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual((found["resolution"]["result"], found["resolution"]["verdict"]), ("pass", "match"))
        self.assertEqual(found["resolution"]["endpoint"], f"{self.base}/trp")
        self.assertEqual((self.dir / "evidence" / found["resolution"]["cbor"]).read_text().strip(), GOLDEN)
        self.assertEqual(found["registry"]["result"], "pass")
        self.assertEqual([r["method"] for r in TRP.requests], ["trp.resolve", "trp.resolve"])
        self.assertEqual(TRP.requests[0]["params"]["args"], {"quantity": 2_000_000})

    def test_a_pull_unlike_the_release_is_never_resolved(self):
        cases = {
            "TII digest": lambda: (self.pull / "main.tii").write_text(json.dumps(TII) + " "),
            "manifest digest": lambda: self.spec["identity"].update(manifest_digest="sha256:" + "b" * 64),
            "published commit": lambda: self.spec["identity"].update(git_sha="4" * 40),
        }
        for reason, break_it in cases.items():
            with self.subTest(reason):
                self.tearDown()
                self.setUp()
                break_it()
                done, found = self.run_journey()
                self.assertNotEqual(done.returncode, 0)
                self.assertEqual(found["resolution"]["result"], "outstanding")
                self.assertIn(reason, found["resolution"]["reason"])
                self.assertEqual(TRP.requests, [])

    def test_unknown_network_has_no_public_endpoint(self):
        self.spec["identity"]["network"] = "devnet"
        done, found = self.run_journey()
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(found["resolution"]["reason"], "no public TRP endpoint is known for network 'devnet'")
        self.assertEqual(TRP.requests, [])

    def test_the_public_endpoint_and_key_are_used_without_overrides(self):
        key = "trp1loopbackkey"
        public = json.dumps({"preprod": [f"{self.base}/public-trp", key]})
        done, found = self.run_journey(TRP_ENDPOINT=None, TRP_API_KEY=None, INVENTORY_TEST_PUBLIC_TRP=public)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(TRP.seen, [("/public-trp", key)] * 2)
        self.assertEqual((found["resolution"]["result"], found["resolution"]["endpoint"]), ("pass", f"{self.base}/public-trp"))
        stored = [p.read_text() for p in (self.dir / "evidence").rglob("*") if p.is_file()]
        self.assertFalse([text for text in stored if key in text], "the key never appears in a record")

    def test_cbor_a_second_request_does_not_reproduce_is_outstanding(self):
        other = order_tx()
        TRP.replies.append({"jsonrpc": "2.0", "id": "1", "result": {"tx": other, "hash": inventory.decode_tx(other)["tx_hash"]}})
        done, found = self.run_journey()
        self.assertNotEqual(done.returncode, 0)
        rec = found["resolution"]
        self.assertEqual((rec["result"], rec["reproducible"], rec["reason"]),
                         ("outstanding", False, "a repeated resolution returned different CBOR"))
        self.assertEqual(len(TRP.requests), 2)

    def test_a_malformed_reply_is_an_outstanding_record(self):
        TRP.replies[:] = [{"error": "Unauthorized"}]
        done, found = self.run_journey()
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual((found["resolution"]["result"], found["resolution"]["reason"]),
                         ("outstanding", "endpoint error: Unauthorized"))
        self.assertEqual(found["registry"]["result"], "pass")

    def test_registry_only_refresh_keeps_the_resolution(self):
        self.spec["resolve"] = False
        done, found = self.run_journey()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual((sorted(found), found["registry"]["result"]), (["registry"], "pass"))
        self.assertEqual(TRP.requests, [])
        done, found = self.run_journey(FAKE_PULL_ERROR="registry unavailable")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(sorted(found), ["registry"])
        self.assertIn("registry pull of open-tx3/transfer:0.1.0 failed", found["registry"]["reason"])


class Endpoints(unittest.TestCase):
    def test_each_network_maps_to_its_public_trp(self):
        for network in ("mainnet", "preprod", "preview"):
            url, key = inventory.public_trp(network)
            self.assertEqual(url, f"https://cardano-{network}.trp-m1.demeter.run")
            self.assertTrue(key.startswith("trp1"))
        self.assertEqual(len({key for _, key in inventory.PUBLIC_TRP.values()}), 3)
        with self.assertRaises(SystemExit):
            inventory.public_trp("devnet")


if __name__ == "__main__":
    unittest.main()
