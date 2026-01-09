-- lua/latexzettel/init.lua
local Client = require("latexzettel.client")
local UI = require("latexzettel.ui")

local M = {}

---@class LatexZettelSetup
---@field server_cmd string[]|nil
---@field protocol_version integer|nil
---@field debug boolean|nil

M._client = nil
M._config = {
	server_cmd = { "latexzettel-server" },
	protocol_version = 1,
	debug = false,
}

local function notify(msg, level)
	vim.schedule(function()
		vim.notify(msg, level or vim.log.levels.INFO, { title = "latexzettel" })
	end)
end

function M.setup(opts)
	opts = opts or {}
	M._config = vim.tbl_deep_extend("force", M._config, opts)

	M._client = Client.new({
		cmd = M._config.server_cmd,
		protocol_version = M._config.protocol_version,
		debug = M._config.debug,
	})
end

function M.client()
	if not M._client then
		M.setup({})
	end
	return M._client
end

function M.start()
	local c = M.client()
	return c:start()
end

function M.stop()
	local c = M.client()
	c:stop()
end

function M.restart()
	local c = M.client()
	c:restart()
end

-- ---------------------------------------------------------------------------
-- Actions (MVP)
-- ---------------------------------------------------------------------------

function M.notes_new_form()
	local c = M.client()
	if not c:is_running() then
		M.start()
	end

	UI.prompt_form("notes.new", {
		{ name = "note_name", label = "note_name", default = "" },
		{ name = "reference_name", label = "reference_name", default = "" },
		{ name = "extension", label = "extension (tex/md)", default = "tex" },
	}, function(values)
		local params = {
			note_name = values.note_name,
			reference_name = (values.reference_name ~= "" and values.reference_name or nil),
			extension = values.extension,
			add_to_documents = true,
			create_file = true,
		}
		c:request("notes.new", params, function(result, err)
			if err then
				notify("Error: " .. vim.inspect(err), vim.log.levels.ERROR)
				return
			end
			notify("Nota creada: " .. tostring(result.note_name))
		end)
	end)
end

function M.render_updates_form()
	local c = M.client()
	if not c:is_running() then
		M.start()
	end

	UI.prompt_form("render.updates", {
		{ name = "format", label = "format (pdf/html)", default = "pdf" },
	}, function(values)
		local params = { format = values.format }
		c:request("render.updates", params, function(result, err)
			if err then
				notify("Error: " .. vim.inspect(err), vim.log.levels.ERROR)
				return
			end

			local lines = {}
			table.insert(lines, "Rendered: " .. tostring(#(result.rendered or {})))
			for _, fn in ipairs(result.rendered or {}) do
				table.insert(lines, "  " .. fn)
			end
			table.insert(lines, "")
			table.insert(lines, "Re-render targets: " .. tostring(#(result.rerendered_targets or {})))
			for _, fn in ipairs(result.rerendered_targets or {}) do
				table.insert(lines, "  " .. fn)
			end
			table.insert(lines, "")
			table.insert(lines, "Re-render sources: " .. tostring(#(result.rerendered_sources or {})))
			for _, fn in ipairs(result.rerendered_sources or {}) do
				table.insert(lines, "  " .. fn)
			end

			UI.show_output("render.updates", lines)
		end, 5 * 60 * 1000) -- 5 min
	end)
end

function M.notes_list_recent()
	local c = M.client()
	if not c:is_running() then
		M.start()
	end

	c:request("notes.list_recent", { n = 20 }, function(result, err)
		if err then
			notify("Error: " .. vim.inspect(err), vim.log.levels.ERROR)
			return
		end
		local lines = { "Recent notes:" }
		for i, it in ipairs(result.items or {}) do
			table.insert(lines, ("%02d  %s"):format(i, it.filename))
		end
		UI.show_output("notes.list_recent", lines)
	end)
end

return M
