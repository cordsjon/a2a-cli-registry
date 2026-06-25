"""Paperclip issue tracking for remediation proposals.

Clusters proposals by (failure_class, target) -> one issue per cluster (not per
CLI). Idempotency via an order-independent cluster hash embedded in each issue
title; duplicate detection reads `paperclip.sh list --json` (machine-readable),
never scraped free text. Missing paperclip.sh -> warn + skip, never raise
(proposals.json is already written by the caller before this runs)."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

from core.remediation.proposal import FixKind

# Only these fix_kinds get filed. auto-safe is excluded (a successful SafeFixer
# leaves no issue; an armed-but-failed one is re-filed by the caller).
_FILED_KINDS = {FixKind.PROPOSE_ONLY, FixKind.NEEDS_HUMAN}


def cluster_hash(failure_class_value: str, target: str, member_slugs) -> str:
    """Stable, ORDER-INDEPENDENT cluster id (spec §3.3)."""
    payload = (failure_class_value + "\0" + target + "\0"
               + "\0".join(sorted(member_slugs)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


class PaperclipClient:
    def __init__(self, script="paperclip.sh"):
        self.script = script

    def available(self) -> bool:
        return shutil.which(self.script) is not None

    def list_open_hashes(self) -> set:
        """Read open issues via `list --json`; extract embedded cluster hashes
        from titles formatted '[remediate:<hash>] ...'. A format/connection
        failure raises CalledProcessError/JSONDecodeError to the caller, which
        surfaces it distinctly (never a silent idempotency break)."""
        out = subprocess.run([self.script, "list", "--json"],
                             capture_output=True, text=True, check=True)
        issues = json.loads(out.stdout)
        hashes = set()
        for it in issues:
            title = it.get("title", "")
            if title.startswith("[remediate:") and "]" in title:
                hashes.add(title[len("[remediate:"):title.index("]")])
        return hashes

    def bulk_create(self, yaml_text: str) -> None:
        fd, tmp = tempfile.mkstemp(suffix=".yaml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(yaml_text)
            subprocess.run([self.script, "bulk-create", tmp], check=True)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


class PaperclipAdapter:
    def __init__(self, client=None, *, session_id=""):
        self.client = client or PaperclipClient()
        self.session_id = session_id

    def _cluster(self, proposals):
        clusters = {}
        for p in proposals:
            if p.fix_kind not in _FILED_KINDS:
                continue
            key = (p.failure_class.value, p.target)
            clusters.setdefault(key, []).append(p)
        return clusters

    def _yaml(self, title, members):
        body = "\\n".join(f"- {p.slug}: {p.evidence}" for p in members)
        lines = [
            "- title: " + json.dumps(title),
            "  body: " + json.dumps(f"session={self.session_id}\\n{body}"),
        ]
        return "\n".join(lines) + "\n"

    def file(self, proposals, *, dry_run=True):
        if not self.client.available():
            print("remediate: paperclip.sh not found; skipping issue filing "
                  "(proposals.json already written)", file=sys.stderr)
            return []
        clusters = self._cluster(proposals)
        open_hashes = set() if dry_run else self.client.list_open_hashes()
        refs = []
        for (fc_value, target), members in clusters.items():
            slugs = [p.slug for p in members]
            h = cluster_hash(fc_value, target, slugs)
            if h in open_hashes:
                continue  # idempotent: cluster already filed
            title = f"[remediate:{h}] {fc_value} / {target} ({len(members)} CLIs)"
            if not dry_run:
                self.client.bulk_create(self._yaml(title, members))
            refs.append({"title": title, "hash": h, "members": slugs, "dry_run": dry_run})
        return refs
