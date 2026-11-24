"""The inventory join: when a row is complete, and why it is not."""

import copy
import unittest

from support import CONFIG, BASELINE, complete_records, identity, proto, readme_for, row, spec

import inventory


def replace(records, kind, **changes):
    out = copy.deepcopy(records)
    for rec in out:
        if rec["kind"] == kind:
            rec.update(changes)
    return out


class Complete(unittest.TestCase):
    def test_every_item_for_one_release(self):
        r = row(complete_records(identity()))
        self.assertEqual((r["status"], r["missing"]), ("complete", []))
        self.assertEqual(set(r["evidence"]), set(inventory.BUNDLE))
        self.assertEqual((r["test_date"], r["within_period"]), ("2026-11-20T12:00:00Z", True))

    def test_retried_identical_release_still_complete(self):
        records = complete_records(identity())
        self.assertEqual(row(records + [copy.deepcopy(records[0])])["status"], "complete")

    def test_test_date_outside_the_period_is_flagged_not_hidden(self):
        r = row(complete_records(identity(), day="2026-12-02"))
        self.assertEqual((r["status"], r["within_period"]), ("complete", False))


class Outstanding(unittest.TestCase):
    def test_nothing_recorded_names_every_item(self):
        r = row([])
        self.assertEqual(r["status"], "outstanding")
        self.assertEqual([m.split(":")[0] for m in r["missing"]], ["release", "reconciliation", *inventory.BUNDLE])

    def test_stale_bundle_version(self):
        records = complete_records(identity())
        newer = copy.deepcopy(records[0])
        newer.update(identity=identity(version="0.2.0"), date="2026-11-21T09:00:00Z")
        r = row(records + [newer])
        self.assertEqual(r["identity"]["version"], "0.2.0")
        self.assertIn(
            "resolution: latest evidence is for another release (version 0.1.0); rerun it for 0.2.0", r["missing"]
        )
        self.assertEqual(len([m for m in r["missing"] if "another release" in m]), len(inventory.BUNDLE))

    def test_wrong_network_resolve(self):
        records = replace(complete_records(identity()), "resolution", identity=identity(network="mainnet"))
        self.assertEqual(
            row(records)["missing"],
            ["resolution: latest evidence is for another release (network mainnet); rerun it for 0.1.0"],
        )

    def test_release_on_another_network_than_selected(self):
        r = row(complete_records(identity(network="mainnet")))
        self.assertIn("release: network mainnet differs from the selected preprod", r["missing"])

    def test_missing_language_record(self):
        records = complete_records(identity())
        clients = next(rec for rec in records if rec["kind"] == "clients")
        clients["languages"] = [x for x in clients["languages"] if x["language"] != "swift"]
        r = row(records)
        self.assertEqual(r["missing"], ["clients: swift record missing"])
        self.assertEqual(len(clients["languages"]), len(CONFIG["clients"]) - 1)

    def test_language_without_its_run(self):
        records = complete_records(identity())
        next(rec for rec in records if rec["kind"] == "clients")["languages"][0].update(run_url="", result="fail")
        first = next(iter(CONFIG["clients"]))
        self.assertEqual(row(records)["missing"], [f"clients: {first} missing run_url", f"clients: {first} result fail"])

    def test_dead_registry_link(self):
        s = spec(identity())
        dead = s["links"]["docs_url"]
        rec = inventory.registry_record(
            s, readme_for(s), "2026-11-20T13:00:00Z",
            get=lambda url: {"status": 404, "ok": False} if url == dead else {"status": 200, "ok": True},
        )
        records = [rec if r["kind"] == "registry" else r for r in complete_records(identity())]
        self.assertEqual(row(records)["missing"], [f"registry: dead link {dead} (404)"])

    def test_readme_without_the_skill(self):
        s = spec(identity())
        readme = readme_for(s).replace(s["links"]["skill_url"], "")
        rec = inventory.registry_record(s, readme, "2026-11-20T13:00:00Z", get=lambda url: {"status": 200, "ok": True})
        records = [rec if r["kind"] == "registry" else r for r in complete_records(identity())]
        self.assertEqual(row(records)["missing"], ["registry: README lacks skill link"])

    def test_duplicate_versions_with_different_digests(self):
        records = complete_records(identity())
        clash = copy.deepcopy(records[0])
        clash["identity"]["manifest_digest"] = "sha256:" + "9" * 64
        r = row(records + [clash])
        self.assertIn(
            "release: version 0.1.0 recorded with conflicting identities; a published version is never replaced",
            r["missing"],
        )

    def test_release_without_a_digest(self):
        records = replace(complete_records(identity()), "release", identity=dict(identity(), tii_digest=None))
        self.assertIn("release: tii_digest missing", row(records)["missing"])

    def test_sign_off_not_recorded(self):
        records = replace(complete_records(identity()), "release", sign_off={"status": "pending"})
        self.assertEqual(
            row(records)["missing"], ["release: owner sign-off pending; the publication pass records it"]
        )

    def test_failed_resolution_keeps_its_diagnosis(self):
        records = replace(complete_records(identity()), "resolution", result="outstanding",
                          reason="endpoint error -32002: Input not resolved")
        self.assertIn("resolution: endpoint error -32002: Input not resolved", row(records)["missing"])

    def test_tool_for_another_operation(self):
        records = replace(complete_records(identity()), "tools", tool_operation="cancel_order")
        self.assertEqual(row(records)["missing"], ["tools: tool operation cancel_order differs from place_order"])

    def test_identity_already_counted_or_not_new(self):
        r = row(complete_records(identity("open-tx3/transfer")), coordinate="open-tx3/transfer")
        self.assertIn("reconciliation: open-tx3/transfer is already counted in Milestone 1.1", r["missing"])
        records = replace(complete_records(identity()), "reconciliation", result="duplicate", reason="same as x/y")
        self.assertEqual(row(records)["missing"], ["reconciliation: duplicate: same as x/y"])


class Rendering(unittest.TestCase):
    def test_incomplete_team_cannot_hide_a_complete_one(self):
        done = row(complete_records(identity()))
        waiting = inventory.build_row(CONFIG, BASELINE, proto("example/lending"), [])
        cfg = dict(CONFIG, title="T", summary="S")
        baseline = dict(BASELINE, summary="B", registry_page="https://tx3.land/protocol/")
        for rows in ([done, waiting], [waiting, done]):
            text = inventory.render_markdown(cfg, baseline, rows)
            self.assertIn("New protocols complete: 1 of 2.", text)
            self.assertIn("| [example/swap](#swap) | Example team | `place_order` | preprod | `example/swap:0.1.0` | complete |", text)
            self.assertIn("outstanding (7)", text)


if __name__ == "__main__":
    unittest.main()
