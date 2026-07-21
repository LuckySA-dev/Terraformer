# Legacy SSH Compatibility Design

Date: 2026-07-21
Status: Approved

## Problem

The structured Cisco and generic read-only connection paths use Scrapli's
`system` transport, which delegates negotiation to the OpenSSH client in the
backend image. An authorized, authentication-free handshake against an older
Cisco Catalyst platform proved that the device and current OpenSSH defaults
have no common key-exchange, host-key, or cipher algorithms. The application
therefore returns a sanitized `device_connection_failed` response before
credentials are evaluated.

The observed device offered only SHA-1 key exchange, RSA host keys, and CBC
ciphers. A bounded handshake reached the authentication boundary when the
client appended these three least-legacy common choices:

- `diffie-hellman-group14-sha1`
- `ssh-rsa`
- `aes256-cbc`

## Selected Design

Define one private, immutable OpenSSH argument tuple in
`backend/app/drivers/transport.py`. Both `ScrapliTransport` and
`ScrapliGenericTransport` pass a fresh copy through Scrapli's
`transport_options.open_cmd` interface.

Each OpenSSH algorithm value begins with `+`. This appends the compatibility
algorithm to OpenSSH's default preference list instead of replacing modern
defaults, so a modern device continues to negotiate a modern algorithm first.
The compatibility list deliberately excludes `diffie-hellman-group1-sha1`,
3DES, and every other unobserved legacy algorithm.

The change applies to structured Cisco IOS/IOS-XE and generic read-only SSH
connections. It does not alter AsyncSSH Web Terminal behavior, credentials,
authentication retries, timeouts, strict host-key verification, driver
capabilities, commands, or any structured write boundary.

## Alternatives Considered

1. Upgrade or reconfigure every switch. This is the preferred long-term
   security outcome but cannot provide application compatibility across older
   models and software images, and Terraformer is not authorized to configure
   devices in phases 0-2.
2. Replace OpenSSH's full algorithm lists with legacy-only values. This was
   rejected because it would force weaker negotiation even for modern devices.
3. Append the smallest verified compatibility set. This is selected because it
   preserves modern defaults while enabling the observed older platform family.

## Security Boundary

These algorithms are weaker than current defaults and exist only for legacy
interoperability. Documentation must state this explicitly. Strict host-key
verification remains an independent control and is not disabled by this
change. No raw SSH exception, device output, address, username, password, host
key, or other identifying lab data may be added to logs, tests, or evidence.

## Verification

Use TDD to require both Scrapli transports to receive exactly the six OpenSSH
arguments for the three appended algorithms. The regression must also prove
that group1 and 3DES are absent. Run focused and full backend format, lint,
type, and network-free tests, validate Compose, rebuild the normal stack, and
then perform one explicitly authorized read-only connection test using the
already encrypted profile. The real-device result remains lab-unverified unless
all metadata required by `docs/lab-test-guide.md` is available.

## Constraints

- Do not use Git commands, commits, pushes, branches, or history operations.
- Do not change `docs/network-automation-final-plan.md`.
- Do not add a structured device write path.
- Do not run device show/configuration commands as part of this fix.
- Preserve sanitized public errors and credential handling.
