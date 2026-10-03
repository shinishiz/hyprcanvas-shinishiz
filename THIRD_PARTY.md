# Third-party and historical source notices

This file records the principal historical codebases incorporated into
`hyprcanvas-shinishiz`. Their original license files remain authoritative and
are preserved in the source tree.

## zyrophix/hyprland-canvas

- **Role:** original daemon and foundational Canvas implementation
- **License:** MIT
- **Copyright:** Copyright (c) 2026 zyrophix
- **Historical source:** https://github.com/zyrophix/hyprland-canvas
- **License location in this tree:** `LICENSE`

The daemon history forms the base history of this monorepo. Subsequent Gold
integration work is maintained as part of `hyprcanvas-shinishiz` without
removing or reassigning the original copyright.

## aaronsb/hypr-canvas

- **Role:** original companion plugin codebase used as the foundation for
  `plugin/`
- **License:** MIT
- **Copyright:** Copyright (c) 2026 Aaron Bockelie
- **Historical source:** https://github.com/aaronsb/hypr-canvas
- **License location in this tree:** `plugin/LICENSE`

`plugin/` contains an integrated and adapted version derived from that
historical base. The upstream codebase was not compatible out of the box with
the current Gold setup; the integrated version includes additional
compatibility and daemon/Hyprland integration work for the Gold environment.

## Current project maintenance

**shinishiz** maintains `hyprcanvas-shinishiz` and the Gold integration,
including compatibility/integration work, packaging, testing and validation,
release engineering, and ongoing project maintenance. This maintenance role
does not replace the original authorship or copyrights listed above.
