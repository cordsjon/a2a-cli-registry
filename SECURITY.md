# Security Policy

a2a-cli-registry exposes a network-reachable MCP/A2A endpoint and processes
untrusted catalog text. It has a real attack surface; we take reports seriously.

## Reporting a vulnerability
Email **jonas.cords@gmail.com** with subject `SECURITY: a2a-cli-registry`.
Please do **not** open a public issue for undisclosed vulnerabilities.
Expect an acknowledgement within 72 hours.

## Scope / threat model
The registry is **describe + plan only** — it never executes a managed CLI for a
network caller. Known surface and mitigations (see the design spec §8):
- **Untrusted catalog text** (descriptions, intent_tags, inferred capabilities) is
  returned inert as data on every surface, never as instruction.
- **Webhook bus**: HMAC-signed payloads; outbound SSRF guard + timeouts.
- **Auth**: bearer securityScheme gates A2A and MCP; unauth omits launch specs.
- **Prober isolation**: `probe` executes each enabled CLI's `health_cmd` under
  prober isolation (per-CLI wall-time timeout, SIGKILL on overrun, bounded
  captured output). Isolation bounds resource blast radius but not authorization
  — only probe CLIs you trust. Disable a CLI (`enabled=False` in config) to
  exclude it from probing.

## Supported versions
Pre-1.0 (0.x): only the latest 0.x minor receives security fixes.
