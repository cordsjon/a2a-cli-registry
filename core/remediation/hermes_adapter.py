"""Hermes LLM diagnosis for CLIs the deterministic classifier abstained on.

Bulkheaded: any Hermes failure (refused/timeout/non200/parse) degrades the
affected batch to unknown/needs-human and records a FailureRecord. Hermes being
down or slow NEVER fails the remediate pass (mirrors the prober's per-future
isolation). Token-frugality: only ever sees the classifier's `unknown` rows."""
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

from core.remediation.proposal import (
    SCHEMA_VERSION, RemediationProposal, FailureRecord,
    FailureClass, FixKind, Confidence,
)

_BATCH = 10

# Map an LLM-returned class string back to the enum; unknown strings abstain.
_CLASS_BY_VALUE = {fc.value: fc for fc in FailureClass}
# fix_kind is derived from class so the LLM cannot mint an auto-safe fix.
_FIXKIND_BY_CLASS = {
    FailureClass.PIP_3RD_PARTY: FixKind.PROPOSE_ONLY,  # LLM-inferred is never auto-safe
    FailureClass.PIP_UNKNOWN: FixKind.PROPOSE_ONLY,
    FailureClass.WRONG_CWD: FixKind.PROPOSE_ONLY,
    FailureClass.CODE_BUG: FixKind.NEEDS_HUMAN,
    FailureClass.ENV_MISSING: FixKind.PROPOSE_ONLY,
    FailureClass.UNKNOWN: FixKind.NEEDS_HUMAN,
}


class HermesHTTPError(Exception):
    def __init__(self, status, body=""):
        super().__init__(f"hermes returned {status}")
        self.status = status
        self.body = body


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unknown(slug, note):
    return RemediationProposal(
        schema_version=SCHEMA_VERSION, slug=slug,
        failure_class=FailureClass.UNKNOWN, fix_kind=FixKind.NEEDS_HUMAN,
        target="", confidence=Confidence.DECLARED_BY_REGEX, evidence=note or "",
    )


class HermesAdapter:
    def __init__(self, *, base_url="http://localhost:9109",
                 model="deepseek-v4-flash", timeout=30.0, now=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._now = now or _utc_now

    def _post(self, payload: dict) -> dict:
        """The single HTTP seam (monkeypatched in tests). Raises
        HermesHTTPError on non-200, urllib errors on connection problems."""
        data = json.dumps({k: v for k, v in payload.items()
                           if not k.startswith("_")}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions", data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise HermesHTTPError(resp.status)
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise HermesHTTPError(exc.code) from exc

    def _build_payload(self, batch):
        msg = "\n\n".join(
            f"slug: {r.slug}\nnote: {r.description or ''}\npath: {r.path or ''}"
            for r in batch)
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content":
                 "You diagnose why a Python CLI failed to run. For each slug "
                 "return strict JSON array of {slug, failure_class, target, "
                 "evidence}. failure_class in: pip-3rd-party, pip-unknown, "
                 "wrong-cwd, code-bug, env-missing, unknown."},
                {"role": "user", "content": msg},
            ],
            "_batch_slugs": [r.slug for r in batch],  # test hook; stripped before POST
        }

    def _parse(self, resp, batch):
        content = resp["choices"][0]["message"]["content"]
        items = json.loads(content)  # raises on non-JSON -> caught as parse failure
        by_slug = {it["slug"]: it for it in items if "slug" in it}
        out = []
        for r in batch:
            it = by_slug.get(r.slug)
            if not it:
                out.append(_unknown(r.slug, r.description))
                continue
            fc = _CLASS_BY_VALUE.get(it.get("failure_class", ""), FailureClass.UNKNOWN)
            out.append(RemediationProposal(
                schema_version=SCHEMA_VERSION, slug=r.slug, failure_class=fc,
                fix_kind=_FIXKIND_BY_CLASS[fc], target=it.get("target", ""),
                confidence=Confidence.LLM_INFERRED,
                evidence=it.get("evidence", "") or (r.description or ""),
            ))
        return out

    def diagnose(self, unknowns, *, max_calls):
        proposals, records = [], []
        batches = [unknowns[i:i + _BATCH] for i in range(0, len(unknowns), _BATCH)]
        for idx, batch in enumerate(batches):
            if idx >= max_calls:
                # Beyond the cap: leave remaining CLIs unknown (no silent truncation).
                proposals.extend(_unknown(r.slug, r.description) for r in batch)
                continue
            try:
                resp = self._post(self._build_payload(batch))
                proposals.extend(self._parse(resp, batch))
            except (ConnectionRefusedError, urllib.error.URLError) as exc:
                self._degrade(batch, "refused", proposals, records)
            except TimeoutError:
                self._degrade(batch, "timeout", proposals, records)
            except HermesHTTPError:
                self._degrade(batch, "non200", proposals, records)
            except (json.JSONDecodeError, KeyError, TypeError, IndexError):
                self._degrade(batch, "parse", proposals, records)
        return proposals, records

    def _degrade(self, batch, reason, proposals, records):
        at = self._now()
        for r in batch:
            proposals.append(_unknown(r.slug, r.description))
            records.append(FailureRecord(slug=r.slug, reason=reason, attempt_at=at))
