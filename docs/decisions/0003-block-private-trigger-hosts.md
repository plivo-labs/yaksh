# 0003 Private trigger hosts are blocked by default

Date: 2026-09-29
Status: accepted

## Decision

Yaksh resolves the trigger host and refuses the request if any address is loopback, private, link-local, a cloud metadata address, IPv6 unique-local, or an IPv6 address that carries a private IPv4 address (IPv4-mapped, NAT64 or IPv4-compatible). It then connects to the address it checked, keeps the TLS host name check, and does not follow redirects. `YAKSH_ALLOW_PRIVATE_HOSTS=true` turns the check off. The same check covers the URL of a text agent.

## Why

- The trigger URL is user input, and Yaksh's server sends the request. Without the check, anyone with the API token can reach internal services, such as `http://169.254.169.254/` (cloud credentials) or `http://localhost:5432`.
- Checking the resolved address, not only the host name, stops DNS names that point to private addresses.
- Local development needs private hosts, for example a test agent on `http://localhost:9000`, so the setting exists.

## Other options

- No check. Rejected: server-side request forgery.
- An allowlist of trigger hosts. Rejected: every new provider or webhook needs a config change.
