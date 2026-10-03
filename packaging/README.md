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
