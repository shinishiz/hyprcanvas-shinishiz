# gold-v0.1.0 — DRAFT / UNRELEASED

**Status:** DRAFT — UNRELEASED

**Planned tag:** `gold-v0.1.0`

This is the draft for the first planned `hyprcanvas-shinishiz` suite release.
It does not represent an existing tag or public release.

## Included components

- `hyprland-canvas` daemon/integration component `1.5.0`;
- adapted `hypr-canvas` companion plugin `0.1` under `plugin/`;
- Gold wrappers, systemd user unit, Lua integration example, and local
  packaging/release tooling in one independent monorepo.

The companion plugin remains source-first and ABI-sensitive. The current Gold
compatibility target is Hyprland `0.56.2`, commit
`efb50993780079460b0cbed1363e2166a2de1d9f`; no universal compatibility with
other Hyprland versions is claimed.

The initial Arch package target validated for this draft is `x86_64`, pinned
to the Hyprland `0.56.2` ABI. Hyprland 0.56.2 has been observed with
`PointerManager.hpp` under both `src/managers/` (Fedora Gold) and
`src/pointer/` (Arch), so the companion plugin resolves those two known
header layouts at compile time. The package remains unpublished; its public
project/source URL and immutable public-source checksum are still pending the
future repository/tag publication stages.

## Installation model

`./scripts/install-user` installs the user integration without building the
plugin. `./scripts/install-user --with-plugin` explicitly builds the integrated
`plugin/` source and installs the ABI-sensitive artifact under
`$XDG_DATA_HOME/hyprcanvas-shinishiz/plugins/hypr-canvas.so`, falling back to
`~/.local/share/hyprcanvas-shinishiz/plugins/hypr-canvas.so`.

The installer does not load the plugin or restart Hyprland/systemd services.

## Gold integration highlights

- socket2 EventListener reconnect recovery;
- cross-workspace Canvas ownership reconciliation;
- visual-viewport-aware window spawn placement;
- pointer-motion transformation under zoom;
- consolidated daemon/plugin source and provenance.

## Known limitation

EventListener transport reconnect does not replay events emitted while the
listener is disconnected. A later reconciliation can repair state, but the
reconnect itself does not recover missed lifecycle events.

## Provenance

The daemon history derives from `zyrophix/hyprland-canvas`. The companion
plugin history derives from Aaron Bockelie's `aaronsb/hypr-canvas` codebase and
was later adapted for the Gold integration. See `CREDITS.md`, `THIRD_PARTY.md`,
`LICENSE`, and `plugin/LICENSE` for attribution and licensing details.
