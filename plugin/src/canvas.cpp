#include "canvas.hpp"

#include <hyprland/src/Compositor.hpp>
#include <hyprland/src/config/ConfigValue.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/state/ViewState.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/state/ViewHitTester.hpp>
#include <hyprland/src/desktop/view/Popup.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/layout/LayoutManager.hpp>
#include <hyprland/src/managers/KeybindManager.hpp>
#if __has_include(<hyprland/src/managers/PointerManager.hpp>)
#include <hyprland/src/managers/PointerManager.hpp>
#elif __has_include(<hyprland/src/pointer/PointerManager.hpp>)
#include <hyprland/src/pointer/PointerManager.hpp>
#else
#error "Unsupported Hyprland PointerManager header layout"
#endif
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/managers/fullscreen/FullscreenController.hpp>
#include <hyprland/src/pointer/PointerController.hpp>
#include <hyprland/src/protocols/XDGShell.hpp>
#include <hyprland/src/protocols/core/Subcompositor.hpp>
#include <hyprland/src/render/ElementRenderer.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/gl/GLElementRenderer.hpp>
#include <hyprland/src/render/pass/RendererHintsPassElement.hpp>
#include <hyprland/src/state/MonitorState.hpp>
#include <hyprland/src/state/WorkspaceState.hpp>
#include <hyprland/src/xwayland/XSurface.hpp>

#include <algorithm>
#include <any>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdarg>
#include <optional>
#include <ranges>
#include <sstream>

static void logf(const char* fmt, ...) {
    FILE* f = fopen("/tmp/hypr-canvas.log", "a");
    if (!f)
        return;
    va_list args;
    va_start(args, fmt);
    vfprintf(f, fmt, args);
    va_end(args);
    fclose(f);
}

static constexpr const char* CANVAS_BUILD_ID = "CANVAS_CAMERA_CULLING_FIX_2026_10_01";

static void scheduleFrame() {
    auto mon = Desktop::focusState()->monitor();
    if (mon)
        mon->scheduleFrame();
}

static WORKSPACEID activeWorkspaceID() {
    auto mon = Desktop::focusState()->monitor();
    if (!mon || mon->m_activeSpecialWorkspace || !mon->m_activeWorkspace)
        return WORKSPACE_INVALID;
    return mon->m_activeWorkspace->m_id;
}

// --- Forward typedefs ---
using steady_tp    = std::chrono::steady_clock::time_point;

static thread_local int         g_worldInputDepth      = 0;
static thread_local WORKSPACEID g_worldInputWorkspace  = WORKSPACE_INVALID;
static thread_local Vector2D    g_worldInputMonitorPos = {};

// onMouseWheel() does its global/input-capture/keybind work in screen-space, then
// obtains one cursor position for window-local axis delivery. These flags let
// only that post-keybind coordinate become Canvas world-space.
static thread_local int         g_wheelInputDepth        = 0;
static thread_local bool        g_wheelConvertNextCoords = false;
static thread_local bool        g_wheelWorldCoordsValid  = false;
static thread_local WORKSPACEID g_wheelInputWorkspace    = WORKSPACE_INVALID;
static thread_local Vector2D    g_wheelInputMonitorPos   = {};
static thread_local Vector2D    g_wheelWorldCoords       = {};

// mouseMoveUnified itself stays entirely in screen-space. We only remember
// the physical coordinate and the Canvas window selected by its hit-test so
// pointer enter/motion can receive correct surface-local world coordinates.
static thread_local int         g_mouseMoveInputDepth  = 0;
static thread_local Vector2D    g_mouseMoveScreenPos   = {};
static thread_local PHLWINDOW   g_mouseMoveCanvasWindow;

// renderAllClientsForWorkspace owns the native workspace transform used by
// monitor/workspace rendering. Keep that transform as context, then add the
// Canvas camera only around individual world-space windows. Layer-shell,
// wallpaper, pinned windows, special workspaces and overlays never enter that
// narrower scope.
static thread_local int         g_workspaceRenderDepth     = 0;
static thread_local WORKSPACEID g_workspaceRenderWorkspace = WORKSPACE_INVALID;
static thread_local Vector2D    g_workspaceRenderTranslate = {};
static thread_local float       g_workspaceRenderScale     = 1.f;
static thread_local int         g_canvasSurfaceDrawDepth   = 0;

class CScopedCanvasWorldInput {
  public:
    CScopedCanvasWorldInput(WORKSPACEID workspace, const Vector2D& monitorPos)
        : m_prevDepth(g_worldInputDepth), m_prevWorkspace(g_worldInputWorkspace), m_prevMonitorPos(g_worldInputMonitorPos) {
        g_worldInputDepth      = m_prevDepth + 1;
        g_worldInputWorkspace  = workspace;
        g_worldInputMonitorPos = monitorPos;
    }

    ~CScopedCanvasWorldInput() {
        g_worldInputDepth      = m_prevDepth;
        g_worldInputWorkspace  = m_prevWorkspace;
        g_worldInputMonitorPos = m_prevMonitorPos;
    }

  private:
    int         m_prevDepth;
    WORKSPACEID m_prevWorkspace;
    Vector2D    m_prevMonitorPos;
};

static const SCanvasViewport* transformedViewport(WORKSPACEID workspace) {
    if (!g_pCanvas)
        return nullptr;
    const auto* viewport = g_pCanvas->viewportForWorkspace(workspace);
    return viewport && viewport->enabled && g_pCanvas->isTransformed(*viewport) ? viewport : nullptr;
}

static Vector2D monitorPositionForWindow(const PHLWINDOW& window) {
    if (window) {
        if (const auto mon = window->m_monitor.lock())
            return mon->m_position;
    }
    return {};
}

static Vector2D inputPositionForWindow(const PHLWINDOW& window, const Vector2D& pos) {
    if (!window || g_worldInputDepth > 0)
        return pos;
    if (g_wheelWorldCoordsValid && window->workspaceID() == g_wheelInputWorkspace && pos == g_wheelWorldCoords)
        return pos;
    const auto* viewport = transformedViewport(window->workspaceID());
    if (!viewport)
        return pos;
    return g_pCanvas->screenToCanvas(*viewport, pos, monitorPositionForWindow(window));
}

// --- Canvas-specific window hit testing ---

typedef PHLWINDOW (*windowAtFn)(const Desktop::CViewHitTester*, const Vector2D&, uint16_t, PHLWINDOW);

