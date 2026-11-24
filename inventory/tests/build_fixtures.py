"""Regenerate fixtures/example/: a rendered inventory with one complete row
and one outstanding row. Run `python3 inventory/tests/build_fixtures.py`
after changing record shapes; test_refresh checks the copy is current."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from support import FIXTURES, LANGUAGES, complete_records, identity, inventory, order_tx, proto

EXAMPLE = FIXTURES / "example"


def build(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    cfg = {
        "title": "Example inventory (test fixture)",
        "summary": "Fixture data only: one complete row and one row outstanding for a missing client record.",
        "milestone": {"name": "Example", "period": {"start": "2026-10-01", "end": "2026-11-30"}},
        "clients": LANGUAGES,
        "protocols": [proto("example/swap"), proto("example/lending", operation="supply")],
    }
    baseline = {"summary": "Fixture baseline.", "registry_page": "https://tx3.land/protocol/",
                "groups": [{"id": "earlier", "title": "Earlier", "entries": [
                    {"protocol": "Transfer", "coordinate": "open-tx3/transfer", "version": "0.1.0"}]}]}
    (root / "protocols.json").write_text(inventory.dump(cfg))
    (root / "baseline.json").write_text(inventory.dump(baseline))
    lending = complete_records(identity("example/lending", operation="supply"))
    clients = next(rec for rec in lending if rec["kind"] == "clients")
    clients["languages"] = [row for row in clients["languages"] if row["language"] != "swift"]
    clients.update(result="fail", reason="swift: no macOS runner was available")
    for pid, records in (("swap", complete_records(identity())), ("lending", lending)):
        for rec in records:
            inventory.add_record(root, pid, rec)
            if rec["kind"] == "resolution":
                cbor = root / "evidence" / pid / rec["cbor"]
                cbor.parent.mkdir(exist_ok=True)
                cbor.write_text(order_tx() + "\n")
    inventory.render(root)


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else EXAMPLE)
    print(json.dumps(sorted(str(p.relative_to(EXAMPLE)) for p in EXAMPLE.rglob("*") if p.is_file()), indent=1))
