# hyprcanvas-shinishiz Gold packaging status

Target project: `hyprcanvas-shinishiz`

Planned initial suite tag: `gold-v0.1.0` (not released)

The current Gold integration is installed from a checkout with:

```bash
uv tool install .
./scripts/install-user
```

The user installer versions the runtime glue under `scripts/`, installs the
portable systemd user unit, and leaves Hyprland configuration merging explicit
via `examples/hyprland-canvas.lua`.

`arch/PKGBUILD` predates the current Gold chain. It still references the older
`zyrophix/hyprland-canvas` upstream/tag packaging source and must not be
treated as a reproducible `hyprcanvas-shinishiz` package yet. The public
repository destination does not exist in this consolidation stage, and the
planned `gold-v0.1.0` suite tag has not been created.

The companion `hypr-canvas` source is now consolidated under `plugin/`, with
its original history and MIT license preserved. The user installer can build
and install that integrated source explicitly with `--with-plugin`, while the
default installer remains plugin-free. Updating the PKGBUILD to build and
package that component belongs to the later packaging stage; the current
PKGBUILD remains intentionally pre-Gold.

## Future Gold package model

The future Gold package should consume **one immutable source archive** created
from the `hyprcanvas-shinishiz` release tag. That archive will contain both the
Python daemon/integration and the companion plugin source, so the package does
not need a second repository or submodule.

Planned package metadata:

- candidate `pkgname`: `hyprcanvas-shinishiz`
- suite `pkgver`: `0.1.0`
- suite tag: `gold-v0.1.0`
- Python component version: `1.5.0`
- companion plugin version: `0.1`
- source URL: **to be filled after remote/tag publication**
- source SHA256: **to be filled after remote/tag publication**

The Gold package build is expected to build the Python package/daemon and the
plugin from `plugin/`. The packaged/installable payload should include the
Python CLI entry points, five Gold wrappers, the portable user systemd unit and
integration example, the ABI-matched plugin `.so`, documentation, root
`LICENSE`, `plugin/LICENSE`, `CREDITS.md`, and `THIRD_PARTY.md`.

`packaging/arch/PKGBUILD` remains the legacy/pre-Gold recipe in this stage. It
must not be repointed to a nonexistent repository, and a final Gold source URL
or checksum must not be invented before publication/freeze.