static PHLWINDOW canvasWindowAt(WORKSPACEID workspace, const Vector2D& worldPos, uint16_t properties, PHLWINDOW ignoreWindow) {
    using namespace Desktop::View;

    static auto PRESIZEONBORDER      = CConfigValue<Config::INTEGER>("general:resize_on_border");
    static auto PBORDERSIZE          = CConfigValue<Config::INTEGER>("general:border_size");
    static auto PBORDERGRABEXTEND    = CConfigValue<Config::INTEGER>("general:extend_border_grab_area");
    static auto PMODALPARENTBLOCKING = CConfigValue<Config::INTEGER>("general:modal_parent_blocking");
    static auto PFOLLOWMOUSESHRINK   = CConfigValue<Config::INTEGER>("input:follow_mouse_shrink");

    const auto BORDER_GRAB_AREA      = *PRESIZEONBORDER ? *PBORDERSIZE + *PBORDERGRABEXTEND : 0;
    const bool ONLY_PRIORITY         = properties & FOCUS_PRIORITY;
    const bool DO_FOLLOW_MOUSE_CHECK = properties & FOLLOW_MOUSE_CHECK;
    const auto HITBOX_SHRINK         = DO_FOLLOW_MOUSE_CHECK ? *PFOLLOWMOUSESHRINK : 0;
    const auto LASTFOCUSED           = Desktop::focusState()->window();
    const auto& WINDOWS              = Desktop::windowState()->windows();

    auto isShadowedByModal = [&](PHLWINDOW w) {
        return *PMODALPARENTBLOCKING && w->m_xdgSurface && w->m_xdgSurface->m_toplevel && w->m_xdgSurface->m_toplevel->anyChildModal();
    };

    auto findPinned = [&]() -> PHLWINDOW {
        for (const auto& w : WINDOWS | std::views::reverse) {
            if (!w || w->workspaceID() != workspace || !w->m_isFloating || !w->m_pinned || !w->m_isMapped || !w->acceptsInput() ||
                w->m_X11ShouldntFocus || w->m_ruleApplicator->noFocus().valueOrDefault() || w == ignoreWindow || isShadowedByModal(w))
                continue;
            if (ONLY_PRIORITY && !w->priorityFocus())
                continue;

            CBox box = w->getWindowBoxUnified(properties).copy().expand(!w->isX11OverrideRedirect() ? BORDER_GRAB_AREA : 0);
            if (HITBOX_SHRINK > 0 && w != LASTFOCUSED)
                box = box.copy().expand(-HITBOX_SHRINK);
            if (box.containsPoint(worldPos))
                return w;
            if (!w->m_isX11 && w->hasPopupAt(worldPos))
                return w;
        }
        return nullptr;
    };

    auto findFloating = [&](bool aboveFullscreen) -> PHLWINDOW {
        for (const auto& w : WINDOWS | std::views::reverse) {
            if (!w || !w->m_workspace || w->workspaceID() != workspace || !w->m_isFloating || w->m_pinned || !w->m_isMapped ||
                !w->m_workspace->isVisible() || !w->acceptsInput() || w->m_ruleApplicator->noFocus().valueOrDefault() ||
                w == ignoreWindow || (aboveFullscreen && !w->isAllowedOverFullscreen()) || isShadowedByModal(w))
                continue;
            if (ONLY_PRIORITY && !w->priorityFocus())
                continue;
            if (w->m_X11ShouldntFocus && !w->isX11OverrideRedirect())
                continue;

            CBox box = w->getWindowBoxUnified(properties).copy().expand(!w->isX11OverrideRedirect() ? BORDER_GRAB_AREA : 0);
            if (HITBOX_SHRINK > 0 && w != LASTFOCUSED)
                box = box.copy().expand(-HITBOX_SHRINK);
            if (box.containsPoint(worldPos)) {
                if (w->m_isX11 && w->isX11OverrideRedirect() && !w->m_xwaylandSurface->wantsFocus())
                    return Desktop::focusState()->window();
                return w;
            }
            if (!w->m_isX11 && w->hasPopupAt(worldPos))
                return w;
        }
        return nullptr;
    };

    CScopedCanvasWorldInput scope(workspace, {});
    if (properties & ALLOW_FLOATING) {
        if (auto pinned = findPinned())
            return pinned;
        if (auto floating = findFloating(true))
            return floating;
    }

    if (properties & FLOATING_ONLY)
        return findFloating(false);

    const auto pWorkspace = State::workspaceState()->query().id(workspace).run();
    if (pWorkspace && Fullscreen::controller()->hasFullscreen(pWorkspace) && !(properties & SKIP_FULLSCREEN_PRIORITY) && !ONLY_PRIORITY) {
        const auto fsWindow = Fullscreen::controller()->getFullscreenWindow(pWorkspace);
        if (!fsWindow)
            return nullptr;
        if (!Fullscreen::controller()->isFullscreen(fsWindow, Fullscreen::FSMODE_MAXIMIZED) || fsWindow->getWindowBoxUnified(properties).containsPoint(worldPos))
            return fsWindow;
        return nullptr;
    }

    return findFloating(false);
}

static PHLWINDOW hkWindowAt(const Desktop::CViewHitTester* self, const Vector2D& pos, uint16_t properties, PHLWINDOW ignoreWindow) {
    auto original = (windowAtFn)g_pCanvas->m_windowAtHook->m_original;

    if (g_wheelWorldCoordsValid && g_wheelInputWorkspace != WORKSPACE_INVALID && pos == g_wheelWorldCoords) {
        if (transformedViewport(g_wheelInputWorkspace))
            return canvasWindowAt(g_wheelInputWorkspace, pos, properties, ignoreWindow);
    }

    if (g_worldInputDepth > 0) {
        if (transformedViewport(g_worldInputWorkspace)) {
            if (auto found = canvasWindowAt(g_worldInputWorkspace, pos, properties, ignoreWindow))
                return found;
            return nullptr;
        }
        return original(self, pos, properties, ignoreWindow);
    }

    const auto monitor = State::monitorState()->query().vec(pos).run();
    if (!monitor || monitor->m_activeSpecialWorkspace || !monitor->m_activeWorkspace)
        return original(self, pos, properties, ignoreWindow);

    const auto workspace = monitor->m_activeWorkspace->m_id;
    const auto* viewport = transformedViewport(workspace);
    if (!viewport)
        return original(self, pos, properties, ignoreWindow);

    const auto worldPos = g_pCanvas->screenToCanvas(*viewport, pos, monitor->m_position);
    const auto found = canvasWindowAt(workspace, worldPos, properties, ignoreWindow);
    if (g_mouseMoveInputDepth > 0)
        g_mouseMoveCanvasWindow = found;
    return found;
}

typedef SP<CWLSurfaceResource> (*windowSurfaceAtFn)(const Desktop::CViewHitTester*, const Vector2D&, PHLWINDOW, Vector2D&);
typedef Vector2D (*surfaceLocalAtFn)(const Desktop::CViewHitTester*, const Vector2D&, PHLWINDOW, SP<CWLSurfaceResource>);

static SP<CWLSurfaceResource> hkWindowSurfaceAt(const Desktop::CViewHitTester* self, const Vector2D& pos, PHLWINDOW window, Vector2D& surfaceLocal) {
    auto original = (windowSurfaceAtFn)g_pCanvas->m_windowSurfaceAtHook->m_original;
    const auto converted = inputPositionForWindow(window, pos);
    if (converted == pos)
        return original(self, pos, window, surfaceLocal);
    CScopedCanvasWorldInput scope(window->workspaceID(), monitorPositionForWindow(window));
    return original(self, converted, window, surfaceLocal);
}

static Vector2D hkSurfaceLocalAt(const Desktop::CViewHitTester* self, const Vector2D& pos, PHLWINDOW window, SP<CWLSurfaceResource> surface) {
    auto original = (surfaceLocalAtFn)g_pCanvas->m_surfaceLocalAtHook->m_original;
    const auto converted = inputPositionForWindow(window, pos);
    if (converted == pos)
        return original(self, pos, window, surface);
    CScopedCanvasWorldInput scope(window->workspaceID(), monitorPositionForWindow(window));
    return original(self, converted, window, surface);
}

typedef bool (*checkInputOnDecosFn)(Desktop::View::CWindow*, eInputType, const Vector2D&, std::any);
typedef bool (*hasPopupAtFn)(Desktop::View::CWindow*, const Vector2D&);

