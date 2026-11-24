# Refreshing the onboarding inventory

The inventory lives in this public repository, under `inventory/`, on `main`. Evidence is
durable once its PR merges. A reviewer cites one inventory revision by its commit permalink,
`https://github.com/tx3-lang/e2e/blob/<commit>/inventory/README.md`. The records it links sit
at the same commit.

| Path | What it holds | Written by |
|---|---|---|
| `protocols.json` | The selected protocols, their operation, network and registry coordinate, the selection evidence (dated activity, TVL and wallet figures, or named data gaps) and the six client package references | hand, by review |
| `baseline.json` | The Catalyst Fund 14 and Milestone 1.1 entries, tracked separately and never counted as new | hand, by review |
| `evidence/<protocol>/<UTC stamp>-<kind>.json` | One dated record per release, check or run. Records are append-only: a newer record supersedes an older one, and both stay in the history | `inventory.py record` / `ingest` |
| `evidence/<protocol>/cbor/<tx hash>.hex` | The unsigned transaction each resolution returned, named by its hash | `inventory.py ingest` |
| `expect/<protocol>/<version>/` | The release's public example: `inputs.json` (the arguments sent) and `expect.json` (the decoded effects it must produce) | the publication pass, by review |
| `rows/<protocol>.json`, `README.md` | The joined, machine-readable rows and the public Markdown | `inventory.py render`, never by hand |

Every command below runs from the repository root with only `python3` (3.9 or later).

## What makes a row complete

A row is complete when every item below exists for the **same release identity**: registry
scope/name/version, OCI manifest digest, TII digest, Git SHA, network and operation. Evidence
recorded for another identity (an older version, another network, other digests) does not count,
and the row names the mismatch.

| Kind | Supplied by | Complete when |
|---|---|---|
| `release` | the protocol's publication pass | every identity field, the UTC release `date`, `source_tag`, `source_url`, the tagged `ci_run`, the `registry_url` page and `sign_off.status: recorded` are present. The approval receipt stays internal: only its status and date appear here. Two records of one version with different identities are a conflict, because a published version is never replaced |
| `reconciliation` | TxPipe, before counting | `coordinate` matches and `result` is `new`. Public identities and aliases (for example Dano Finance and Danogo) are checked against existing source, the historical catalog and every live registry namespace, and the record lists what was `checked`. A coordinate already in the baseline never counts |
| `resolution` | journey 13, via the refresh workflow | the pulled release matched both digests, the network's public TRP returned an unsigned transaction that a second identical request reproduced byte for byte, and its independently decoded effects match `expect.json` |
| `registry` | journey 13 | the release README carries the version, the six client package references and the docs, example, MCP tools and Skill links, and every recorded link answers |
| `clients` | the client checks' release-scoped result | each of the six languages in `protocols.json` has a row with `language`, `package`, `package_version`, `tx3c`, `trix`, `run_url`, `date` and `result: pass` |
| `docs` | the documentation producer | `docs_url` and the versioned `example_url` are recorded with `result: pass` |
| `tools` | the tools and Skills producer | `tools_url`, `skill_url` and the dated `verification_url` are recorded, `tool_operation` is the release's operation, and `result` is `pass` |

Records other than `release` and `reconciliation` take their identity from the protocol's current
release when they omit it, so a later producer only states what it verified. A record may carry a
`reason`, the diagnosis shown when it is not `pass`.

## When a protocol is published

The publication pass supplies the pinned coordinate and evidence URLs in one reviewed PR, then
starts the public verification.

1. Write the release record and store it:

   ```json
   {
     "date": "2026-11-28T15:04:00Z",
     "identity": {"scope": "open-tx3", "name": "minswap-v2", "version": "0.1.0",
                  "manifest_digest": "sha256:…", "tii_digest": "sha256:…", "git_sha": "…",
                  "network": "preprod", "operation": "place_exact_in_order"},
     "source_tag": "v0.1.0",
     "source_url": "https://github.com/…/tree/v0.1.0",
     "ci_run": "https://github.com/…/actions/runs/…",
     "registry_url": "https://tx3.land/protocol/open-tx3/minswap-v2",
     "sign_off": {"status": "recorded", "date": "2026-11-27"}
   }
   ```

   ```sh
   python3 inventory/lib/inventory.py record --protocol minswap-v2 --kind release release.json
   ```

2. Add `inventory/expect/minswap-v2/0.1.0/inputs.json` (the public example's arguments: funded
   public addresses and amounts, never keys) and `expect.json` (below), taken from the mapping's
   checked-in comparison fixture. Store the `reconciliation` record the same way.
