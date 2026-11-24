#!/usr/bin/env python3
"""The protocol onboarding inventory: dated evidence in, public rows out.

`record` and `ingest` add evidence under `evidence/<protocol>/`; `render`
joins it into `rows/<protocol>.json` and `README.md`. `spec`, `request`,
`resolution` and `registry` back the public-resolution journey. Standard
library only, so CI and a third party need nothing installed.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cardano_tx import decode_tx  # noqa: E402

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ("scope", "name", "version", "manifest_digest", "tii_digest", "git_sha", "network", "operation")
BUNDLE = ("resolution", "clients", "docs", "tools", "registry")
KINDS = ("release", "reconciliation") + BUNDLE
RELEASE_FIELDS = ("date", "source_tag", "source_url", "ci_run", "registry_url")
LANGUAGE_FIELDS = ("package", "package_version", "tx3c", "trix", "run_url", "date")
FORBIDDEN_KEYS = {"headers", "api_key", "dmtr-api-key", "token", "secret", "password", "mnemonic", "env"}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path):
    return json.loads(Path(path).read_text())


def dump(data) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def semver(version) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", version or "")[:3])


def identity_of(rec) -> dict:
    return {k: (rec.get("identity") or {}).get(k) for k in IDENTITY}


def records(root: Path, pid: str) -> list:
    folder = root / "evidence" / pid
    found = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        rec = load(path)
        rec["_file"] = f"evidence/{pid}/{path.name}"
        found.append(rec)
    return sorted(found, key=lambda r: (r.get("date") or "", r["_file"]))


def current_release(recs):
    releases = [r for r in recs if r.get("kind") == "release"]
    if not releases:
        return None
    return max(releases, key=lambda r: (semver(identity_of(r)["version"]), r.get("date") or ""))


def latest(recs, kind, ident) -> dict:
    found = [r for r in recs if r.get("kind") == kind and identity_of(r) == ident]
    return found[-1] if found else {}


# --- the join ---------------------------------------------------------------


def _result(rec) -> list:
    return [] if rec.get("result") == "pass" else [rec.get("reason") or f"result {rec.get('result', 'absent')}"]


def _resolution_gaps(rec, ident, cfg) -> list:
    if rec.get("result") != "pass":
        return _result(rec)
    gaps = [f"{k} missing" for k in ("endpoint", "tx_hash", "cbor", "inputs") if not rec.get(k)]
    if rec.get("verdict") != "match":
        gaps.append("decoded effects not matched")
    if not rec.get("reproducible"):
        gaps.append("unsigned CBOR not reproduced byte for byte")
    return gaps


def _client_gaps(rec, ident, cfg) -> list:
    rows = {row.get("language"): row for row in rec.get("languages", [])}
    gaps = []
    for language in cfg["clients"]:
        row = rows.get(language)
        if row is None:
            gaps.append(f"{language} record missing")
            continue
        absent = [f for f in LANGUAGE_FIELDS if not row.get(f)]
        if absent:
            gaps.append(f"{language} missing {', '.join(absent)}")
        if row.get("result") != "pass":
            gaps.append(f"{language} result {row.get('result', 'absent')}")
    return gaps


def _docs_gaps(rec, ident, cfg) -> list:
    return _result(rec) + [f"{k} missing" for k in ("docs_url", "example_url") if not rec.get(k)]


def _tools_gaps(rec, ident, cfg) -> list:
    gaps = _result(rec) + [f"{k} missing" for k in ("tools_url", "skill_url", "verification_url") if not rec.get(k)]
    if rec.get("tool_operation") != ident["operation"]:
        gaps.append(f"tool operation {rec.get('tool_operation')} differs from {ident['operation']}")
    return gaps


def _registry_gaps(rec, ident, cfg) -> list:
    gaps = [f"README lacks {c['effect']}" for c in rec.get("checks", []) if not c.get("passed")]
    gaps += [f"dead link {link['url']} ({link.get('status')})" for link in rec.get("links", []) if not link.get("ok")]
    return gaps or _result(rec)


GAPS = {
    "resolution": _resolution_gaps,
    "clients": _client_gaps,
    "docs": _docs_gaps,
    "tools": _tools_gaps,
    "registry": _registry_gaps,
}


def _release_gaps(proto, recs, release) -> list:
    if release is None:
        return ["release: no publication-pass record yet (version, digests, source tag, CI run, sign-off)"]
    ident = identity_of(release)
    versions = {}
    for rec in recs:
        if rec.get("kind") == "release":
            other = identity_of(rec)
            versions.setdefault(other["version"], set()).add(json.dumps(other, sort_keys=True))
    gaps = [
        f"release: version {v} recorded with conflicting identities; a published version is never replaced"
        for v, seen in sorted(versions.items())
        if len(seen) > 1
    ]
    gaps += [f"release: {k} missing" for k in IDENTITY if not ident[k]]
    gaps += [f"release: {k} missing" for k in RELEASE_FIELDS if not release.get(k)]
    actual = {
        "coordinate": f"{ident['scope']}/{ident['name']}",
        "network": ident["network"],
        "operation": ident["operation"],
    }
    gaps += [
        f"release: {k} {actual[k]} differs from the selected {proto[k]}"
        for k in actual
        if actual[k] != proto[k]
    ]
    sign_off = (release.get("sign_off") or {}).get("status") or "absent"
    if sign_off != "recorded":
        gaps.append(f"release: owner sign-off {sign_off}; the publication pass records it")
    return gaps


def build_row(cfg, baseline, proto, recs) -> dict:
    release = current_release(recs)
    ident = identity_of(release) if release else None
    missing = _release_gaps(proto, recs, release)

    checked = [r for r in recs if r.get("kind") == "reconciliation" and r.get("coordinate") == proto["coordinate"]]
    if not checked:
        missing.append(
            "reconciliation: identity not yet checked against existing source, "
            "the historical catalog and every live registry namespace"
        )
    elif checked[-1].get("result") != "new":
        missing.append(f"reconciliation: {checked[-1].get('result')}: {checked[-1].get('reason', 'not a new identity')}")
    for group in baseline["groups"]:
        if any(e["coordinate"] == proto["coordinate"] for e in group["entries"]):
            missing.append(f"reconciliation: {proto['coordinate']} is already counted in {group['title']}")

    evidence = {}
    for kind in BUNDLE:
        if ident is None:
            missing.append(f"{kind}: waits on the release")
            continue
        same_kind = [r for r in recs if r.get("kind") == kind]
        rec = latest(recs, kind, ident)
        if not rec:
            if same_kind:
                other = identity_of(same_kind[-1])
                diff = ", ".join(f"{k} {other[k]}" for k in IDENTITY if other[k] != ident[k])
                missing.append(f"{kind}: latest evidence is for another release ({diff}); rerun it for {ident['version']}")
            else:
                missing.append(f"{kind}: no evidence for {ident['version']} yet")
            continue
        evidence[kind] = {"file": rec["_file"], "date": rec.get("date")}
        missing += [f"{kind}: {gap}" for gap in GAPS[kind](rec, ident, cfg)]

    test_date = evidence.get("resolution", {}).get("date")
    period = cfg["milestone"]["period"]
    return {
        "id": proto["id"],
        "protocol": proto["protocol"],
        "team": proto["team"],
        "operation": proto["operation"],
        "network": proto["network"],
        "coordinate": proto["coordinate"],
        "status": "outstanding" if missing else "complete",
        "missing": missing,
        "identity": ident,
        "release": {k: release.get(k) for k in RELEASE_FIELDS} if release else None,
        "sign_off": (release.get("sign_off") or {}).get("status") if release else None,
        "evidence": evidence,
        "test_date": test_date,
        "within_period": (period["start"] <= test_date[:10] <= period["end"]) if test_date else None,
        "selection": proto.get("selection"),
        "history": [
            {
                "date": r.get("date"),
                "kind": r.get("kind"),
                "version": identity_of(r)["version"],
                "result": r.get("result"),
                "reason": r.get("reason"),
                "file": r["_file"],
            }
            for r in recs
        ],
    }


# --- rendering --------------------------------------------------------------


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _selection_lines(selection) -> list:
    lines = []
    for metric, data in (selection or {}).items():
        if data.get("gap"):
            lines.append(f"- {metric}: data gap: {data['gap']}")
        else:
            lines.append(f"- {metric}: {data['value']} ({data['as_of']}; [source]({data['source']}))")
    return lines


def render_markdown(cfg, baseline, rows) -> str:
    period = cfg["milestone"]["period"]
    done = sum(1 for r in rows if r["status"] == "complete")
    out = [
        f"# {cfg['title']}",
        "",
        "<!-- Generated by `python3 inventory/lib/inventory.py render` from `inventory/evidence/`. Do not edit. -->",
        "",
        cfg["summary"],
        "",
        f"Milestone period: {period['start']} to {period['end']}. Test dates are the actual UTC dates of each run.",
        "",
        f"New protocols complete: {done} of {len(rows)}. Each new identity counts once across networks and "
        "releases; the baseline below is listed separately and is not counted.",
        "",
        "| Protocol | Team | Operation | Network | Release | Status | Test date |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        release = f"`{r['coordinate']}:{r['identity']['version']}`" if r["identity"] else f"`{r['coordinate']}` unreleased"
        status = "complete" if r["status"] == "complete" else f"outstanding ({len(r['missing'])})"
        date = r["test_date"] or "-"
        if r["within_period"] is False:
            date += " (outside the period)"
        out.append(
            f"| [{r['protocol']}](#{r['id']}) | {r['team']} | `{r['operation']}` | {r['network']} | {release} | {status} | {date} |"
        )
    for r in rows:
        out += ["", f'<a id="{r["id"]}"></a>', f"## {r['protocol']}", ""]
        out.append(f"Team: {r['team']}. Operation `{r['operation']}` on {r['network']}, coordinate `{r['coordinate']}`.")
        if r["missing"]:
            out += ["", "Outstanding:", ""] + [f"- {_cell(m)}" for m in r["missing"]]
        if r["identity"]:
            out += ["", "| Field | Value |", "|---|---|"]
            out += [f"| {k} | `{_cell(v)}` |" for k, v in r["identity"].items() if v]
            out += [f"| {k} | {_cell(v)} |" for k, v in r["release"].items() if v]
            out.append(f"| sign-off | {r['sign_off'] or 'absent'} (receipt kept internally) |")
        if r["evidence"]:
            out += ["", "Evidence:", ""]
            out += [f"- {kind}: [{e['file']}]({e['file']}) ({e['date']})" for kind, e in r["evidence"].items()]
        if r["selection"]:
            out += ["", "Selection evidence:", ""] + _selection_lines(r["selection"])
        if r["history"]:
            out += ["", "| Date | Kind | Version | Result | Diagnosis |", "|---|---|---|---|---|"]
            out += [
                f"| {h['date']} | [{h['kind']}]({h['file']}) | {h['version'] or '-'} | {h['result'] or '-'} | {_cell(h['reason'] or '')} |"
                for h in r["history"]
            ]
    out += ["", "## Baseline", "", baseline["summary"]]
    for group in baseline["groups"]:
        out += ["", f"### {group['title']} ({len(group['entries'])})", "", "| Protocol | Registry entry | Version |", "|---|---|---|"]
        out += [
            f"| {e['protocol']} | [{e['coordinate']}]({baseline['registry_page']}{e['coordinate']}) | {e['version']} |"
            for e in group["entries"]
        ]
    out += ["", "How to reproduce a row and how a release refreshes it: [REFRESH.md](REFRESH.md).", ""]
    return "\n".join(out)


def render(root: Path, check: bool = False) -> int:
    cfg, baseline = load(root / "protocols.json"), load(root / "baseline.json")
    ids = [p["id"] for p in cfg["protocols"]]
    coordinates = [p["coordinate"] for p in cfg["protocols"]]
    if len(set(ids)) != len(ids) or len(set(coordinates)) != len(coordinates):
        raise SystemExit("protocols.json lists a protocol id or coordinate twice; each identity counts once")
    rows = [build_row(cfg, baseline, p, records(root, p["id"])) for p in cfg["protocols"]]
    files = {root / "rows" / f"{r['id']}.json": dump(r) for r in rows}
    files[root / "README.md"] = render_markdown(cfg, baseline, rows)
    stale = [p for p, text in files.items() if not p.exists() or p.read_text() != text]
    if check:
        for path in stale:
            print(f"out of date: {path.relative_to(root)} (run render)", file=sys.stderr)
        return 1 if stale else 0
    for path in stale:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(files[path])
    return 0


# --- evidence ---------------------------------------------------------------


def _forbidden(data) -> list:
    if isinstance(data, dict):
        return [k for k in data if k.lower() in FORBIDDEN_KEYS] + [x for v in data.values() for x in _forbidden(v)]
    if isinstance(data, list):
        return [x for v in data for x in _forbidden(v)]
    return []


def add_record(root: Path, pid: str, rec: dict) -> Path:
    """Store one dated record; an identical retry adds nothing."""
    rec = {k: v for k, v in rec.items() if not k.startswith("_")}
    if rec.get("kind") not in KINDS:
        raise SystemExit(f"unknown evidence kind {rec.get('kind')!r}; expected one of {', '.join(KINDS)}")
    if _forbidden(rec):
        raise SystemExit(f"refusing to store credential-shaped fields: {', '.join(sorted(set(_forbidden(rec))))}")
    if rec["kind"] in BUNDLE and not rec.get("identity"):
        release = current_release(records(root, pid))
        if release is None:
            raise SystemExit(f"{pid}: no release recorded to key this {rec['kind']} evidence by")
        rec["identity"] = identity_of(release)
    rec.setdefault("date", now())
    folder = root / "evidence" / pid
    folder.mkdir(parents=True, exist_ok=True)
    text = dump(rec)
    for existing in sorted(folder.glob("*.json")):
        if existing.read_text() == text:
            return existing
    stamp = re.sub(r"[-:]", "", rec["date"])
    path, n = folder / f"{stamp}-{rec['kind']}.json", 2
    while path.exists():
        path, n = folder / f"{stamp}-{rec['kind']}-{n}.json", n + 1
    path.write_text(text)
    return path


def ingest(root: Path, pid: str, source: Path) -> None:
    for path in sorted(source.glob("*.json")):
        print(add_record(root, pid, load(path)).relative_to(root))
    for cbor in sorted(source.glob("cbor/*.hex")):
        target = root / "evidence" / pid / "cbor" / cbor.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cbor, target)
    render(root)


# --- journey helpers --------------------------------------------------------


def build_spec(root: Path, pid: str) -> dict:
    cfg, recs = load(root / "protocols.json"), records(root, pid)
    release = current_release(recs)
    if release is None:
        raise SystemExit(f"{pid}: no release recorded; the publication pass records one first")
    ident = identity_of(release)
    example = root / "expect" / pid / ident["version"]
    docs, tools = latest(recs, "docs", ident), latest(recs, "tools", ident)
    return {
        "protocol": pid,
        "identity": ident,
        "profile": release.get("profile") or ident["network"],
        "inputs": load(example / "inputs.json") if (example / "inputs.json").exists() else None,
        "expect": load(example / "expect.json") if (example / "expect.json").exists() else None,
        "packages": cfg["clients"],
        "links": {
            "registry_url": release.get("registry_url"),
            "source_url": release.get("source_url"),
            "ci_run": release.get("ci_run"),
            "docs_url": docs.get("docs_url"),
            "example_url": docs.get("example_url"),
            "tools_url": tools.get("tools_url"),
            "skill_url": tools.get("skill_url"),
        },
    }


def build_request(tii: dict, spec: dict) -> dict:
    """The `trp.resolve` call: the operation's TIR, profile arguments, public inputs."""
    operation, profile_name = spec["identity"]["operation"], spec["profile"]
    tx = tii.get("transactions", {}).get(operation)
    profile = tii.get("profiles", {}).get(profile_name)
    if tx is None or profile is None:
        raise SystemExit(f"the pulled TII lacks transaction {operation} or profile {profile_name}")
    if spec.get("inputs") is None:
        raise SystemExit(f"no public example inputs supplied for version {spec['identity']['version']}")
    args = dict(profile.get("environment") or {})
    args.update({k.lower(): v for k, v in (profile.get("parties") or {}).items()})
    args.update(spec["inputs"])
    return {"jsonrpc": "2.0", "method": "trp.resolve", "id": "1", "params": {"tir": tx["tir"], "args": args}}