static bool hkCheckInputOnDecos(Desktop::View::CWindow* self, eInputType type, const Vector2D& pos, std::any data) {
    auto original = (checkInputOnDecosFn)g_pCanvas->m_checkInputOnDecosHook->m_original;
    const auto window = self->m_self.lock();
    const auto converted = inputPositionForWindow(window, pos);
    if (converted == pos)
        return original(self, type, pos, std::move(data));
    CScopedCanvasWorldInput scope(window->workspaceID(), monitorPositionForWindow(window));
    return original(self, type, converted, std::move(data));
}

static bool hkHasPopupAt(Desktop::View::CWindow* self, const Vector2D& pos) {
    auto original = (hasPopupAtFn)g_pCanvas->m_hasPopupAtHook->m_original;
    const auto window = self->m_self.lock();
    const auto converted = inputPositionForWindow(window, pos);
    if (converted == pos)
        return original(self, pos);
    CScopedCanvasWorldInput scope(window->workspaceID(), monitorPositionForWindow(window));
    return original(self, converted);
}

// getMouseCoordsInternal stays screen-space normally. It becomes world-space only
// inside the narrow drag/border scopes below.
typedef Vector2D (*mouseCoordsFn)(CInputManager*);

static Vector2D hkGetMouseCoordsInternal(CInputManager* self) {
    auto original = (mouseCoordsFn)g_pCanvas->m_mouseCoordsHook->m_original;
    const auto raw = original(self);
    if (g_worldInputDepth <= 0)
        ;
    else {
        const auto* viewport = transformedViewport(g_worldInputWorkspace);
        return viewport ? g_pCanvas->screenToCanvas(*viewport, raw, g_worldInputMonitorPos) : raw;
    }

    if (!g_wheelConvertNextCoords)
        return raw;

    g_wheelConvertNextCoords = false;
    const auto monitor = State::monitorState()->query().vec(raw).run();
    if (!monitor || monitor->m_activeSpecialWorkspace || !monitor->m_activeWorkspace)
        return raw;

    const auto workspace = monitor->m_activeWorkspace->m_id;
    const auto* viewport = transformedViewport(workspace);
    if (!viewport)
        return raw;

    g_wheelInputWorkspace   = workspace;
    g_wheelInputMonitorPos  = monitor->m_position;
    g_wheelWorldCoords      = g_pCanvas->screenToCanvas(*viewport, raw, monitor->m_position);
    g_wheelWorldCoordsValid = true;
    return g_wheelWorldCoords;
}

typedef void (*mouseWheelFn)(CInputManager*, IPointer::SAxisEvent, SP<IPointer>);
typedef bool (*axisEventFn)(CKeybindManager*, const IPointer::SAxisEvent&, SP<IPointer>);

static bool hkOnAxisEvent(CKeybindManager* self, const IPointer::SAxisEvent& event, SP<IPointer> pointer) {
    auto original = (axisEventFn)g_pCanvas->m_axisEventHook->m_original;
    const bool pass = original(self, event, pointer);
    if (g_wheelInputDepth > 0 && pass)
        g_wheelConvertNextCoords = true;
    return pass;
}

static void hkOnMouseWheel(CInputManager* self, IPointer::SAxisEvent event, SP<IPointer> pointer) {
    auto original = (mouseWheelFn)g_pCanvas->m_mouseWheelHook->m_original;

    if (event.axis == WL_POINTER_AXIS_VERTICAL_SCROLL && (g_pInputManager->getModsFromAllKBs() & HL_MODIFIER_META)) {
        const auto cursorScreen = Pointer::mgr()->position();
        const auto monitor = State::monitorState()->query().vec(cursorScreen).run();
        if (monitor && !monitor->m_activeSpecialWorkspace && monitor->m_activeWorkspace) {
            const auto workspace = monitor->m_activeWorkspace->m_id;
            auto* viewport = g_pCanvas->viewportForWorkspace(workspace);
            if (viewport && viewport->enabled) {
                const double scrollDelta = event.deltaDiscrete != 0 ? (double)event.deltaDiscrete : event.delta;
                if (scrollDelta != 0) {
                    const double zoomBefore = viewport->zoom;
                    const double newZoom = scrollDelta < 0
                        ? viewport->zoom * CCanvas::ZOOM_STEP
                        : viewport->zoom / CCanvas::ZOOM_STEP;
                    g_pCanvas->applyZoom(*viewport, newZoom, cursorScreen, monitor->m_position);
                    logf("[hypr-canvas] wheel event canvas=1 ws=%lld monitor=%s zoom_before=%.6f zoom_after=%.6f offset=(%.1f, %.1f)\n",
                         (long long)workspace, monitor->m_name.c_str(), zoomBefore, viewport->zoom, viewport->offset.x, viewport->offset.y);
                    monitor->scheduleFrame();
                    return;
                }
            }
        }
    }

    const int         prevDepth       = g_wheelInputDepth;
    const bool        prevConvert     = g_wheelConvertNextCoords;
    const bool        prevValid       = g_wheelWorldCoordsValid;
    const WORKSPACEID prevWorkspace   = g_wheelInputWorkspace;
    const Vector2D    prevMonitorPos  = g_wheelInputMonitorPos;
    const Vector2D    prevWorldCoords = g_wheelWorldCoords;

    g_wheelInputDepth        = prevDepth + 1;
    g_wheelConvertNextCoords = false;
    g_wheelWorldCoordsValid  = false;
    g_wheelInputWorkspace    = WORKSPACE_INVALID;
    g_wheelInputMonitorPos   = {};
    g_wheelWorldCoords       = {};

    original(self, event, pointer);

    g_wheelInputDepth        = prevDepth;
    g_wheelConvertNextCoords = prevConvert;
    g_wheelWorldCoordsValid  = prevValid;
    g_wheelInputWorkspace    = prevWorkspace;
    g_wheelInputMonitorPos   = prevMonitorPos;
    g_wheelWorldCoords       = prevWorldCoords;
}

typedef void (*pointerWarpFn)(const Pointer::CPointerController*, const Vector2D&, bool);

static void hkPointerWarpTo(const Pointer::CPointerController* self, const Vector2D& pos, bool force) {
    auto original = (pointerWarpFn)g_pCanvas->m_pointerWarpHook->m_original;

    // onMouseWheel mode 3 clamps in the same coordinate space as its local
    // delivery. Once that delivery coordinate is Canvas world-space, convert
    // only the resulting physical pointer warp back to screen-space.
    if (g_wheelInputDepth > 0 && g_wheelWorldCoordsValid && g_wheelInputWorkspace != WORKSPACE_INVALID) {
        if (const auto* viewport = transformedViewport(g_wheelInputWorkspace)) {
            original(self, g_pCanvas->canvasToScreen(*viewport, pos, g_wheelInputMonitorPos), force);
            return;
        }
    }

    original(self, pos, force);
}

typedef void (*mouseMoveUnifiedFn)(CInputManager*, uint32_t, bool, bool, std::optional<Vector2D>);

static void hkMouseMoveUnified(CInputManager* self, uint32_t time, bool refocus, bool mouse, std::optional<Vector2D> overridePos) {
    auto original = (mouseMoveUnifiedFn)g_pCanvas->m_mouseMoveUnifiedHook->m_original;

    const int       prevDepth  = g_mouseMoveInputDepth;
    const Vector2D  prevPos    = g_mouseMoveScreenPos;
    const PHLWINDOW prevWindow = g_mouseMoveCanvasWindow;

    g_mouseMoveInputDepth  = prevDepth + 1;
    g_mouseMoveScreenPos   = overridePos.value_or(Pointer::mgr()->position());
    g_mouseMoveCanvasWindow.reset();

    original(self, time, refocus, mouse, overridePos);

    g_mouseMoveInputDepth  = prevDepth;
    g_mouseMoveScreenPos   = prevPos;
    g_mouseMoveCanvasWindow = prevWindow;
}

