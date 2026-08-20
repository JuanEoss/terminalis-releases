local M = {}
M.name        = "docker-monitor"
M.version     = "1.0"
M.author      = "someone"
M.description = "Show running Docker containers in a side panel."
M.permissions = { "shell" }

M.panel = { title = "Docker", icon = "shippingbox", width = 260, side = "right" }

function M.on_command(ctx)
    if ctx.command:match("^docker ") then terminalis.panel.reload() end
end

function M.panel_content()
    local raw, err = terminalis.shell("docker ps --format '{{.Names}}|{{.Status}}' 2>/dev/null")
    if err then
        return { ui.label("Permission required: " .. err, { color = "#FF453A" }) }
    end
    if raw == "" then
        return { ui.label("Docker not running", { color = "#636366" }) }
    end
    local rows = {}
    for line in raw:gmatch("[^\n]+") do
        local name, status = line:match("([^|]+)|([^|]+)")
        if name then
            table.insert(rows, {
                label  = name,
                detail = status,
                icon   = status:match("^Up") and "checkmark.circle.fill" or "xmark.circle.fill",
            })
        end
    end
    return {
        ui.label("Containers (" .. #rows .. ")", { bold = true }),
        ui.separator(),
        ui.list(rows, { on_select = "tail_logs" }),
        ui.spacer(),
        ui.button("Refresh", { action = "refresh", icon = "arrow.clockwise" }),
    }
end

function M.tail_logs(ctx) terminalis.send("docker logs -f " .. ctx.label .. "\n") end
function M.refresh()      terminalis.panel.reload() end

return M