def at_path(data, path: str):
    for part in path.split("."):
        if isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        elif isinstance(data, dict):
            data = data.get(part)
        else:
            return None
    return data


def _check(effect, expected, actual) -> dict:
    return {"effect": effect, "expected": expected, "actual": actual, "passed": expected == actual}


def _output_checks(want, out) -> list:
    name = want["effect"]
    checks = [_check(f"{name}: address", want["address"], out["address"])]
    if "lovelace" in want:
        checks.append(_check(f"{name}: lovelace", want["lovelace"], out["lovelace"]))
    if want.get("lovelace_parts"):
        parts = want["lovelace_parts"]
        checks.append(_check(f"{name}: lovelace = {' + '.join(parts)}", sum(parts.values()), out["lovelace"]))
    if "assets" in want:
        checks.append(_check(f"{name}: assets", want["assets"], out["assets"]))
    for d in want.get("datum", []):
        checks.append(_check(f"{name}: {d['effect']}", d["equals"], at_path(out.get("datum"), d["path"])))
    return checks


def compare(summary: dict, expect: dict) -> list:
    """Check a decoded transaction against the operation's expected effects."""
    network = expect["network"]
    prefix = "addr1" if network == "mainnet" else "addr_test1"
    elsewhere = sorted({o["address"] for o in summary["outputs"] if not o["address"].startswith(prefix)})
    checks = [_check("network", network, elsewhere or network)]
    if summary.get("network_id") is not None:
        checks.append(_check("body network id", 1 if network == "mainnet" else 0, summary["network_id"]))
    for field, key, source in (("spends", "ref", "inputs"), ("references", "ref", "reference_inputs"),
                               ("signers", "key_hash", "required_signers")):
        for item in expect.get(field, []):
            checks.append(_check(item["effect"], item[key], item[key] if item[key] in summary[source] else "absent"))
    for item in expect.get("mint", []):
        checks.append(_check(item["effect"], item["amount"], summary["mint"].get(item["unit"], 0)))
    for want in expect.get("outputs", []):
        candidates = [o for o in summary["outputs"] if o["address"] == want["address"]]
        if not candidates:
            checks.append(_check(want["effect"], want["address"], "no output at this address"))
            continue
        options = [_output_checks(want, o) for o in candidates]
        checks += max(options, key=lambda cs: sum(c["passed"] for c in cs))
    return checks