static PHLWINDOW ownerWindowForSurface(const SP<CWLSurfaceResource>& surface) {
    if (!surface)
        return nullptr;

    auto top = surface;
    std::vector<SP<CWLSurfaceResource>> visited;
    while (top && top->m_role && top->m_role->role() == SURFACE_ROLE_SUBSURFACE) {
        if (std::ranges::find(visited, top) != visited.end())
            return nullptr;
        visited.emplace_back(top);

        const auto role = sc<CSubsurfaceRole*>(top->m_role.get());
        const auto subsurface = role ? role->m_subsurface.lock() : nullptr;
        if (!subsurface)
            return nullptr;
        top = subsurface->m_parent.lock();
    }

    const auto hlSurface = Desktop::View::CWLSurface::fromResource(top);
    const auto view = hlSurface ? hlSurface->view() : nullptr;
    if (!view)
        return nullptr;

    if (const auto window = Desktop::View::CWindow::fromView(view))
        return window;

    const auto popup = Desktop::View::CPopup::fromView(view);
    if (!popup)
        return nullptr;

    const auto ownerSurface = popup->getT1Owner();
    return ownerSurface ? Desktop::View::CWindow::fromView(ownerSurface->view()) : nullptr;
}

static std::optional<Vector2D> mouseMoveLocalForSurface(const SP<CWLSurfaceResource>& surface) {
    if (g_mouseMoveInputDepth <= 0 || !surface)
        return std::nullopt;

    const auto ownerWindow = ownerWindowForSurface(surface);
    if (!ownerWindow || !transformedViewport(ownerWindow->workspaceID()))
        return std::nullopt;

    // Prefer the window selected by the normal Canvas hit-test. Held-button
    // motion can skip windowAt(), so only then fall back to the focused
    // surface's owner window while staying inside mouseMoveUnified.
    const auto window = g_mouseMoveCanvasWindow ? g_mouseMoveCanvasWindow : ownerWindow;
    if (window != ownerWindow)
        return std::nullopt;

    auto local = Desktop::viewState()->hitTest().surfaceLocalAt(g_mouseMoveScreenPos, window, surface);
    if (window->m_isX11)
        local *= window->m_X11SurfaceScaledBy;
    return local;
}

typedef void (*setPointerFocusFn)(CSeatManager*, SP<CWLSurfaceResource>, const Vector2D&);
typedef void (*sendPointerMotionFn)(CSeatManager*, uint32_t, const Vector2D&);

static void hkSetPointerFocus(CSeatManager* self, SP<CWLSurfaceResource> surface, const Vector2D& local) {
    auto original = (setPointerFocusFn)g_pCanvas->m_setPointerFocusHook->m_original;
    if (const auto corrected = mouseMoveLocalForSurface(surface)) {
        original(self, surface, *corrected);
        return;
    }
    original(self, surface, local);
}

static void hkSendPointerMotion(CSeatManager* self, uint32_t timeMs, const Vector2D& local) {
    auto original = (sendPointerMotionFn)g_pCanvas->m_sendPointerMotionHook->m_original;
    const auto surface = self->m_state.pointerFocus.lock();
    if (const auto corrected = mouseMoveLocalForSurface(surface)) {
        original(self, timeMs, *corrected);
        return;
    }
    original(self, timeMs, local);
}

static bool transformedTarget(const SP<Layout::ITarget>& target, WORKSPACEID& workspace, Vector2D& monitorPos) {
    if (!target || !target->window())
        return false;
    const auto window = target->window();
    workspace = window->workspaceID();
    if (!transformedViewport(workspace))
        return false;
    monitorPos = monitorPositionForWindow(window);
    return true;
}

typedef void (*beginDragFn)(Layout::CLayoutManager*, SP<Layout::ITarget>, eMouseBindMode, std::optional<Layout::eRectCorner>, bool);
typedef void (*moveMouseFn)(Layout::CLayoutManager*, const Vector2D&);
typedef void (*endDragFn)(Layout::CLayoutManager*);

static void hkBeginDragTarget(Layout::CLayoutManager* self, SP<Layout::ITarget> target, eMouseBindMode mode, std::optional<Layout::eRectCorner> edge, bool exclusive) {
    auto original = (beginDragFn)g_pCanvas->m_beginDragHook->m_original;
    WORKSPACEID workspace;
    Vector2D monitorPos;
    if (!transformedTarget(target, workspace, monitorPos)) {
        original(self, target, mode, edge, exclusive);
        return;
    }
    CScopedCanvasWorldInput scope(workspace, monitorPos);
    original(self, target, mode, edge, exclusive);
}

static void hkMoveMouse(Layout::CLayoutManager* self, const Vector2D& mousePos) {
    auto original = (moveMouseFn)g_pCanvas->m_moveMouseHook->m_original;
    const auto target = self->dragController()->target();
    WORKSPACEID workspace;
    Vector2D monitorPos;
    if (!transformedTarget(target, workspace, monitorPos)) {
        original(self, mousePos);
        return;
    }
    const auto* viewport = transformedViewport(workspace);
    const auto worldPos = g_pCanvas->screenToCanvas(*viewport, mousePos, monitorPos);
    CScopedCanvasWorldInput scope(workspace, monitorPos);
    original(self, worldPos);
}

static void hkEndDragTarget(Layout::CLayoutManager* self) {
    auto original = (endDragFn)g_pCanvas->m_endDragHook->m_original;
    const auto target = self->dragController()->target();
    WORKSPACEID workspace;
    Vector2D monitorPos;
    if (!transformedTarget(target, workspace, monitorPos)) {
        original(self);
        return;
    }
    CScopedCanvasWorldInput scope(workspace, monitorPos);
    original(self);
}

typedef void (*cursorBorderFn)(CInputManager*, PHLWINDOW);

static void hkSetCursorIconOnBorder(CInputManager* self, PHLWINDOW window) {
    auto original = (cursorBorderFn)g_pCanvas->m_cursorBorderHook->m_original;
    if (!window || !transformedViewport(window->workspaceID())) {
        original(self, window);
        return;
    }
    CScopedCanvasWorldInput scope(window->workspaceID(), monitorPositionForWindow(window));
    original(self, window);
}

typedef void (*mouseDownNormalFn)(CInputManager*, const IPointer::SButtonEvent&, SP<IPointer>);

