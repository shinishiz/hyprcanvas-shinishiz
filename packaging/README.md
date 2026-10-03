# hyprcanvas-shinishiz Gold packaging status

Target project: `hyprcanvas-shinishiz`

Gold Release: `gold-v0.1.0`

Release URL: <https://github.com/shinishiz/hyprcanvas-shinishiz/releases/tag/gold-v0.1.0>

Canonical source URL:
<https://github.com/shinishiz/hyprcanvas-shinishiz/releases/download/gold-v0.1.0/hyprcanvas-shinishiz-gold-v0.1.0.tar.gz>

SHA256:
`a257e94fa56b69610e9e02a72014a81e00ed9b9b906189355d39a6eb510c2d3a`

Public repository: <https://github.com/shinishiz/hyprcanvas-shinishiz>

The current Gold integration is installed from a checkout with:

```bash
uv tool install .
./scripts/install-user
```

The user installer versions the runtime glue under `scripts/`, installs the
portable systemd user unit, and leaves Hyprland configuration merging explicit
via `examples/hyprland-canvas.lua`.

`arch/PKGBUILD.legacy` predates the current Gold chain. It still references the older
`zyrophix/hyprland-canvas` upstream/tag packaging source and must not be
treated as the current `hyprcanvas-shinishiz` Gold package recipe. The public repository and immutable `gold-v0.1.0` suite tag are published.
The tag remains the Gold source snapshot while post-release `main` carries
administrative/documentation synchronization.

The companion `hypr-canvas` source is consolidated under `plugin/`, with its
original history and MIT license preserved. The user installer can build and
install that integrated source explicitly with `--with-plugin`, while the
default installer remains plugin-free. The Gold package template builds this
integrated source directly.

## Gold package model

The Gold package consumes **one immutable source archive** for the
`hyprcanvas-shinishiz` suite. That archive contains both the Python
daemon/integration and the companion plugin source, so the package does not
need a second repository or submodule.

Validated package metadata:

- candidate `pkgname`: `hyprcanvas-shinishiz`
- suite `pkgver`: `0.1.0`
- suite tag: `gold-v0.1.0`
- Python component version: `1.5.0`
- companion plugin version: `0.1`
- project URL: <https://github.com/shinishiz/hyprcanvas-shinishiz>
- source URL: <https://github.com/shinishiz/hyprcanvas-shinishiz/releases/download/gold-v0.1.0/hyprcanvas-shinishiz-gold-v0.1.0.tar.gz>
- source SHA256: `a257e94fa56b69610e9e02a72014a81e00ed9b9b906189355d39a6eb510c2d3a`
- source directory: `hyprcanvas-shinishiz-gold-v0.1.0`

The Gold package build is expected to build the Python package/daemon and the
plugin from `plugin/`. The packaged/installable payload should include the
Python CLI entry points, five Gold wrappers, the portable user systemd unit and
integration example, the ABI-matched plugin `.so`, documentation, root
`LICENSE`, `plugin/LICENSE`, `CREDITS.md`, and `THIRD_PARTY.md`.

The legacy recipe is preserved byte-for-byte as `arch/PKGBUILD.legacy`.
`arch/PKGBUILD.in` is the reusable Gold template and intentionally retains
`@SOURCE_URL@`, `@SOURCE_SHA256@`, and `@SOURCE_DIR@` for future immutable
release evidence. The exact rendered recipe published for `gold-v0.1.0` is
also tracked as `arch/PKGBUILD`; it is byte-identical to the validated GitHub
Release asset. Arch `x86_64`, runtime dependencies, and build dependencies
have been validated against the official Arch repositories. `SKIP` is not
part of the Gold recipe.

## User-local versus system package paths

The checkout installer remains user-local: wrappers go to `~/.local/bin`, its
unit goes to `~/.config/systemd/user`, and an optional plugin goes under
`$XDG_DATA_HOME/hyprcanvas-shinishiz/plugins/`.

The system package model instead stages:

- Python entry points and the five Gold wrappers in `/usr/bin`;
- `packaging/systemd/hypr-canvasd.service` in `/usr/lib/systemd/user`;
- the native plugin in `/usr/lib/hyprcanvas-shinishiz/plugins/hypr-canvas.so`;
- documentation in `/usr/share/doc/hyprcanvas-shinishiz`;
- both MIT licenses, with distinct filenames, in
  `/usr/share/licenses/hyprcanvas-shinishiz`.

The Lua example preserves user-local precedence and only selects the system
plugin when the user-local artifact is absent. Missing both remains tolerated.

Because `hypr-canvas.so` is a native, ABI-sensitive binary, the Gold package
cannot use `arch=('any')`. The initial validated package architecture is
`x86_64`, and the Gold package pins the Hyprland ABI target to
`hyprland=0.56.2`. The validated runtime dependencies are `python>=3.12`,
`python-yaml`, `jq`, `util-linux` (provider of `flock`), and `libnotify`
(provider of `notify-send`) in addition to Hyprland. The package-specific
build dependencies are `python-build`, `python-hatchling`,
`python-installer`, `pixman`, and `libdrm`; the Arch `base-devel`
contract supplies the compiler, make, pkgconf, and fakeroot tooling.

Hyprland 0.56.2 is shipped with two observed PointerManager header layouts
across the validated Fedora Gold and Arch environments. The plugin source
prefers `src/managers/PointerManager.hpp` when present and falls back to
`src/pointer/PointerManager.hpp`, without changing Canvas behavior. The plugin
Makefile also preserves caller `CPPFLAGS`, `CXXFLAGS`, and `LDFLAGS` so
distro hardening flags, including Arch FULL RELRO flags, reach the final link.

`canvasd` and `canvas-ctl` are also installed by the historical Python package,
while Gold adds `hypr-canvasd` and `hypr-canvas-ctl`. That creates a potential
file/package collision with an installed legacy `hyprland-canvas` package.
`provides`, `conflicts`, and `replaces` are therefore intentionally omitted
until the actual Arch legacy-package relationship is verified; no aggressive
replacement policy is assumed in this stage.

## Validation status

Native Arch validation passed on `x86_64` against Hyprland `0.56.2` using the
official Arch environment: `makepkg` passed, `namcap` findings were acceptable
for the pre-publication template, FULL RELRO/BIND_NOW were confirmed, and a
clean package install/uninstall passed. The public Git repository is live, and
the targeted history privacy rewrite was completed before publication while
preserving project trees and third-party provenance.

The rendered Gold `PKGBUILD` is published as a GitHub Release asset and is
tracked on `main`. No AUR publication is claimed, no binary `.pkg.tar.zst` is
part of the Gold Release, and no generic plugin `.so` is part of the Release.
