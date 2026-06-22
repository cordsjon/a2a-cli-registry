from dataclasses import dataclass


@dataclass
class VocabularyRegistry:
    registered: set[str]
    aliases: dict[str, str]

    def canonicalize(self, port: str) -> str:
        return self.aliases.get(port, port)

    def admit(self, port: str) -> tuple[str, bool]:
        """Return (canonical_port, is_registered). Unregistered ports are
        quarantined into the unverified: namespace and excluded from edges."""
        canonical = self.canonicalize(port)
        if canonical in self.registered:
            return canonical, True
        return f"unverified:{canonical}", False

    def is_edge_eligible(self, port: str) -> bool:
        """Only registered (non-unverified) ports form call-graph edges."""
        return port in self.registered and not port.startswith("unverified:")