static void hkProcessMouseDownNormal(CInputManager* self, const IPointer::SButtonEvent& event, SP<IPointer> mouse) {
    auto original = (mouseDownNormalFn)g_pCanvas->m_mouseDownNormalHook->m_original;
    static auto PRESIZEONBORDER   = CConfigValue<Config::INTEGER>("general:resize_on_border");
    static auto PBORDERSIZE       = CConfigValue<Config::INTEGER>("general:border_size");
    static auto PBORDERGRABEXTEND = CConfigValue<Config::INTEGER>("general:extend_border_grab_area");

    if (*PRESIZEONBORDER && event.state == WL_POINTER_BUTTON_STATE_PRESSED) {
        const auto screenPos = Pointer::mgr()->position();
        const auto window = Desktop::viewState()->hitTest().windowAt(
            screenPos, Desktop::View::ALLOW_FLOATING | Desktop::View::RESERVED_EXTENTS | Desktop::View::INPUT_EXTENTS);
        if (window && transformedViewport(window->workspaceID()) && !Fullscreen::controller()->isFullscreen(window) && !window->isX11OverrideRedirect()) {
            const auto* viewport = transformedViewport(window->workspaceID());
            const auto worldPos = g_pCanvas->screenToCanvas(*viewport, screenPos, monitorPositionForWindow(window));
            const auto real = window->geometricBox(Desktop::View::IGeometric::GEOMETRIC_CURRENT);
            const auto borderGrab = *PBORDERSIZE + *PBORDERGRABEXTEND;
            const CBox grab = {real.x - borderGrab, real.y - borderGrab, real.width + 2 * borderGrab, real.height + 2 * borderGrab};
            CScopedCanvasWorldInput scope(window->workspaceID(), monitorPositionForWindow(window));
            if (grab.containsPoint(worldPos) && (!real.containsPoint(worldPos) || window->isInCurvedCorner(worldPos.x, worldPos.y)) && !window->hasPopupAt(worldPos)) {
                g_pKeybindManager->resizeWithBorder(event);
                return;
            }
        }
    }

    original(self, event, mouse);
}

// --- Visibility hook ---

typedef bool (*shouldRenderFn)(Render::IHyprRenderer*, PHLWINDOW, PHLMONITOR);

static CBox canvasProjectedBox(const SCanvasViewport& viewport, const PHLMONITOR& monitor, const CBox& worldBox) {
    if (!monitor)
        return {};

    const auto projectedPos = g_pCanvas->canvasToScreen(viewport, worldBox.pos(), monitor->m_position);
    return {projectedPos.x, projectedPos.y, worldBox.width * viewport.zoom, worldBox.height * viewport.zoom};
}

static bool canvasProjectedWindowVisible(const SCanvasViewport& viewport, const PHLWINDOW& window, const PHLMONITOR& monitor) {
    if (!window || !monitor || !window->m_workspace)
        return false;

    CBox worldBox = window->getFullWindowBoundingBox();
    worldBox.translate(window->m_workspace->m_renderOffset->value() + window->m_floatingOffset);

    const CBox projected  = canvasProjectedBox(viewport, monitor, worldBox);
    const CBox monitorBox = {monitor->m_position, monitor->m_size};
    return !projected.intersection(monitorBox).empty();
}

static bool hkShouldRenderWindow(Render::IHyprRenderer* self, PHLWINDOW pWindow, PHLMONITOR pMonitor) {
    auto original = (shouldRenderFn)g_pCanvas->m_shouldRenderHook->m_original;

    if (g_pCanvas && pWindow && pMonitor && pMonitor->m_activeWorkspace &&
        pWindow->workspaceID() == pMonitor->m_activeWorkspace->m_id && pWindow->m_monitor == pMonitor && !pWindow->m_pinned) {
        const auto* viewport = g_pCanvas->viewportForWorkspace(pWindow->workspaceID());
        if (viewport && viewport->enabled && g_pCanvas->isTransformed(*viewport)) {
            const auto workspace = pWindow->m_workspace;
            if (!workspace)
                return false;

            if (workspace->m_renderOffset->isBeingAnimated() || workspace->m_alpha->isBeingAnimated() || workspace->m_forceRendering)
                return true;

            if (Fullscreen::controller()->hasFullscreen(workspace) && !pWindow->isAllowedOverFullscreen() &&
                pWindow->alphaValue(Desktop::View::WINDOW_ALPHA_FADE) * pWindow->alphaValue(Desktop::View::WINDOW_ALPHA_FULLSCREEN) == 0)
                return false;

            if (!workspace->isVisible())
                return false;

            return canvasProjectedWindowVisible(*viewport, pWindow, pMonitor);
        }
    }

    return original(self, pWindow, pMonitor);
}

// --- Render hook ---

typedef void (*renderAllClientsFn)(Render::IHyprRenderer*, PHLMONITOR, PHLWORKSPACE, const steady_tp&, const Vector2D&, const float&);
typedef void (*renderWindowFn)(Render::IHyprRenderer*, PHLWINDOW, PHLMONITOR, const steady_tp&, bool, Render::eRenderPassMode, bool, bool);

static Render::SRenderModifData nativeWorkspaceRenderModif() {
    Render::SRenderModifData data;
    if (g_workspaceRenderTranslate != Vector2D{0, 0})
        data.modifs.emplace_back(Render::SRenderModifData::RMOD_TYPE_TRANSLATE, g_workspaceRenderTranslate);
    if (std::abs(g_workspaceRenderScale - 1.f) > 0.0001f)
        data.modifs.emplace_back(Render::SRenderModifData::RMOD_TYPE_SCALE, g_workspaceRenderScale);
    return data;
}

static Render::SRenderModifData canvasWindowRenderModif(const SCanvasViewport& viewport, const PHLMONITOR& monitor) {
    Render::SRenderModifData data;

    // Window pass boxes are already monitor-local and multiplied by monitor
    // scale before renderModif is applied. Convert the logical camera offset
    // to that same coordinate space, then project world -> screen.
    const Vector2D cameraTranslate = {
        -viewport.offset.x * monitor->m_scale,
        -viewport.offset.y * monitor->m_scale,
    };
    if (cameraTranslate != Vector2D{0, 0})
        data.modifs.emplace_back(Render::SRenderModifData::RMOD_TYPE_TRANSLATE, cameraTranslate);
    if (std::abs(viewport.zoom - 1.0) > 0.0001)
        data.modifs.emplace_back(Render::SRenderModifData::RMOD_TYPE_SCALE, (float)viewport.zoom);

    // renderWorkspace() may already be rendering into translated/scaled output
    // geometry. Apply that native transform after the camera projection.
    if (g_workspaceRenderTranslate != Vector2D{0, 0})
        data.modifs.emplace_back(Render::SRenderModifData::RMOD_TYPE_TRANSLATE, g_workspaceRenderTranslate);
    if (std::abs(g_workspaceRenderScale - 1.f) > 0.0001f)
        data.modifs.emplace_back(Render::SRenderModifData::RMOD_TYPE_SCALE, g_workspaceRenderScale);

    return data;
}

static void queueRenderModif(Render::IHyprRenderer* self, Render::SRenderModifData data) {
    self->m_renderPass.add(makeUnique<CRendererHintsPassElement>(
        CRendererHintsPassElement::SData{std::move(data)}));
}

static void hkRenderAllClientsForWorkspace(Render::IHyprRenderer* self, PHLMONITOR pMonitor, PHLWORKSPACE pWorkspace,
                                           const steady_tp& now, const Vector2D& translate, const float& scale) {
    auto original = (renderAllClientsFn)g_pCanvas->m_renderHook->m_original;
    const auto* viewport = (g_pCanvas && pWorkspace)
        ? g_pCanvas->viewportForWorkspace(pWorkspace->m_id)
        : nullptr;

    if (viewport && viewport->enabled && g_pCanvas->isTransformed(*viewport)) {
        g_pHyprRenderer->damageMonitor(pMonitor);
        // Rendering is still damaged in output space. Disabling simplification
        // prevents the pass from culling windows that become visible via zoom.
        self->m_renderData.noSimplify = true;
    }

    const int         prevDepth     = g_workspaceRenderDepth;
    const WORKSPACEID prevWorkspace = g_workspaceRenderWorkspace;
    const Vector2D    prevTranslate = g_workspaceRenderTranslate;
    const float       prevScale     = g_workspaceRenderScale;

    g_workspaceRenderDepth     = prevDepth + 1;
    g_workspaceRenderWorkspace = pWorkspace ? pWorkspace->m_id : WORKSPACE_INVALID;
    g_workspaceRenderTranslate = translate;
    g_workspaceRenderScale     = scale;

    // Keep Hyprland's normal render scope intact. The Canvas transform is
    // injected only by hkRenderWindow below, so background/layer-shell/UI stay
    // in physical screen-space.
    original(self, pMonitor, pWorkspace, now, translate, scale);

    g_workspaceRenderDepth     = prevDepth;
    g_workspaceRenderWorkspace = prevWorkspace;
    g_workspaceRenderTranslate = prevTranslate;
    g_workspaceRenderScale     = prevScale;
}

