#pragma once

#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/plugins/HookSystem.hpp>
#include <hyprland/src/helpers/math/Math.hpp>
#include <hyprland/src/devices/IPointer.hpp>
#include <hyprutils/memory/SharedPtr.hpp>

#include <string>
#include <unordered_map>

struct SCanvasViewport {
    bool     enabled = false;
    double   zoom    = 1.0;
    Vector2D offset  = {0, 0};
};

class CCanvas {
  public:
    CCanvas();
    ~CCanvas();

    SCanvasViewport*       viewportForWorkspace(WORKSPACEID workspace, bool create = false);
    const SCanvasViewport* viewportForWorkspace(WORKSPACEID workspace) const;
    SCanvasViewport*       activeViewport();

    Vector2D screenToCanvas(const SCanvasViewport& viewport, const Vector2D& screen, const Vector2D& monitorPosition = {}) const;
    Vector2D canvasToScreen(const SCanvasViewport& viewport, const Vector2D& canvas, const Vector2D& monitorPosition = {}) const;
    bool     isTransformed(const SCanvasViewport& viewport) const;
    void     applyZoom(SCanvasViewport& viewport, double newZoom, const Vector2D& anchorScreen, const Vector2D& monitorPosition = {});

    SDispatchResult dispatch(std::string args);

    static constexpr double ZOOM_MIN  = 0.05;
    static constexpr double ZOOM_MAX  = 1.0;
    static constexpr double ZOOM_STEP = 1.15;

    CFunctionHook* m_windowAtHook          = nullptr;
    CFunctionHook* m_windowSurfaceAtHook   = nullptr;
    CFunctionHook* m_surfaceLocalAtHook    = nullptr;
    CFunctionHook* m_checkInputOnDecosHook = nullptr;
    CFunctionHook* m_hasPopupAtHook        = nullptr;
    CFunctionHook* m_mouseCoordsHook       = nullptr;
    CFunctionHook* m_mouseWheelHook        = nullptr;
    CFunctionHook* m_axisEventHook         = nullptr;
    CFunctionHook* m_pointerWarpHook       = nullptr;
    CFunctionHook* m_mouseMoveUnifiedHook  = nullptr;
    CFunctionHook* m_setPointerFocusHook   = nullptr;
    CFunctionHook* m_sendPointerMotionHook = nullptr;
    CFunctionHook* m_beginDragHook         = nullptr;
    CFunctionHook* m_moveMouseHook         = nullptr;
    CFunctionHook* m_endDragHook           = nullptr;
    CFunctionHook* m_cursorBorderHook      = nullptr;
    CFunctionHook* m_mouseDownNormalHook   = nullptr;
    CFunctionHook* m_popupPositionHook     = nullptr;
    CFunctionHook* m_shouldRenderHook      = nullptr;
    CFunctionHook* m_renderHook            = nullptr;
    CFunctionHook* m_renderWindowHook      = nullptr;
    CFunctionHook* m_drawSurfaceHook       = nullptr;
    CFunctionHook* m_glDrawTexHook         = nullptr;
    SP<SHyprCtlCommand> m_hyprctlCommand;

  private:
    std::unordered_map<WORKSPACEID, SCanvasViewport> m_viewports;
};

inline std::unique_ptr<CCanvas> g_pCanvas;
inline HANDLE                   PHANDLE = nullptr;
