-- Hyprland Canvas Gold integration example
--
-- This is the distributable extraction of the integration validated with
-- Hyprland 0.56.2. Install the scripts from ../scripts into ~/.local/bin first.
-- Keep general.resize_on_border = false in the base Hyprland configuration;
-- hypr-canvas-sync-resize temporarily enables it for the active Canvas workspace.

-- Gold startup ordering: publish the Hyprland session environment to systemd,
-- load the ABI-matched companion plugin, then start the target that owns the
-- Canvas daemon service.
local data_home = os.getenv("XDG_DATA_HOME")
if not data_home or data_home == "" then
    data_home = (os.getenv("HOME") or "") .. "/.local/share"
end
local plugin_path = data_home .. "/hyprcanvas-shinishiz/plugins/hypr-canvas.so"

hl.on("hyprland.start", function()
    hl.exec_cmd([[
/bin/sh -lc '
dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE HYPRLAND_INSTANCE_SIGNATURE &&
systemctl --user import-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE HYPRLAND_INSTANCE_SIGNATURE &&
(hyprctl plugin load ]] .. string.format("%q", plugin_path) .. [[ >/dev/null 2>&1 || true) &&
systemctl --user start hyprland-session.target
'
]])
end)

-- Canvas state confirmation via toggle-state.json
local function read_confirmed_canvas_state(ws_id)
    local state_path = os.getenv("XDG_RUNTIME_DIR") .. "/canvas/toggle-state.json"
    local file = io.open(state_path, "r")
    if not file then return false end
    local content = file:read("*a")
    file:close()
    -- Simple JSON parsing without external dependency
    -- Looking for: {"_v":3,"9":{"active":true,...}}
    local ws_key = '"' .. tostring(ws_id) .. '"'
    local active_pattern = ws_key .. '%s*:%s*{%s*"active"%s*:%s*true'
    return content:match(active_pattern) ~= nil
end

-- Read confirmed canvas state for workspace
local function is_canvas_confirmed_active(ws_id)
    return read_confirmed_canvas_state(ws_id)
end

-- Check if Canvas is active for current workspace
local function is_canvas_active_now()
    local ws = hl.get_active_workspace()
    if not ws or ws.special then
        return false
    end
    return is_canvas_confirmed_active(ws.id)
end

-- Allow natural border/corner resize only while the active workspace is in
-- Canvas mode. Hyprland's resize_on_border option is global, so keep it synced
-- whenever the active workspace changes or the config is reloaded.
local function sync_canvas_border_resize()
    hl.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-canvas-sync-resize")
end

hl.on("workspace.active", sync_canvas_border_resize)
hl.on("config.reloaded", sync_canvas_border_resize)

-- Gold relative-workspace movement. Keep this implementation unchanged:
-- SUPER+ALT+0 moves/follows to current+1; SUPER+SHIFT+0 to current-1.
local function move_focused_window_relative(delta)
    local ws = hl.get_active_workspace()
    if not ws or ws.special then return end

    local target = ws.id + delta
    if target < 1 then return end

    hl.dispatch(hl.dsp.window.move({ workspace = tostring(target) }))
end

for i = 1, 9 do
    hl.bind("SUPER + " .. i, hl.dsp.focus({ workspace = tostring(i) }))
    hl.bind("SUPER + SHIFT + " .. i, hl.dsp.window.move({ workspace = tostring(i) }))
end

hl.bind("SUPER + ALT + 0", function() move_focused_window_relative(1) end)
hl.bind("SUPER + SHIFT + 0", function() move_focused_window_relative(-1) end)

-- Super+Space: external state machine avoids Lua callback/keybind regressions.
hl.bind("SUPER + space", hl.dsp.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-cycle-mode"), {
    transparent = true,
    dont_inhibit = true,
    submap_universal = true,
    allow_input_capture = true,
})

-- Pan: press to start, release to stop
hl.bind("SUPER + SHIFT + mouse:272",
    hl.dsp.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-canvas-ctl pan-start"),
    { mouse = true }
)

hl.bind("SUPER + SHIFT + mouse:272",
    hl.dsp.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-canvas-ctl pan-stop"),
    { mouse = true, release = true }
)

-- Canvas: edge-scroll (drag window to screen edge -> camera follows)
hl.bind("SUPER + mouse:272", function()
    hl.dispatch(hl.dsp.window.drag())
    hl.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-canvas-ctl edge-start")
end, { mouse = true })

hl.bind("SUPER + mouse:272", function()
    hl.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-canvas-ctl edge-stop")
end, { mouse = true, release = true })

-- Canvas: center view on the floating window under the cursor
hl.bind("SUPER + mouse:274", function()
    hl.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-canvas-ctl center-cursor")
end, { mouse = true })

-- Canvas: toggle & invert
hl.bind("SUPER + SHIFT + V", function()
    hl.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-canvas-ctl canvas-toggle-single")
end)
hl.bind("SUPER + SHIFT + G", function()
    hl.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-canvas-ctl toggle")
end)

-- Conditional movement/navigation used by the Gold configuration.
hl.bind("SUPER + SHIFT + LEFT", function()
    if is_canvas_active_now() then
        hl.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-canvas-ctl nav-left")
    else
        local ws = hl.get_active_workspace()
        if ws and not ws.special then
            if ws.tiled_layout == "dwindle" then
                hl.dispatch(hl.dsp.window.move({ direction = "l" }))
            elseif ws.tiled_layout == "scrolling" then
                hl.dispatch("layout", "consume_or_expel prev")
            end
        end
    end
end)

hl.bind("SUPER + SHIFT + RIGHT", function()
    if is_canvas_active_now() then
        hl.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-canvas-ctl nav-right")
    else
        local ws = hl.get_active_workspace()
        if ws and not ws.special then
            if ws.tiled_layout == "dwindle" then
                hl.dispatch(hl.dsp.window.move({ direction = "r" }))
            elseif ws.tiled_layout == "scrolling" then
                hl.dispatch("layout", "consume_or_expel next")
            end
        end
    end
end)

hl.bind("SUPER + SHIFT + UP", function()
    if is_canvas_active_now() then
        hl.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-canvas-ctl nav-up")
    else
        local ws = hl.get_active_workspace()
        if ws and not ws.special and ws.tiled_layout == "dwindle" then
            hl.dispatch(hl.dsp.window.move({ direction = "u" }))
        end
    end
end)

hl.bind("SUPER + SHIFT + DOWN", function()
    if is_canvas_active_now() then
        hl.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-canvas-ctl nav-down")
    else
        local ws = hl.get_active_workspace()
        if ws and not ws.special and ws.tiled_layout == "dwindle" then
            hl.dispatch(hl.dsp.window.move({ direction = "d" }))
        end
    end
end)

-- Canvas zoom reset. SUPER+wheel is handled inside the hypr-canvas plugin so
-- normal SUPER+scroll behavior remains untouched outside Canvas mode.
local function canvas_zoom(command)
    if not is_canvas_active_now() then
        return
    end
    hl.exec_cmd(os.getenv("HOME") .. "/.local/bin/hypr-canvas-ctl " .. command)
end

hl.bind("SUPER + 0", function()
    canvas_zoom("zoom-reset")
end)