static void hkRenderWindow(Render::IHyprRenderer* self, PHLWINDOW pWindow, PHLMONITOR pMonitor, const steady_tp& now,
                           bool decorate, Render::eRenderPassMode mode, bool ignorePosition, bool standalone) {
    auto original = (renderWindowFn)g_pCanvas->m_renderWindowHook->m_original;

    if (g_workspaceRenderDepth <= 0 || !pWindow || !pMonitor || pWindow->m_pinned ||
        pWindow->workspaceID() != g_workspaceRenderWorkspace) {
        original(self, pWindow, pMonitor, now, decorate, mode, ignorePosition, standalone);
        return;
    }

    const auto* viewport = transformedViewport(pWindow->workspaceID());
    if (!viewport) {
        original(self, pWindow, pMonitor, now, decorate, mode, ignorePosition, standalone);
        return;
    }

    // This brackets every render element belonging to the window: surface,
    // subsurfaces, popups, border, rounding and shadow. Geometry stored on the
    // window itself remains untouched.
    queueRenderModif(self, canvasWindowRenderModif(*viewport, pMonitor));
    original(self, pWindow, pMonitor, now, decorate, mode, ignorePosition, standalone);
    queueRenderModif(self, nativeWorkspaceRenderModif());
}

static bool inverseRenderModifToRegion(const Render::SRenderModifData& modif, CRegion& region) {
    if (!modif.enabled)
        return true;

    try {
        for (auto it = modif.modifs.rbegin(); it != modif.modifs.rend(); ++it) {
            switch (it->first) {
                case Render::SRenderModifData::RMOD_TYPE_SCALE: {
                    const float scale = std::any_cast<float>(it->second);
                    if (std::abs(scale) < 0.000001f)
                        return false;
                    region.scale(1.f / scale);
                    break;
                }
                case Render::SRenderModifData::RMOD_TYPE_TRANSLATE: {
                    const auto translate = std::any_cast<Vector2D>(it->second);
                    region.translate(Vector2D{-translate.x, -translate.y});
                    break;
                }
                default:
                    return false;
            }
        }
    } catch (const std::bad_any_cast&) {
        return false;
    }

    region.expand(2);
    return true;
}

typedef void (*drawSurfaceFn)(Render::IElementRenderer*, WP<CSurfacePassElement>, const CRegion&);

static void hkDrawSurface(Render::IElementRenderer* self, WP<CSurfacePassElement> element, const CRegion& damage) {
    auto original = (drawSurfaceFn)g_pCanvas->m_drawSurfaceHook->m_original;
    if (!element || !g_pHyprRenderer) {
        original(self, element, damage);
        return;
    }

    const auto window  = element->m_data.pWindow;
    const auto monitor = element->m_data.pMonitor.lock();
    const auto* viewport = window ? transformedViewport(window->workspaceID()) : nullptr;
    if (!window || !monitor || !viewport || window->m_pinned) {
        original(self, element, damage);
        return;
    }

    auto& renderData = g_pHyprRenderer->m_renderData;
    CRegion screenDamage = renderData.damage.copy();
    CRegion worldDamage  = screenDamage.copy();
    if (!inverseRenderModifToRegion(renderData.renderModif, worldDamage)) {
        original(self, element, damage);
        return;
    }

    renderData.damage = worldDamage;
    ++g_canvasSurfaceDrawDepth;
    original(self, element, worldDamage);
    --g_canvasSurfaceDrawDepth;
    renderData.damage = screenDamage;
}

typedef void (*glDrawTexFn)(Render::GL::CGLElementRenderer*, WP<CTexPassElement>, const CRegion&);

static void hkGLDrawTex(Render::GL::CGLElementRenderer* self, WP<CTexPassElement> element, const CRegion& damage) {
    auto original = (glDrawTexFn)g_pCanvas->m_glDrawTexHook->m_original;
    if (g_canvasSurfaceDrawDepth <= 0 || !element || !g_pHyprRenderer) {
        original(self, element, damage);
        return;
    }

    auto& renderData = g_pHyprRenderer->m_renderData;
    CRegion projectedDamage = damage.copy();
    renderData.renderModif.applyToRegion(projectedDamage);

    const CRegion savedClipRegion = element->m_data.clipRegion.copy();
    const CBox    savedClipBox    = renderData.clipBox;

    if (!element->m_data.clipRegion.empty())
        renderData.renderModif.applyToRegion(element->m_data.clipRegion);
    if (!renderData.clipBox.empty())
        renderData.renderModif.applyToBox(renderData.clipBox);

    original(self, element, projectedDamage);

    element->m_data.clipRegion = savedClipRegion;
    renderData.clipBox         = savedClipBox;
}

// --- Popup positioning hook ---
// When zoomed, expand the constraint box so popups aren't clamped to the physical monitor

typedef void (*applyPositioningFn)(CXDGPopupResource*, const CBox&, const Vector2D&);

static PHLWINDOW popupOwnerWindow(CXDGPopupResource* popup) {
    if (!popup)
        return nullptr;

    auto current = popup->m_parent.lock();
    while (current) {
        if (const auto toplevel = current->m_toplevel.lock()) {
            if (const auto window = toplevel->m_window.lock())
                return window;
        }

        const auto parentPopup = current->m_popup.lock();
        if (!parentPopup)
            break;
        current = parentPopup->m_parent.lock();
    }

    return nullptr;
}

static void hkApplyPositioning(CXDGPopupResource* self, const CBox& availableBox, const Vector2D& t1coord) {
    auto original = (applyPositioningFn)g_pCanvas->m_popupPositionHook->m_original;
    const auto owner = popupOwnerWindow(self);
    const auto* viewport = owner ? transformedViewport(owner->workspaceID()) : nullptr;

    if (viewport) {
        // Popup geometry remains in the window's world-space. Keep the normal
        // positioner rules, but avoid constraining it to the physical output.
        CBox expanded = {t1coord.x - 1000000.0, t1coord.y - 1000000.0, 2000000.0, 2000000.0};
        original(self, expanded, t1coord);
        return;
    }

    original(self, availableBox, t1coord);
}

// --- Constructor / Destructor ---

static CFunctionHook* hookByName(const std::string& name, void* dest) {
    auto fns = HyprlandAPI::findFunctionsByName(PHANDLE, name);
    logf("[hypr-canvas] %s: %zu matches\n", name.c_str(), fns.size());
    if (fns.empty())
        return nullptr;
    auto hook = HyprlandAPI::createFunctionHook(PHANDLE, fns[0].address, dest);
    if (hook && hook->hook())
        logf("[hypr-canvas] hooked %s\n", name.c_str());
    return hook;
}

