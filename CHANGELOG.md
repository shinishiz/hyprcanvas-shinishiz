# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.5.0] - 2026-09-27

### Added

- **Auto-float on window open**: New tiled windows opened while Canvas is active automatically become floating and join the Canvas
- **Socket2 event listener**: Real-time window creation/close events via Hyprland's `.socket2.sock`
- **Sensible spawn geometry**: New windows use median geometry from original tiled snapshot
- **Canvas state persistence**: State persisted in `toggle-state.json` + local cache files
- **Spawned window tracking**: Windows spawned during Canvas ON are tracked and restored on OFF
- **Hyprland 0.56.2 compatibility**: Updated for API changes in 0.56.2
- **Safer address normalization**: Robust window address handling between socket2 events and j/clients
- **Workspace-scoped Canvas state**: Per-workspace Canvas state tracking

### Changed

- **Canvas cycle**: `SUPER+SPACE` now cycles `Dwindle → Canvas → Scrolling → Dwindle` (was `Dwindle ↔ Scrolling`)
- **Conditional navigation**: `SUPER+SHIFT+Arrows` now context-aware (Canvas: nav-*, OFF: layout actions)
- **SUPER+SHIFT+V**: Toggle single window floating/tiled
- **SUPER+SHIFT+G**: Invert pan direction
- **SUPER+SHIFT+C removed**: Replaced by `SUPER+SPACE` cycle

### Fixed

- **Address normalization**: Proper handling of `0x` prefix differences between socket2 events and `j/clients`
- **Window geometry preservation**: New windows use median size from original tiled snapshot
- **Canvas state persistence**: State survives daemon restarts within session
- **Race condition fixes**: Lock files prevent concurrent transition conflicts

### Removed

- `SUPER+SHIFT+C` (canvas-toggle): Replaced by `SUPER+SPACE` cycle

### Testing

- 247 tests passing
- 80.17% code coverage
- Ruff linting clean
- Mypy type checking clean

## [1.4.2] — 2026-09-26

### Fixed

- Arch PKGBUILD now includes the post-install message and installs the wheel under `/usr`.

## [1.4.1] — 2026-09-26

### Added

- Arch Linux PKGBUILD for installing `hyprland-canvas` with `makepkg`.

## [1.4.0] — 2026-09-25

### Added

- Arch Linux PKGBUILD for installing `hyprland-canvas` with `makepkg`.

## [1.4.0] — 2026-09-25

### Added

- Arch Linux PKGBUILD for installing `hyprland-canvas` with `makepkg`.

## [1.4.0] — 2026-09-25

### Added

- Arch Linux PKGBUILD for installing `hyprland-canvas` with `makepkg`.

## [1.5.0] - 2026-09-27

### Added

- **Auto-float on window open**: New tiled windows opened while Canvas is active automatically become floating and join the Canvas
- **Socket2 event listener**: Real-time window creation/close events via Hyprland's `.socket2.sock`
- **Sensible spawn geometry**: New windows use median geometry from original tiled snapshot
- **Canvas state persistence**: State persisted in `toggle-state.json` + local cache files
- **Spawned window tracking**: Windows spawned during Canvas ON are tracked and restored on OFF
- **Hyprland 0.56.2 compatibility**: Updated for API changes in 0.56.2
- **Safer address normalization**: Robust window address handling between socket2 events and j/clients
- **Workspace-scoped Canvas state**: Per-workspace Canvas state tracking

### Changed

- **Canvas cycle**: `SUPER+SPACE` now cycles `Dwindle → Canvas → Scrolling → Dwindle` (was `Dwindle ↔ Scrolling`)
- **Conditional navigation**: `SUPER+SHIFT+Arrows` now context-aware (Canvas: nav-*, OFF: layout actions)
- **SUPER+SHIFT+V**: Toggle single window floating/tiled
- **SUPER+SHIFT+G**: Invert pan direction
- **SUPER+SHIFT+C removed**: Replaced by `SUPER+SPACE` cycle

### Fixed

- **Address normalization**: Proper handling of `0x` prefix differences between socket2 events and `j/clients`
- **Window geometry preservation**: New windows use median size from original tiled snapshot
- **Canvas state persistence**: State survives daemon restarts within session
- **Race condition fixes**: Lock files prevent concurrent transition conflicts

### Removed

- `SUPER+SHIFT+C` (canvas-toggle): Replaced by `SUPER+SPACE` cycle

### Testing

- 247 tests passing
- 80.17% code coverage
- Ruff linting clean
- Mypy type checking clean

## [1.4.2] — 2026-09-26

### Fixed

- Arch PKGBUILD now includes the post-install message and installs the wheel under `/usr`.

## [1.4.1] — 2026-09-26

### Added

- Arch Linux PKGBUILD for installing `hyprland-canvas` with `makepkg`.

## [1.4.0] — 2026-09-25

### Added

- Arch Linux PKGBUILD for installing `hyprland-canvas` with `makepkg`.

## [1.4.0] — 2026-09-25

### Added

- Arch Linux PKGBUILD for installing `hyprland-canvas` with `makepkg`.

## [1.0.0] - 2026-09-27

### Added

- **Auto-float on window open**: New tiled windows opened while Canvas is active automatically become floating and join the Canvas
- **Socket2 event listener**: Real-time window creation/close events via Hyprland's `.socket2.sock`
- **Sensible spawn geometry**: New windows use median geometry from original tiled snapshot
- **Canvas state persistence**: State persisted in `toggle-state.json` + local cache files
- **Spawned window tracking**: Windows spawned during Canvas ON are tracked and restored on OFF
- **Hyprland 0.56.2 compatibility**: Updated for API changes in 0.56.2
- **Safer address normalization**: Robust window address handling between socket2 events and j/clients
- **Workspace-scoped Canvas state**: Per-workspace Canvas state tracking

### Changed

- **Canvas cycle**: `SUPER+SPACE` now cycles `Dwindle → Canvas → Scrolling → Dwindle` (was `Dwindle ↔ Scrolling`)
- **Conditional navigation**: `SUPER+SHIFT+Arrows` now context-aware (Canvas: nav-*, OFF: layout actions)
- **SUPER+SHIFT+V**: Toggle single window floating/tiled
- **SUPER+SHIFT+G**: Invert pan direction
- **SUPER+SHIFT+C removed**: Replaced by `SUPER+SPACE` cycle

### Fixed

- **Address normalization**: Proper handling of `0x` prefix differences between socket2 events and `j/clients`
- **Window geometry preservation**: New windows use median size from original tiled snapshot
- **Canvas state persistence**: State survives daemon restarts within session
- **Race condition fixes**: Lock files prevent concurrent transition conflicts

### Removed

- `SUPER+SHIFT+C` (canvas-toggle): Replaced by `SUPER+SPACE` cycle

### Testing

- 247 tests passing
- 80.17% code coverage
- Ruff linting clean
- Mypy type checking clean

## [0.1.0] - 2026-08-XX (upstream)

Initial release by zyrophix.
