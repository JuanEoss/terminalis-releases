local M = {}
M.name        = "plugin-de-prueba"
M.version     = "1.0"
M.author       = "terminalis-plugins"
M.description = "Placeholder plugin used to validate the marketplace registry pipeline. Remove once real plugins are published."

function M.on_load()
    terminalis.log("plugin-de-prueba loaded")
end

return M