CCanvas::CCanvas() {
    logf("[hypr-canvas] build %s\n", CANVAS_BUILD_ID);
    m_windowAtHook          = hookByName("windowAt", (void*)&hkWindowAt);
    m_windowSurfaceAtHook   = hookByName("windowSurfaceAt", (void*)&hkWindowSurfaceAt);
    m_surfaceLocalAtHook    = hookByName("surfaceLocalAt", (void*)&hkSurfaceLocalAt);
    m_checkInputOnDecosHook = hookByName("checkInputOnDecos", (void*)&hkCheckInputOnDecos);
    m_hasPopupAtHook        = hookByName("hasPopupAt", (void*)&hkHasPopupAt);
    m_mouseCoordsHook       = hookByName("getMouseCoordsInternal", (void*)&hkGetMouseCoordsInternal);
    m_axisEventHook         = hookByName("onAxisEvent", (void*)&hkOnAxisEvent);
    m_mouseWheelHook        = hookByName("onMouseWheel", (void*)&hkOnMouseWheel);
    {
        auto fns = HyprlandAPI::findFunctionsByName(PHANDLE, std::string("warpTo"));
        for (auto& fn : fns) {
            if (fn.demangled.find("CPointerController::warpTo") == std::string::npos)
                continue;
            m_pointerWarpHook = HyprlandAPI::createFunctionHook(PHANDLE, fn.address, (void*)&hkPointerWarpTo);
            if (m_pointerWarpHook && m_pointerWarpHook->hook())
                logf("[hypr-canvas] hooked CPointerController::warpTo\n");
            break;
        }
    }
    m_mouseMoveUnifiedHook  = hookByName("mouseMoveUnified", (void*)&hkMouseMoveUnified);
    m_setPointerFocusHook   = hookByName("setPointerFocus", (void*)&hkSetPointerFocus);
    m_sendPointerMotionHook = hookByName("sendPointerMotion", (void*)&hkSendPointerMotion);
    m_beginDragHook         = hookByName("beginDragTarget", (void*)&hkBeginDragTarget);
    m_moveMouseHook         = hookByName("moveMouse", (void*)&hkMoveMouse);
    m_endDragHook           = hookByName("endDragTarget", (void*)&hkEndDragTarget);
    m_cursorBorderHook      = hookByName("setCursorIconOnBorder", (void*)&hkSetCursorIconOnBorder);
    m_mouseDownNormalHook   = hookByName("processMouseDownNormal", (void*)&hkProcessMouseDownNormal);
    m_popupPositionHook     = hookByName("applyPositioning", (void*)&hkApplyPositioning);
    // Hook shouldRenderWindow to disable culling when zoomed out
    {
        auto fns = HyprlandAPI::findFunctionsByName(PHANDLE, std::string("shouldRenderWindow"));
        for (auto& fn : fns) {
            // Match the 2-arg overload (PHLWINDOW, PHLMONITOR)
            if (fn.demangled.find("CMonitor") != std::string::npos) {
                logf("[hypr-canvas] found shouldRenderWindow(window,monitor) @ %p\n", fn.address);
                m_shouldRenderHook = HyprlandAPI::createFunctionHook(PHANDLE, fn.address, (void*)&hkShouldRenderWindow);
                if (m_shouldRenderHook) m_shouldRenderHook->hook();
                break;
            }
        }
    }
    m_renderHook = hookByName("renderAllClientsForWorkspace", (void*)&hkRenderAllClientsForWorkspace);
    {
        auto fns = HyprlandAPI::findFunctionsByName(PHANDLE, std::string("renderWindow"));
        logf("[hypr-canvas] renderWindow: %zu matches\n", fns.size());
        for (size_t i = 0; i < fns.size(); ++i) {
            logf("[hypr-canvas] renderWindow match[%zu] @ %p => %s\n", i, fns[i].address, fns[i].demangled.c_str());
            if (fns[i].demangled.find("Render::IHyprRenderer::renderWindow(") == std::string::npos)
                continue;

            m_renderWindowHook = HyprlandAPI::createFunctionHook(PHANDLE, fns[i].address, (void*)&hkRenderWindow);
            if (m_renderWindowHook && m_renderWindowHook->hook())
                logf("[hypr-canvas] hooked exact %s\n", fns[i].demangled.c_str());
            break;
        }
        if (!m_renderWindowHook)
            logf("[hypr-canvas] failed to find Render::IHyprRenderer::renderWindow\n");
    }
    {
        auto fns = HyprlandAPI::findFunctionsByName(PHANDLE, std::string("drawSurface"));
        for (auto& fn : fns) {
            if (fn.demangled.find("Render::IElementRenderer::drawSurface(") == std::string::npos)
                continue;
            m_drawSurfaceHook = HyprlandAPI::createFunctionHook(PHANDLE, fn.address, (void*)&hkDrawSurface);
            if (m_drawSurfaceHook && m_drawSurfaceHook->hook())
                logf("[hypr-canvas] hooked exact %s\n", fn.demangled.c_str());
            break;
        }
    }
    {
        auto fns = HyprlandAPI::findFunctionsByName(PHANDLE, std::string("draw"));
        for (auto& fn : fns) {
            if (fn.demangled.find("Render::GL::CGLElementRenderer::draw(") == std::string::npos ||
                fn.demangled.find("CTexPassElement") == std::string::npos)
                continue;
            m_glDrawTexHook = HyprlandAPI::createFunctionHook(PHANDLE, fn.address, (void*)&hkGLDrawTex);
            if (m_glDrawTexHook && m_glDrawTexHook->hook())
                logf("[hypr-canvas] hooked exact %s\n", fn.demangled.c_str());
            break;
        }
    }
    if (!HyprlandAPI::addDispatcherV2(PHANDLE, "hypr-canvas", [](std::string args) {
            return g_pCanvas ? g_pCanvas->dispatch(std::move(args))
                             : SDispatchResult{.success = false, .error = "hypr-canvas unavailable"};
        })) {
        logf("[hypr-canvas] failed to register dispatcher\n");
    }
    m_hyprctlCommand = HyprlandAPI::registerHyprCtlCommand(PHANDLE, SHyprCtlCommand{
        .name = "hypr-canvas",
        .exact = false,
        .fn = [](eHyprCtlOutputFormat, std::string request) -> std::string {
            std::istringstream stream(request);
            std::string token;
            std::vector<std::string> tokens;
            while (stream >> token)
                tokens.push_back(token);

            if (!tokens.empty() && tokens.front() == "hypr-canvas")
                tokens.erase(tokens.begin());
            if (tokens.size() != 2)
                return "error: usage: hypr-canvas <status|enable|disable|reset|zoom-in|zoom-out|zoom-reset> <workspace-id>\n";

            if (tokens[0] != "status") {
                if (!g_pCanvas)
                    return "error: hypr-canvas unavailable\n";
                const auto result = g_pCanvas->dispatch(tokens[0] + " " + tokens[1]);
                if (!result.success)
                    return "error: " + result.error + "\n";
                return "ok\n";
            }

            WORKSPACEID workspace = WORKSPACE_INVALID;
            try {
                size_t parsed = 0;
                workspace = std::stoll(tokens[1], &parsed);
                if (parsed != tokens[1].size())
                    throw std::invalid_argument("trailing characters");
            } catch (...) {
                return "error: invalid workspace id\n";
            }

            const auto* viewport = g_pCanvas ? g_pCanvas->viewportForWorkspace(workspace) : nullptr;
            const bool enabled = viewport && viewport->enabled;
            const double zoom = viewport ? viewport->zoom : 1.0;
            const Vector2D offset = viewport ? viewport->offset : Vector2D{0, 0};
            Vector2D monitorPosition = {};
            if (const auto ws = State::workspaceState()->query().id(workspace).run()) {
                if (const auto monitor = ws->m_monitor.lock())
                    monitorPosition = monitor->m_position;
            }

            std::ostringstream out;
            out.setf(std::ios::fixed);
            out.precision(6);
            out << "{\"workspace\":" << workspace
                << ",\"enabled\":" << (enabled ? "true" : "false")
                << ",\"zoom\":" << zoom
                << ",\"offset_x\":" << offset.x
                << ",\"offset_y\":" << offset.y
                << ",\"monitor_x\":" << monitorPosition.x
                << ",\"monitor_y\":" << monitorPosition.y << "}\n";
            return out.str();
        },
    });
    if (!m_hyprctlCommand)
        logf("[hypr-canvas] failed to register hyprctl command\n");
    logf("[hypr-canvas] initialized\n");
}