3. Open a PR with only those files, and the `rows/` and `README.md` files `record` regenerated.
   Review and merge it.
4. Start the public verification:

   ```sh
   gh workflow run inventory-refresh.yml -R tx3-lang/e2e -f protocol=minswap-v2
   ```

   The workflow runs journey 13 on the stable toolchain. It pulls the release into an empty
   consumer, checks both digests, resolves the example twice on the network's public TRP, decodes
   and compares the result, and checks the README and its links. It then stores the dated records
   and opens a generated evidence PR. Review and merge that PR. If GitHub Actions may not open
   PRs in this repository, the workflow still pushes its `inventory/<protocol>-<stamp>` branch, and
   a maintainer opens the PR from it.

## When docs, tools, Skills or clients release later

Only the affected row changes. Record what the producer verified, merge, and refresh that protocol:

```sh
python3 inventory/lib/inventory.py record --protocol minswap-v2 --kind docs - <<'EOF'
{"docs_url": "https://…/consuming/", "example_url": "https://…/examples/minswap-v2", "result": "pass"}
EOF
python3 inventory/lib/inventory.py record --protocol minswap-v2 --kind tools tools.json
python3 inventory/lib/inventory.py record --protocol minswap-v2 --kind clients client-checks-result.json
gh workflow run inventory-refresh.yml -R tx3-lang/e2e -f protocol=minswap-v2
```

The refresh rechecks that the release README links the new docs, tools and Skill URLs and that
they answer. The client checks' combined result is stored as it is emitted, with one row per
language. A failed, skipped or unavailable language stays visible as an outstanding item.

## Retries and concurrent refreshes

- Storing a record identical to one already stored adds nothing, so a retried command is
  harmless. A rerun of the workflow adds a newly dated run, and the history keeps both.
- Refreshes of one protocol queue behind each other. Refreshes of different protocols run in
  parallel and write disjoint files under `evidence/<protocol>/` and `rows/<protocol>.json`.
  If two evidence PRs then conflict on the generated `README.md`, merge `main` into the later PR
  and run `python3 inventory/lib/inventory.py render`. The README is derived from the evidence, so
  the result is the same whichever merges first.
- A PR opened by the workflow's token does not trigger the offline `Inventory` check. Run
  `python3 inventory/lib/inventory.py render --check` before merging, or push to the branch to run
  it.

## What is never stored

Credentials, including the TRP key header, never appear in a record. Neither does private owner
correspondence: a release carries only the sign-off status and date. CI environment dumps are
excluded too. `record` refuses credential-shaped fields, and recorded endpoints drop any query
string or user information.

## Expected effects

`expect.json` names each effect the decoded transaction must show, in the operation's own words.
Datum paths walk the Plutus data in its detailed JSON form (`constructor`, `fields`, `int`,
`bytes`, `list`, `map`). For example:

```json
{
  "network": "preprod",
  "outputs": [{
    "effect": "order output",
    "address": "addr_test1z…",
    "lovelace_parts": {"offered": 10000000, "batcher fee": 2000000, "deposit": 2000000},
    "assets": {},
    "datum": [
      {"effect": "receiver", "path": "fields.1.fields.0.bytes", "equals": "…"},
      {"effect": "minimum received", "path": "fields.4.int", "equals": 4321000}
    ]
  }],
  "spends": [{"effect": "pool input", "ref": "<tx hash>#<index>"}],
  "references": [{"effect": "config reference", "ref": "<tx hash>#<index>"}],
  "mint": [{"effect": "receipt minted", "unit": "<policy id>.<asset name hex>", "amount": 1}],
  "signers": [{"effect": "owner signs", "key_hash": "<28-byte hex>"}]
}
```

An output matches on its address, then on exactly its `lovelace` (or the sum of its named
`lovelace_parts`), exactly its `assets` and each datum field. Every output address must belong to
`network`.

## Reproducing a row by hand

Take the TII layer of the release (its digest is in the row) and its `transactions.<operation>.tir`.
Merge the profile's `environment` and `parties` with the example's `inputs.json` into `args`. POST
`{"jsonrpc":"2.0","method":"trp.resolve","id":"1","params":{"tir":<tir>,"args":<args>}}` to the
network's public endpoint, `https://cardano-<network>.trp-m1.demeter.run`, with the public
`dmtr-api-key` that `trix` ships. The answer's `tx` is the unsigned transaction. Decode it with
`python3 inventory/lib/cardano_tx.py < tx.hex`. Journey 13 performs exactly these steps;
`journeys/13-public-resolution/README.md` shows how to run it locally.
