"""Refreshing the inventory: records on disk, retries, concurrent refreshes,
the committed renderings, the link checker and the journey's commands."""

import contextlib
import filecmp
import http.server
import io
import json
import shutil
import socketserver
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from support import FIXTURES, complete_records, identity, order_expect, order_tx, proto, readme_for, spec

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


class Shapes(Records.__base__):
    """What `record` refuses, and how the join treats malformed records already stored."""

    setUp, tearDown, docs = Records.setUp, Records.tearDown, Records.docs

    def row(self, pid="swap"):
        inventory.render(self.root)
        return inventory.load(self.root / "rows" / f"{pid}.json")

    def tools(self, date="2026-11-22T10:00:00Z", **changes):
        rec = {"kind": "tools", "date": date, "tools_url": "https://example.test/swap/tools",
               "skill_url": "https://example.test/swap/skill", "verification_url": "https://example.test/v",
               "tool_operation": "place_order", "result": "pass"}
        return dict(rec, **changes)

    def test_refuses_nested_credentials(self):
        clients = inventory.load(FIXTURES / "client-checks-combined.json")
        clients["languages"][0]["token"] = "x"
        for rec in (dict(clients, kind="clients"), dict(self.docs(), extra={"api_key": "x"})):
            with self.assertRaises(SystemExit):
                inventory.add_record(self.root, "swap", rec)

    def test_refuses_links_that_are_not_public_http(self):
        for url in ("example.test/docs", "file:///etc/passwd", "https://example.test/a b", "https://example.test/ñ"):
            with self.subTest(url=url), self.assertRaises(SystemExit):
                inventory.add_record(self.root, "swap", dict(self.docs(), docs_url=url))
        clients = inventory.load(FIXTURES / "client-checks-combined.json")
        clients["languages"][0]["run_url"] = "local"
        with self.assertRaises(SystemExit):
            inventory.add_record(self.root, "swap", dict(clients, kind="clients"))

    def test_refuses_shapes_the_join_cannot_read(self):
        release = next(r for r in complete_records(identity(version="0.2.0")) if r["kind"] == "release")
        clients = dict(inventory.load(FIXTURES / "client-checks-combined.json"), kind="clients")
        bad = [
            dict(release, identity=dict(release["identity"], version=None)),
            dict(release, sign_off="recorded"),
            dict(clients, languages={"rust": {}}),
            dict(self.docs(), date="2026-11-22"),
            dict(self.docs(), date="2026-11-22T10:00:00"),
        ]
        for rec in bad:
            with self.subTest(rec=rec), self.assertRaises(SystemExit):
                inventory.add_record(self.root, "swap", rec)

    def test_malformed_stored_records_stay_in_the_history_only(self):
        release = next(r for r in complete_records(identity(version="0.2.0")) if r["kind"] == "release")
        folder = self.root / "evidence" / "swap"
        stored = {
            "20261123T000000Z-release.json": dict(release, identity=dict(release["identity"], version=None)),
            "20261123T010000Z-release.json": dict(release, sign_off="recorded"),
            "20261123T020000Z-clients.json": {"kind": "clients", "date": "2026-11-23T02:00:00Z",
                                              "identity": identity(), "languages": {"rust": {}}},
            "20261123T030000Z-docs.json": dict(self.docs(), date="2026-11-23", identity=identity()),
        }
        for name, rec in stored.items():
            (folder / name).write_text(json.dumps(rec))
        (folder / "20261123T040000Z-tools.json").write_text("{")
        row = self.row()
        self.assertEqual((row["status"], row["identity"]["version"]), ("complete", "0.1.0"))
        invalid = [h for h in row["history"] if h["result"] == "invalid"]
        self.assertEqual(len(invalid), 5)
        self.assertTrue(all(h["reason"] for h in invalid))

    def test_dates_are_normalized_to_utc(self):
        path = inventory.add_record(self.root, "swap", dict(self.docs(), date="2026-11-22T07:00:00-03:00"))
        self.assertEqual((path.name, inventory.load(path)["date"]), ("20261122T100000Z-docs.json", "2026-11-22T10:00:00Z"))

    def test_the_newer_of_two_same_dated_records_wins(self):
        failing = self.tools(result="fail", reason="the Skill names another operation")
        for first, second, status in ((self.tools(), failing, "outstanding"), (failing, self.tools(), "complete")):
            with self.subTest(second=second["result"]):
                self.tearDown()
                self.setUp()
                inventory.add_record(self.root, "swap", first)
                path = inventory.add_record(self.root, "swap", second)
                row = self.row()
                self.assertEqual((path.name, row["status"]), ("20261122T100000Z-tools-2.json", status))
                self.assertEqual(row["evidence"]["tools"]["file"], f"evidence/swap/{path.name}")

    def test_collision_index_orders_numerically(self):
        for n in range(1, 11):
            path = inventory.add_record(self.root, "swap", self.tools(verification_url=f"https://example.test/v/{n}"))
        self.assertEqual(path.name, "20261122T100000Z-tools-10.json")
        self.assertEqual(self.row()["evidence"]["tools"]["file"], f"evidence/swap/{path.name}")

    def test_client_checks_result_is_read_as_emitted(self):
        combined = dict(inventory.load(FIXTURES / "client-checks-combined.json"), kind="clients")
        path = inventory.add_record(self.root, "swap", combined)
        row = self.row()
        self.assertEqual((row["status"], row["evidence"]["clients"]["file"]), ("complete", f"evidence/swap/{path.name}"))
        del combined["languages"][0]["runtime_version"]
        combined["languages"][1].update(result="fail", reason="no record produced")
        inventory.add_record(self.root, "swap", dict(combined, date="2026-11-21T00:00:00Z"))
        self.assertCountEqual(self.row()["missing"], ["clients: rust missing runtime_version",
                                                 "clients: python result fail (no record produced)"])

    def test_producer_identity_is_kept_as_stated(self):
        release = next(r for r in complete_records(identity(version="0.2.0")) if r["kind"] == "release")
        inventory.add_record(self.root, "swap", dict(release, date="2026-11-21T09:00:00Z"))
        combined = dict(inventory.load(FIXTURES / "client-checks-combined.json"), kind="clients")
        path = inventory.add_record(self.root, "swap", combined)
        self.assertEqual(inventory.load(path)["identity"], identity())
        self.assertIn("clients: latest evidence is for another release (version 0.1.0); rerun it for 0.2.0",
                      self.row()["missing"])
        stated = inventory.add_record(self.root, "swap", dict(self.docs(), identity={"version": "0.2.0"}))
        self.assertEqual(inventory.load(stated)["identity"], identity(version="0.2.0"))

    def test_registry_evidence_follows_the_current_links(self):
        inventory.add_record(self.root, "swap", dict(self.docs(), docs_url="https://example.test/swap/docs-v2"))
        self.assertEqual(self.row()["missing"],
                         ["registry: checked older links (docs_url, example_url); rerun the registry check for the current ones"])
        s = inventory.build_spec(self.root, "swap")
        rec = inventory.registry_record(s, readme_for(s), "2026-11-23T10:00:00Z", get=lambda url: {"status": 200, "ok": True})
        inventory.add_record(self.root, "swap", rec)
        self.assertEqual(self.row()["status"], "complete")

    def test_spec_resolves_again_only_without_a_passing_resolution(self):
        self.assertFalse(inventory.build_spec(self.root, "swap")["resolve"])
        self.assertTrue(inventory.build_spec(self.root, "swap", "always")["resolve"])
        failed, _ = inventory.resolution_record(inventory.build_spec(self.root, "swap"), None, [],
                                                "2026-11-23T10:00:00Z", "endpoint error: no reply")
        inventory.add_record(self.root, "swap", failed)
        self.assertTrue(inventory.build_spec(self.root, "swap")["resolve"])

    @unittest.skipUnless(shutil.which("git"), "needs git merge-file")
    def test_two_completions_conflict_instead_of_merging_a_wrong_count(self):
        base = Path(self.tmp.name) / "base"
        base.mkdir()
        cfg = inventory.load(self.root / "protocols.json")
        cfg["protocols"] = [proto(f"example/{name}") for name in ("alpha", "beta", "gamma")]
        (base / "protocols.json").write_text(inventory.dump(cfg))
        shutil.copyfile(self.root / "baseline.json", base / "baseline.json")
        tools = {}
        for name in ("alpha", "beta", "gamma"):
            for rec in complete_records(identity(f"example/{name}")):
                if rec["kind"] == "tools" and name != "beta":
                    tools[name] = rec
                else:
                    inventory.add_record(base, name, rec)
        inventory.render(base)
        for side, name in (("a", "alpha"), ("b", "gamma")):  # rows that are not adjacent
            shutil.copytree(base, Path(self.tmp.name) / side)
            inventory.add_record(Path(self.tmp.name) / side, name, tools[name])
            inventory.render(Path(self.tmp.name) / side)
        merged = subprocess.run(["git", "merge-file", "-p", *(str(Path(self.tmp.name) / d / "README.md") for d in "a")
                                 , str(base / "README.md"), str(Path(self.tmp.name) / "b" / "README.md")],
                                stdout=subprocess.PIPE, text=True)
        self.assertEqual(merged.returncode, 1, "exactly one conflict: the count line")
        conflict = merged.stdout.split("<<<<<<<")[1].split(">>>>>>>")[0]
        self.assertIn("New protocols complete: 2 of 3 (example/alpha, example/beta)", conflict)
        self.assertIn("New protocols complete: 2 of 3 (example/beta, example/gamma)", conflict)


class Garbage(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.recv(1024)
        self.request.sendall(b"garbage\r\n\r\n")


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

    def test_any_failure_is_a_dead_link(self):
        server = socketserver.TCPServer(("127.0.0.1", 0), Garbage)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        urls = ["example.test/docs", "https://example.test/a b", "https://example.test/ñ", "file:///etc/passwd",
                f"http://127.0.0.1:{server.server_address[1]}/"]
        try:
            results = {url: inventory.fetch(url) for url in urls}
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual([r["ok"] for r in results.values()], [False] * len(urls))
        self.assertIn("BadStatusLine", results[urls[-1]]["status"])
        s = spec(identity())
        s["links"]["docs_url"] = "example.test/docs"
        rec = inventory.registry_record(s, readme_for(s), "2026-11-20T13:00:00Z")
        self.assertEqual(rec["result"], "outstanding")
        self.assertIn("dead link example.test/docs (example.test/docs is not an http(s) URL)", rec["reason"])


if __name__ == "__main__":
    unittest.main()