def _public(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))


def resolution_record(spec, endpoint, replies, date, error=None):
    """The dated resolution record and the transaction hex, or None on error.

    `replies` are the parsed JSON-RPC answers to repeated identical requests,
    None where an answer was not JSON.
    """
    rec = {"kind": "resolution", "date": date, "identity": spec["identity"], "profile": spec["profile"],
           "endpoint": _public(endpoint) if endpoint else None, "inputs": spec.get("inputs"), "result": "outstanding"}
    if error:
        rec["reason"] = error
        return rec, None
    envelopes = []
    for reply in replies:
        if not isinstance(reply, dict):
            rec["reason"] = "endpoint error: no JSON-RPC response"
            return rec, None
        if reply.get("error"):
            rec["reason"] = f"endpoint error {reply['error'].get('code')}: {reply['error'].get('message')}"
            return rec, None
        envelopes.append(reply.get("result") or {})
    tx = envelopes[0].get("tx") if envelopes else None
    try:
        summary = decode_tx(tx or "")
    except ValueError as err:
        rec["reason"] = f"the endpoint returned no decodable transaction: {err}"
        return rec, None
    checks = [_check("hash the endpoint returned", envelopes[0].get("hash"), summary["tx_hash"])]
    checks += compare(summary, spec["expect"]) if spec.get("expect") else []
    failed = [c["effect"] for c in checks if not c["passed"]]
    rec.update(tx_hash=summary["tx_hash"], cbor=f"cbor/{summary['tx_hash']}.hex", cbor_bytes=len(tx) // 2,
               reproducible=len(envelopes) > 1 and all(e.get("tx") == tx for e in envelopes),
               summary=summary, checks=checks, verdict="mismatch" if failed or not spec.get("expect") else "match")
    if not spec.get("expect"):
        rec["reason"] = f"no expected effects supplied for version {spec['identity']['version']}"
    elif failed:
        rec["reason"] = "decoded effects differ: " + ", ".join(failed)
    elif not rec["reproducible"]:
        rec["reason"] = "a repeated resolution returned different CBOR"
    else:
        rec["result"] = "pass"
    return rec, tx


