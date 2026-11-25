#!/usr/bin/env python3
"""Serve one tx3 protocol image over the OCI distribution API, for harness tests.

It holds the same layers `trix publish` pushes (application/tx3 source and
application/tii+json interface), so `trix use` pulls it like a public release.
Writes the listening port and the manifest digest to the given files.
"""
import argparse
import hashlib
import http.server
import json
import pathlib


def blob(media_type, data):
    return {"mediaType": media_type, "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "size": len(data)}, data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ("tii", "source", "scope", "name", "version", "commit-sha",
                 "port-file", "digest-file"):
        p.add_argument(f"--{flag}", required=True)
    ns = p.parse_args()

    published = 1735689600  # fixed, so the fixture manifest digest is reproducible
    config = json.dumps({"name": ns.name, "scope": ns.scope, "published_date": published,
                         "version": ns.version, "commit_sha": ns.commit_sha}).encode()
    config_desc, _ = blob("application/vnd.oci.image.config.v1+json", config)
    layers = [blob("application/tx3", pathlib.Path(ns.source).read_bytes()),
              blob("application/tii+json", pathlib.Path(ns.tii).read_bytes())]
    blobs = {config_desc["digest"]: config, **{d["digest"]: data for d, data in layers}}
    manifest = json.dumps({
        "schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": config_desc, "layers": [d for d, _ in layers]}).encode()
    digest = "sha256:" + hashlib.sha256(manifest).hexdigest()
    repo = f"/v2/{ns.scope.lower()}/{ns.name.lower()}"

    class Handler(http.server.BaseHTTPRequestHandler):
        def reply(self, body, content_type, extra=None):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command == "GET":
                self.wfile.write(body)

        def do_GET(self):
            if self.path == "/v2/":
                return self.reply(b"{}", "application/json")
            if self.path in (f"{repo}/manifests/{ns.version}", f"{repo}/manifests/{digest}"):
                return self.reply(manifest, "application/vnd.oci.image.manifest.v1+json",
                                  {"Docker-Content-Digest": digest})
            if self.path.startswith(f"{repo}/blobs/") and self.path.rsplit("/", 1)[1] in blobs:
                return self.reply(blobs[self.path.rsplit("/", 1)[1]], "application/octet-stream")
            self.send_error(404)

        do_HEAD = do_GET

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    pathlib.Path(ns.digest_file).write_text(digest)
    pathlib.Path(ns.port_file).write_text(str(server.server_port))
    server.serve_forever()


if __name__ == "__main__":
    main()
