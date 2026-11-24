"""Refreshing the inventory: records on disk, retries, concurrent refreshes,
the committed renderings, the link checker and the journey's commands."""

import contextlib
import filecmp
import http.server
import io
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from support import FIXTURES, complete_records, identity, order_expect, order_tx, spec

import build_fixtures
import inventory

LIVE = Path(inventory.__file__).resolve().parents[1]


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class Committed(unittest.TestCase):
    def test_live_inventory_is_rendered(self):
        self.assertEqual(inventory.render(LIVE, check=True), 0)

    def test_example_shows_one_complete_and_one_outstanding_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_fixtures.build(Path(tmp) / "example")
            self.assertEqual(tree(Path(tmp) / "example"), tree(build_fixtures.EXAMPLE), "run build_fixtures.py")
        rows = {p.stem: inventory.load(p) for p in (build_fixtures.EXAMPLE / "rows").glob("*.json")}
        self.assertEqual(rows["swap"]["status"], "complete")
        self.assertEqual((rows["lending"]["status"], rows["lending"]["missing"]),
                         ("outstanding", ["clients: swift record missing"]))


class Records(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "inventory"
        shutil.copytree(build_fixtures.EXAMPLE, self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def docs(self, version="0.1.0"):
        return {"kind": "docs", "date": "2026-11-22T10:00:00Z", "docs_url": "https://example.test/v2",
                "example_url": "https://example.test/v2/example", "result": "pass"}

    def test_refresh_touches_only_its_protocol_and_a_retry_adds_nothing(self):
        before = tree(self.root)
        inventory.add_record(self.root, "lending", self.docs())
        inventory.render(self.root)
        after = tree(self.root)
        changed = sorted(k for k in after if before.get(k) != after[k])
        self.assertEqual(changed, ["README.md", "evidence/lending/20261122T100000Z-docs.json", "rows/lending.json"])
        inventory.add_record(self.root, "lending", self.docs())
        inventory.render(self.root)
        self.assertEqual(tree(self.root), after)

    def test_concurrent_refreshes_of_two_protocols_merge(self):
        copies = [Path(self.tmp.name) / name for name in ("a", "b")]
        for copy_root, pid in zip(copies, ("swap", "lending")):
            shutil.copytree(self.root, copy_root)
            inventory.add_record(copy_root, pid, self.docs())
            inventory.render(copy_root)
        for copy_root in copies:  # what merging both evidence PRs leaves in Git
            shutil.copytree(copy_root / "evidence", self.root / "evidence", dirs_exist_ok=True)
        inventory.render(self.root)
        for copy_root, pid in zip(copies, ("swap", "lending")):
            self.assertTrue(filecmp.cmp(copy_root / "rows" / f"{pid}.json", self.root / "rows" / f"{pid}.json", False))

    def test_identity_comes_from_the_current_release(self):
        path = inventory.add_record(self.root, "swap", self.docs())
        self.assertEqual(inventory.load(path)["identity"], identity())
        with self.assertRaises(SystemExit):
            inventory.add_record(self.root, "unknown", self.docs())

    def test_refuses_credentials_and_unknown_kinds(self):
        with self.assertRaises(SystemExit):
            inventory.add_record(self.root, "swap", dict(self.docs(), headers={"dmtr-api-key": "x"}))
        with self.assertRaises(SystemExit):
            inventory.add_record(self.root, "swap", {"kind": "env-dump"})

    def test_spec_carries_the_example_and_links(self):
        example = self.root / "expect" / "swap" / "0.1.0"
        example.mkdir(parents=True)
        (example / "inputs.json").write_text(json.dumps({"sender": "addr_test1example"}))
        (example / "expect.json").write_text(json.dumps(order_expect()))
        s = inventory.build_spec(self.root, "swap")
        self.assertEqual((s["identity"], s["profile"], s["inputs"]), (identity(), "preprod", {"sender": "addr_test1example"}))
        self.assertEqual(s["links"]["skill_url"], "https://example.test/swap/skill")

    def test_journey_commands_write_records(self):
        s, out = Path(self.tmp.name) / "spec.json", Path(self.tmp.name) / "out"
        s.write_text(json.dumps(spec(identity())))
        reply = Path(self.tmp.name) / "reply.json"
        tx = order_tx()
        reply.write_text(json.dumps({"result": {"tx": tx, "hash": inventory.decode_tx(tx)["tx_hash"]}}))
        args = ["resolution", "--spec", str(s), "--out", str(out), "--endpoint", "https://trp.example.test"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(inventory.main(args + ["--response", str(reply), "--response", str(reply)]), 0)
            rec = inventory.load(out / "resolution.json")
            self.assertEqual((out / rec["cbor"]).read_text().strip(), tx)
            self.assertEqual(inventory.main(args + ["--error", "registry pull failed"]), 1)
            self.assertEqual(inventory.main(["--root", str(self.root), "ingest", "--protocol", "swap", str(out)]), 0)
        self.assertIn("registry pull failed", inventory.load(self.root / "rows" / "swap.json")["missing"][0])


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/ok" else 404)
        self.end_headers()

    def log_message(self, *args):
        pass


class Links(unittest.TestCase):
    def test_fetch_reports_live_and_dead_links(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            self.assertEqual(inventory.fetch(f"{base}/ok"), {"status": 200, "ok": True})
            self.assertEqual(inventory.fetch(f"{base}/gone"), {"status": 404, "ok": False})
        finally:
            server.shutdown()
            server.server_close()
        self.assertFalse(inventory.fetch(base + "/ok")["ok"])


if __name__ == "__main__":
    unittest.main()
