# hyprcanvas-shinishiz Gold packaging status

Target project: `hyprcanvas-shinishiz`

Initial Gold suite tag target: `gold-v0.1.0`

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
treated as the current `hyprcanvas-shinishiz` Gold package recipe. The public
repository now exists; the `gold-v0.1.0` suite tag is created separately after
the tag-ready source freeze.

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
- source URL: **rendered only after the immutable release source is published**
- source SHA256: **rendered only after the immutable release source is verified**
- source directory: **rendered from the verified immutable release archive**

The Gold package build is expected to build the Python package/daemon and the
plugin from `plugin/`. The packaged/installable payload should include the
Python CLI entry points, five Gold wrappers, the portable user systemd unit and
integration example, the ABI-matched plugin `.so`, documentation, root
`LICENSE`, `plugin/LICENSE`, `CREDITS.md`, and `THIRD_PARTY.md`.

The legacy recipe is preserved byte-for-byte as `arch/PKGBUILD.legacy`.
`arch/PKGBUILD.in` is the Gold template. Its project URL is now fixed to the
public repository. It intentionally retains `@SOURCE_URL@`,
`@SOURCE_SHA256@`, and `@SOURCE_DIR@` until Stage 8 can render them from
immutable published asset evidence. Arch `x86_64`, runtime dependencies, and
build dependencies have been validated against the official Arch repositories.
It must not be published as a final PKGBUILD until those source placeholders
have been resolved from real evidence; `SKIP` is not part of the Gold template.

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

The package itself is not published yet. `release/metadata.toml` is now
`tag-ready`, while `PKGBUILD.in` remains intentionally templated until Stage 8
provides verified immutable `SOURCE_URL`, `SOURCE_SHA256`, and `SOURCE_DIR`
values. No AUR publication is claimed.