CCanvas::~CCanvas() {
    if (m_hyprctlCommand)
        HyprlandAPI::unregisterHyprCtlCommand(PHANDLE, m_hyprctlCommand);
    HyprlandAPI::removeDispatcher(PHANDLE, "hypr-canvas");
    if (m_windowAtHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_windowAtHook);
    if (m_windowSurfaceAtHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_windowSurfaceAtHook);
    if (m_surfaceLocalAtHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_surfaceLocalAtHook);
    if (m_checkInputOnDecosHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_checkInputOnDecosHook);
    if (m_hasPopupAtHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_hasPopupAtHook);
    if (m_mouseCoordsHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_mouseCoordsHook);
    if (m_axisEventHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_axisEventHook);
    if (m_mouseWheelHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_mouseWheelHook);
    if (m_pointerWarpHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_pointerWarpHook);
    if (m_mouseMoveUnifiedHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_mouseMoveUnifiedHook);
    if (m_setPointerFocusHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_setPointerFocusHook);
    if (m_sendPointerMotionHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_sendPointerMotionHook);
    if (m_beginDragHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_beginDragHook);
    if (m_moveMouseHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_moveMouseHook);
    if (m_endDragHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_endDragHook);
    if (m_cursorBorderHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_cursorBorderHook);
    if (m_mouseDownNormalHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_mouseDownNormalHook);
    if (m_popupPositionHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_popupPositionHook);
    if (m_shouldRenderHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_shouldRenderHook);
    if (m_renderHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_renderHook);
    if (m_renderWindowHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_renderWindowHook);
    if (m_drawSurfaceHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_drawSurfaceHook);
    if (m_glDrawTexHook)
        HyprlandAPI::removeFunctionHook(PHANDLE, m_glDrawTexHook);
}

// --- Coordinate transforms ---

SCanvasViewport* CCanvas::viewportForWorkspace(WORKSPACEID workspace, bool create) {
    if (workspace == WORKSPACE_INVALID)
        return nullptr;
    const auto it = m_viewports.find(workspace);
    if (it != m_viewports.end())
        return &it->second;
    if (!create)
        return nullptr;
    return &m_viewports.try_emplace(workspace).first->second;
}

const SCanvasViewport* CCanvas::viewportForWorkspace(WORKSPACEID workspace) const {
    const auto it = m_viewports.find(workspace);
    return it == m_viewports.end() ? nullptr : &it->second;
}

SCanvasViewport* CCanvas::activeViewport() {
    return viewportForWorkspace(activeWorkspaceID());
}

Vector2D CCanvas::screenToCanvas(const SCanvasViewport& viewport, const Vector2D& screen, const Vector2D& monitorPosition) const {
    return monitorPosition + viewport.offset + (screen - monitorPosition) / viewport.zoom;
}

Vector2D CCanvas::canvasToScreen(const SCanvasViewport& viewport, const Vector2D& canvas, const Vector2D& monitorPosition) const {
    return monitorPosition + (canvas - monitorPosition - viewport.offset) * viewport.zoom;
}

bool CCanvas::isTransformed(const SCanvasViewport& viewport) const {
    return std::abs(viewport.zoom - 1.0) > 0.001
        || std::abs(viewport.offset.x) > 0.5
        || std::abs(viewport.offset.y) > 0.5;
}

void CCanvas::applyZoom(SCanvasViewport& viewport, double newZoom, const Vector2D& anchorScreen, const Vector2D& monitorPosition) {
    const Vector2D anchorCanvas = screenToCanvas(viewport, anchorScreen, monitorPosition);
    viewport.zoom = std::clamp(newZoom, ZOOM_MIN, ZOOM_MAX);
    if (viewport.zoom >= ZOOM_MAX - 0.000001) {
        viewport.zoom = ZOOM_MAX;
        viewport.offset = {0, 0};
        return;
    }
    viewport.offset = anchorCanvas - monitorPosition - (anchorScreen - monitorPosition) / viewport.zoom;
}

SDispatchResult CCanvas::dispatch(std::string args) {
    std::istringstream stream(args);
    std::string action;
    std::string workspaceText;
    std::string extra;
    if (!(stream >> action >> workspaceText) || (stream >> extra))
        return {.success = false, .error = "usage: hypr-canvas <enable|disable|reset|zoom-in|zoom-out|zoom-reset> <workspace-id>"};

    WORKSPACEID workspace = WORKSPACE_INVALID;
    try {
        size_t parsed = 0;
        workspace = std::stoll(workspaceText, &parsed);
        if (parsed != workspaceText.size())
            throw std::invalid_argument("trailing characters");
    } catch (...) {
        return {.success = false, .error = "invalid workspace id"};
    }

    if (action == "enable") {
        auto* viewport = viewportForWorkspace(workspace, true);
        viewport->enabled = true;
        logf("[hypr-canvas] enabled workspace %lld\n", (long long)workspace);
    } else if (action == "disable") {
        auto* viewport = viewportForWorkspace(workspace);
        if (viewport) {
            viewport->enabled = false;
            viewport->zoom = 1.0;
            viewport->offset = {0, 0};
        }
        logf("[hypr-canvas] disabled workspace %lld\n", (long long)workspace);
    } else if (action == "reset" || action == "zoom-reset") {
        auto* viewport = viewportForWorkspace(workspace, true);
        viewport->zoom = 1.0;
        viewport->offset = {0, 0};
        logf("[hypr-canvas] reset workspace %lld\n", (long long)workspace);
    } else if (action == "zoom-in" || action == "zoom-out") {
        auto* viewport = viewportForWorkspace(workspace);
        if (!viewport || !viewport->enabled)
            return {.success = false, .error = "canvas viewport is disabled"};
        if (workspace != activeWorkspaceID())
            return {.success = false, .error = "canvas workspace is not active"};
        const auto monitor = Desktop::focusState()->monitor();
        if (!monitor)
            return {.success = false, .error = "active monitor unavailable"};
        const auto cursorScreen = Pointer::mgr()->position();
        const double newZoom = action == "zoom-in"
            ? viewport->zoom * ZOOM_STEP
            : viewport->zoom / ZOOM_STEP;
        applyZoom(*viewport, newZoom, cursorScreen, monitor->m_position);
        logf("[hypr-canvas] ws=%lld zoom=%.3f offset=(%.1f, %.1f)\n",
             (long long)workspace, viewport->zoom, viewport->offset.x, viewport->offset.y);
    } else {
        return {.success = false, .error = "unknown hypr-canvas action"};
    }

    scheduleFrame();
    return {};
}
