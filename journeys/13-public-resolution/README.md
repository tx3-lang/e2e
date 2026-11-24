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
  mismatch, an endpoint error, a mismatched effect or CBOR that a second identical request does
  not reproduce byte for byte all write an `outstanding` record with the reason, and fail the
  journey.
- **Endpoint:** the network's public Demeter TRP with the public key trix ships, as in
  `trix`'s known networks. `TRP_ENDPOINT` / `TRP_API_KEY` override them. The record names
  the endpoint and never a key.

The inventory refresh workflow (`.github/workflows/inventory-refresh.yml`) runs this journey
for one protocol and turns its records into an evidence PR; see `inventory/REFRESH.md`.

To run it by hand against a protocol already in the inventory:

```sh
python3 inventory/lib/inventory.py spec --protocol minswap-v2 > /path/to/spec.json
PUBLIC_RESOLUTION_SPEC=/path/to/spec.json PUBLIC_RESOLUTION_OUT=/path/to/evidence \
  ./run.sh --channel stable --journey 13-public-resolution --verbose
python3 inventory/lib/inventory.py ingest --protocol minswap-v2 /path/to/evidence
```
