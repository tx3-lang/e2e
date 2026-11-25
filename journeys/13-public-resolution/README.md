# 13-public-resolution

One released protocol interface, checked the way a third party would check it. In a fresh
consumer, `trix use <scope>/<name>:<version>` pulls the release anonymously from the public
registry. The journey checks the OCI manifest digest, the TII digest and the recorded commit
against the release. It then resolves the release's public example on its network's public
TRP, twice, and decodes the unsigned transaction with an independent decoder
(`inventory/lib/cardano_tx.py`, which reads only the CBOR). The decoded result is compared with
the operation's expected effects. Last, the journey checks that the release README exposes the
version, the six client package references, the docs and example links and the MCP tools and
Skill links, and that each link answers.

- **Scope:** live network, read-only. Nothing is signed or submitted, so the transaction hash is
  never on chain. The example's inputs are public, funded addresses; no wallet keys are involved.
- **Input:** `PUBLIC_RESOLUTION_SPEC`, a release spec produced by
  `python3 inventory/lib/inventory.py spec --protocol <id>`. It names the identity (registry
  scope/name/version, both digests, Git SHA, network, operation), the profile, the public inputs
  and the expected effects. Unset ⇒ the journey **skips green**, so it can sit in the
  auto-discovered suite.
- **Output:** dated `resolution` and `registry` records, plus the unsigned CBOR under
  `cbor/<tx hash>.hex`, in `PUBLIC_RESOLUTION_OUT` (default `./evidence`). A failed pull, a digest
  mismatch, an endpoint error or malformed reply, a mismatched effect, CBOR that a second
  identical request does not reproduce byte for byte, or a check that fails unexpectedly all write
  an `outstanding` record with the reason, and fail the journey.
- **Registry-only refresh:** when the spec says `"resolve": false` (the release already has a
  passing resolution and the refresh was not asked to resolve again), the journey pulls and
  verifies the release, skips the resolution and writes only the `registry` record. A failure is
  then recorded against the registry, and the passing resolution stays current.
- **Endpoint:** the network's public Demeter TRP with the public key trix ships, as in
  `trix`'s known networks (`inventory.py endpoint --network <network>`). `TRP_ENDPOINT` /
  `TRP_API_KEY` override them. The record names the endpoint and never a key.
- **Offline test:** `inventory/tests/test_journey.py` runs this journey through `run.sh` with a fake
  `trix` and a loopback TRP that returns the golden preprod Transfer.

The inventory refresh workflow (`.github/workflows/inventory-refresh.yml`) runs this journey
for one protocol and turns its records into an evidence PR; see `inventory/REFRESH.md`.

To run it by hand against a protocol already in the inventory:

```sh
python3 inventory/lib/inventory.py spec --protocol minswap-v2 > /path/to/spec.json
PUBLIC_RESOLUTION_SPEC=/path/to/spec.json PUBLIC_RESOLUTION_OUT=/path/to/evidence \
  ./run.sh --channel stable --journey 13-public-resolution --verbose
python3 inventory/lib/inventory.py ingest --protocol minswap-v2 /path/to/evidence
```
