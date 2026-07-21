# Device Connection Route Method Design

Date: 2026-07-21
Status: Approved

## Problem

`GET /api/devices/connection-test` currently falls through to
`GET /api/devices/{device_id}`. FastAPI then validates the literal
`connection-test` as a UUID and returns a misleading 422 validation response.
The candidate connection endpoint is intentionally POST-only.

## Design

Constrain the device-detail GET route with Starlette's UUID path converter:
`/{device_id:uuid}`. A non-UUID segment will no longer enter device UUID
validation, allowing the existing static POST route to produce the correct
405 Method Not Allowed response for GET requests.

The candidate POST endpoint, registered-device endpoints, request schemas,
drivers, and hardware behavior remain unchanged. No request in automated
verification may contact a network device.

## Verification

Add an authenticated API regression test that first demonstrates the current
422 response and then requires GET on `/api/devices/connection-test` to return
405 with `Allow: POST`. Run the focused test followed by backend formatting,
lint, type checking, and the network-free test suite.

## Constraints

- Do not use Git commands, commits, pushes, branches, or history operations.
- Do not connect to, probe, or otherwise access real hardware.
- Do not change the POST connection-test contract.
- Do not change structured read/write capability declarations.
