-- Example Hyprland Canvas integration
-- Copy relevant parts to your ~/.config/hypr/hyprland.lua

-- Canvas state helpers
local function is_canvas_active_now()
    local ws = hl.get_active_workspace()
    if not ws or ws.special then return false end
    -- In practice, read from toggle-state.json or use a helper
    return false -- placeholder
end

-- Canvas toggle (optional - SUPER+SPACE cycle replaces this)
-- hl.bind("SUPER + SHIFT + C", function()
--     hl.exec_cmd("/home/youruser/.local/bin/hypr-canvas-ctl canvas-toggle")
-- end)

-- Canvas: pan (mouse binds)
hl.bind("SUPER + SHIFT + mouse:272", function()
    os.execute("canvas-ctl pan-start")
end, { mouse = true })

hl.bind("SUPER + SHIFT + mouse:272", function()
    os.execute("canvas-ctl pan-stop")
end, { mouse = true, release = true })

-- Canvas: edge-scroll (drag window to screen edge → camera follows)
hl.bind("SUPER + mouse:272", function()
    hl.dispatch(hl.dsp.window.drag())
    hl.exec_cmd("canvas-ctl edge-start")
end, { mouse = true })

hl.bind("SUPER + mouse:272", function()
    os.execute("canvas-ctl edge-stop")
end, { mouse = true, release = true })

-- Canvas: center view on the floating window under the cursor
hl.bind("SUPER + mouse:274", function()
    os.execute("canvas-ctl center-cursor")
end, { mouse = true })

-- Canvas: navigation (4-dir spatial)
hl.bind("SUPER + SHIFT + left", function()
    os.execute("canvas-ctl nav-left")
end)
hl.bind("SUPER + SHIFT + right", function()
    os.execute("canvas-ctl nav-right")
end)
hl.bind("SUPER + SHIFT + up", function()
    os.execute("canvas-ctl nav-up")
end)
hl.bind("SUPER + SHIFT + down", function()
    os.execute("canvas-ctl nav-down")
end)

-- Canvas: toggle & invert
hl.bind("SUPER + SHIFT + V", function()
    os.execute("canvas-ctl canvas-toggle-single")
end)
hl.bind("SUPER + SHIFT + G", function()
    os.execute("canvas-ctl toggle")
end)

-- Super+Space: Cycle workspace mode (Dwindle → Canvas → Scrolling → Dwindle)
hl.bind("SUPER + SPACE", function()
    -- Implement cycle_mode() from main config
end)
