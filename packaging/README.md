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

`arch/PKGBUILD.legacy` predates the current Gold chain. It still references the older
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

The legacy recipe is preserved byte-for-byte as `arch/PKGBUILD.legacy`.
`arch/PKGBUILD.in` is the Gold template. It is intentionally non-final and
contains explicit `@...@` placeholders only for publication-time values such
as the public project/source URL, source checksum, and archive root. Arch
`x86_64`, runtime dependencies, and build dependencies have been validated
against the official Arch repositories. It must not be published as a final
PKGBUILD until the remaining public-source placeholders have been resolved from
real evidence; `SKIP` is not part of the Gold template.

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

Stage 5B validates the Gold template and package layout locally from a release
candidate without a remote. Stage 5C validates the Arch package model using an
official isolated Arch environment; the initial target is `x86_64` with
Hyprland 0.56.2. The public source URL and public source checksum remain unset
until the repository/tag exists, and the package has not been published. The
release itself remains DRAFT / UNRELEASED and `release/metadata.toml` remains
`release-preparation`.

The historical Git author records that contain the local machine identity are
not rewritten in Stage 5B. The privacy decision remains pending before public
repository/tag publication because any history rewrite would change commit
identities and invalidate frozen source checksums.
