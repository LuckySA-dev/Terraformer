# Manual USB Console UI Polish Design

Date: 2026-07-20
Status: Approved

## Scope

Fix the clipped, undersized privacy note at the bottom of the Manual USB
Console and make its pre-connection surface match the surrounding white modal.
Keep the active terminal dark, and preserve the component structure, safety
warning, authorization gate, and responsive form.

Credential profiles, Add Device, SSH, discovery, serial behavior, and hardware
validation are outside this slice.

## Design

Make targeted CSS-only adjustments:

- Select the USB pre-connection state through its existing
  `.usb-console-settings` descendant and give that terminal card the standard
  white surface and border colors.
- Use dark standard text for the authorization label in that state.
- In that pre-connection state, remove the privacy note's default paragraph
  margin, add inset spacing, use the existing small UI text size instead of
  7px, and set an explicit line height so glyphs are not clipped.
- Stop applying the light surface after the settings disappear, leaving the
  connected terminal presentation dark.

No React markup, terminal lifecycle, transport, or backend code changes.

## Verification

Add one focused regression check for the note's readable inset styling, then
run the USB console component tests, frontend lint, type check, and production
build. Automated verification must not access serial or network hardware.

## Acceptance criteria

- The pre-connection card uses the standard white modal surface while the
  connected terminal remains dark.
- The complete privacy note is readable and visibly inset from the card.
- The note wraps without clipping at narrow widths.
- Existing USB authorization, settings, and open-session behavior are unchanged.
- No SSH, credential, discovery, API, or device-driver behavior changes.