def fetch(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "tx3-e2e-inventory"})
    try:
        with urllib.request.urlopen(request, timeout=30) as reply:
            return {"status": reply.status, "ok": 200 <= reply.status < 400}
    except urllib.error.HTTPError as err:
        return {"status": err.code, "ok": False}
    except (urllib.error.URLError, OSError) as err:
        return {"status": str(getattr(err, "reason", err)), "ok": False}


def registry_record(spec, readme: str, date: str, get=fetch) -> dict:
    """Check the release README's bundle references and that every link answers."""
    links = spec["links"]
    wanted = [("version", spec["identity"]["version"])]
    wanted += [(f"{language} package reference", marker) for language, marker in spec["packages"].items()]
    wanted += [(key.replace("_url", " link"), links.get(key)) for key in ("docs_url", "example_url", "tools_url", "skill_url")]
    checks = [{"effect": effect, "expected": needle, "passed": bool(needle) and needle in readme} for effect, needle in wanted]
    results = [dict(url=url, **get(url)) for url in sorted({u for u in links.values() if u})]
    rec = {"kind": "registry", "date": date, "identity": spec["identity"], "checks": checks, "links": results}
    problems = [f"README lacks {c['effect']}" for c in checks if not c["passed"]]
    problems += [f"dead link {r['url']} ({r['status']})" for r in results if not r["ok"]]
    rec["result"] = "outstanding" if problems else "pass"
    if problems:
        rec["reason"] = "; ".join(problems)
    return rec


