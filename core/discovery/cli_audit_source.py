import json
from core.discovery.base import CliRecord
from core.capability.model import CapabilityRecord


class SchemaError(ValueError):
    """cli-audit JSON drifted from the expected schema — fail closed."""


_REQUIRED_CLI_KEYS = {"slug", "lang", "path"}


class CliAuditSource:
    def __init__(self, json_path: str):
        self.json_path = json_path

    def discover(self) -> list[CliRecord]:
        with open(self.json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if "clis" not in data:
            raise SchemaError("cli-audit JSON missing 'clis' key")
        run_id = data.get("run_id")
        records = []
        for entry in data["clis"]:
            missing = _REQUIRED_CLI_KEYS - entry.keys()
            if missing:
                raise SchemaError(f"cli entry missing required keys: {sorted(missing)}")
            cap = None
            if "capability" in entry:
                c = entry["capability"]
                cap = CapabilityRecord(
                    intent_tags=c.get("intent_tags", []),
                    input_types=c.get("input_types", []),
                    output_types=c.get("output_types", []),
                    side_effect=c.get("side_effect", "unknown"),
                    confidence="declared",
                )
            records.append(CliRecord(
                slug=entry["slug"], lang=entry["lang"], path=entry["path"],
                bucket=entry.get("bucket"), project=entry.get("project"),
                description=entry.get("description", ""), declared_capability=cap,
                source_class="cli_audit", source_run_id=run_id,
            ))
        return records
