local M = {}
M.name        = "markdown-viewer"
M.version     = "1.0"
M.author      = "someone"
M.description = "Rendered Markdown with Mermaid diagram support."

M.tab_view = {
    file_types     = { "md", "markdown" },
    toggle_icon    = "doc.richtext.fill",
    toggle_tooltip = "Rendered view",
}

local function js_escape(s)
    return s:gsub("\\","\\\\"):gsub('"','\\"')
             :gsub("\r",""):gsub("\n","\\n"):gsub("\t","\\t")
end

function M.tab_view_content(ctx)
    local bg  = ctx.dark_mode and "#1c1c1e" or "#ffffff"
    local fg  = ctx.dark_mode and "#e5e5ea" or "#1c1c1e"
    local bg2 = ctx.dark_mode and "#2c2c2e" or "#f2f2f7"
    local tmt = ctx.dark_mode and "dark"    or "default"

    local html =
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        .. '<script src="https://cdn.jsdelivr.net/npm/marked@9/marked.min.js"></script>'
        .. '<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>'
        .. '<style>'
        .. 'body{font-family:-apple-system,sans-serif;font-size:15px;line-height:1.75;'
        .. 'padding:32px 40px;width:100%;background:' .. bg .. ';color:' .. fg .. '}'
        .. 'pre{background:' .. bg2 .. ';padding:16px;border-radius:8px;overflow-x:auto}'
        .. 'code{font-family:Menlo,monospace;font-size:.87em;background:' .. bg2 .. ';padding:2px 6px;border-radius:4px}'
        .. '.mermaid-wrap{background:' .. bg2 .. ';border-radius:12px;padding:24px;'
        .. 'margin:1em 0;display:flex;justify-content:center}'
        .. '</style></head><body><div id="root"></div><script>'
        .. 'mermaid.initialize({startOnLoad:false,theme:"' .. tmt .. '",securityLevel:"loose"});'
        .. 'marked.use({renderer:{code(c,l){'
        .. 'if(l==="mermaid")return\'<div class="mermaid-wrap"><div class="mermaid">\'+c+\'</div></div>\';'
        .. 'return\'<pre><code>\'+c.replace(/&/g,"&amp;").replace(/</g,"&lt;")+\'</code></pre>\'}}});'
        .. 'document.getElementById("root").innerHTML=marked.parse("' .. js_escape(ctx.content) .. '");'
        .. 'mermaid.run({nodes:document.querySelectorAll(".mermaid")});'
        .. '</script></body></html>'

    return ui.webview(html)
end

return M
