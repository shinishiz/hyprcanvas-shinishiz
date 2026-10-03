# Gold packaging status

The current Gold integration is installed from a checkout with:

```bash
uv tool install .
./scripts/install-user
```

The user installer versions the runtime glue under `scripts/`, installs the
portable systemd user unit, and leaves Hyprland configuration merging explicit
via `examples/hyprland-canvas.lua`.

`arch/PKGBUILD` predates the current Gold chain. It still references the older
upstream/tag packaging source and must not be treated as a reproducible Gold
package until the final repository destination and release tag/version are
chosen. Updating that source prematurely would point the package at content
that does not contain the local Gold commits.

The companion `hypr-canvas` plugin is also still maintained in its separate
repository. A self-contained public package therefore remains blocked on the
Gold repository/tag strategy even though the local checkout install path is
reproducible.