# --- command line -----------------------------------------------------------


def _reply(path):
    try:
        return load(path)
    except (OSError, ValueError):
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="inventory directory")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("render", help="join evidence into rows and README.md").add_argument("--check", action="store_true")
    cmd = sub.add_parser("record", help="store one evidence record (JSON file or -)")
    cmd.add_argument("--protocol", required=True)
    cmd.add_argument("--kind", choices=KINDS, required=True)
    cmd.add_argument("file")
    cmd = sub.add_parser("ingest", help="store a journey's evidence directory and render")
    cmd.add_argument("--protocol", required=True)
    cmd.add_argument("dir", type=Path)
    sub.add_parser("spec", help="the journey spec for a protocol's current release").add_argument("--protocol", required=True)
    cmd = sub.add_parser("request", help="the trp.resolve request for a pulled TII")
    cmd.add_argument("--spec", required=True)
    cmd.add_argument("--tii", required=True)
    for name in ("resolution", "registry"):
        cmd = sub.add_parser(name, help=f"write the {name} record into --out")
        cmd.add_argument("--spec", required=True)
        cmd.add_argument("--out", type=Path, required=True)
        cmd.add_argument("--date", default=None)
    sub.choices["resolution"].add_argument("--endpoint")
    sub.choices["resolution"].add_argument("--response", action="append", default=[])
    sub.choices["resolution"].add_argument("--error")
    sub.choices["registry"].add_argument("--readme", required=True)
    args = parser.parse_args(argv)

    if getattr(args, "protocol", None) is not None:
        known = [p["id"] for p in load(args.root / "protocols.json")["protocols"]]
        if args.protocol not in known:
            raise SystemExit(f"unknown protocol {args.protocol!r}; expected one of {', '.join(known)}")
    if args.command == "render":
        return render(args.root, args.check)
    if args.command == "record":
        rec = json.loads(sys.stdin.read() if args.file == "-" else Path(args.file).read_text())
        rec["kind"] = args.kind
        print(add_record(args.root, args.protocol, rec).relative_to(args.root))
        return render(args.root)
    if args.command == "ingest":
        ingest(args.root, args.protocol, args.dir)
        return 0
    if args.command == "spec":
        print(dump(build_spec(args.root, args.protocol)), end="")
        return 0
    if args.command == "request":
        print(dump(build_request(load(args.tii), load(args.spec))), end="")
        return 0
    spec, date = load(args.spec), args.date or now()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "resolution":
        replies = [_reply(path) for path in args.response]
        rec, tx = resolution_record(spec, args.endpoint, replies, date, args.error)
        if tx:
            (args.out / "cbor").mkdir(exist_ok=True)
            (args.out / rec["cbor"]).write_text(tx + "\n")
    else:
        readme = Path(args.readme)
        rec = registry_record(spec, readme.read_text() if readme.exists() else "", date)
    (args.out / f"{rec['kind']}.json").write_text(dump(rec))
    print(f"{rec['kind']}: {rec['result']}" + (f" ({rec['reason']})" if rec.get("reason") else ""))
    return 0 if rec["result"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
