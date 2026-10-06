# Credits and project provenance

## hyprcanvas-shinishiz

`hyprcanvas-shinishiz` is an independent Hyprland Canvas suite maintained by
**shinishiz**. The project consolidates the daemon/integration history and the
companion plugin into one source tree while preserving the provenance and
licenses of both historical bases.

### shinishiz

Maintainer: **shinishiz**

Contact:

- GitHub: `shinishiz`
- Email: `shinishiz@outlook.com`
- Discord: `shinishi`

Responsibilities:

- project maintenance and Gold integration;
- Hyprland compatibility and integration work for the validated Gold setup;
- daemon, companion plugin, and Hyprland integration;
- packaging and user integration work;
- testing and validation;
- release engineering.

This work does not replace or reassign the original authorship or copyrights
of the daemon and plugin codebases described below.

## Daemon provenance — zyrophix

The daemon history and foundational Canvas implementation derive from
`zyrophix/hyprland-canvas`, originally authored by **zyrophix** and distributed
under the MIT License.

The daemon history forms the historical base of this monorepo. The root
`LICENSE` preserves the original zyrophix copyright and MIT terms.

Historical source: https://github.com/zyrophix/hyprland-canvas

## Companion plugin provenance — Aaron Bockelie

The source under `plugin/` derives from the `aaronsb/hypr-canvas` companion
plugin codebase originally authored by **Aaron Bockelie** and distributed
under the MIT License.

That original codebase was used as the historical foundation for the companion
plugin. It was not compatible out of the box with the current Gold setup. The
integrated version in `plugin/` contains later compatibility and integration
work performed for the Gold environment while retaining the original plugin
history and `plugin/LICENSE`.

Historical source: https://github.com/aaronsb/hypr-canvas

## Relationship of the components

The Python daemon retains its historical component identity (`hyprland-canvas`
1.5.0), and the companion plugin retains its technical `hypr-canvas` identity
and internal version 0.1. `hyprcanvas-shinishiz` is the suite/project identity
that brings those components and the Gold integration together.

The initial suite tag is `gold-v0.1.0`. It was created and published as the
Gold v0.1.0 suite release on October 3, 2026.
