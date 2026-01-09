-- lua/latexzettel/ui.lua
local M = {}

local function center_opts(width, height)
	local cols = vim.o.columns
	local lines = vim.o.lines
	return {
		relative = "editor",
		width = width,
		height = height,
		col = math.floor((cols - width) / 2),
		row = math.floor((lines - height) / 2),
		style = "minimal",
		border = "rounded",
	}
end

---@class LatexZettelField
---@field name string
---@field label string
---@field default string|nil

---@param title string
---@param fields LatexZettelField[]
---@param on_submit fun(values: table)
function M.prompt_form(title, fields, on_submit)
	local width = 70
	local height = #fields + 4

	local buf = vim.api.nvim_create_buf(false, true)
	local win = vim.api.nvim_open_win(buf, true, center_opts(width, height))

	vim.api.nvim_buf_set_option(buf, "buftype", "prompt")
	vim.fn.prompt_setprompt(buf, title .. " > ")

	-- Render instructions + fields template
	local lines = {}
	table.insert(lines, "Complete los campos y presione <Enter> para enviar. <Esc> para cancelar.")
	table.insert(lines, "")
	for i, f in ipairs(fields) do
		local d = f.default and (" (" .. f.default .. ")") or ""
		table.insert(lines, ("%d) %s%s:"):format(i, f.label, d))
	end
	vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)

	-- We'll use a second buffer for input (simpler): open a scratch buffer below
	local ibuf = vim.api.nvim_create_buf(false, true)
	local iwin = vim.api.nvim_open_win(ibuf, true, center_opts(width, #fields + 4))
	vim.api.nvim_buf_set_option(ibuf, "buftype", "acwrite")
	vim.api.nvim_buf_set_option(ibuf, "filetype", "latexzettel-form")

	local ilines = {}
	table.insert(ilines, "Ingrese valores (uno por línea). Vacío = default.")
	table.insert(ilines, "")
	for _, f in ipairs(fields) do
		table.insert(ilines, "")
	end
	vim.api.nvim_buf_set_lines(ibuf, 0, -1, false, ilines)
	vim.api.nvim_win_set_cursor(iwin, { 3, 0 })

	local function close_all()
		if vim.api.nvim_win_is_valid(iwin) then
			vim.api.nvim_win_close(iwin, true)
		end
		if vim.api.nvim_win_is_valid(win) then
			vim.api.nvim_win_close(win, true)
		end
		if vim.api.nvim_buf_is_valid(ibuf) then
			vim.api.nvim_buf_delete(ibuf, { force = true })
		end
		if vim.api.nvim_buf_is_valid(buf) then
			vim.api.nvim_buf_delete(buf, { force = true })
		end
	end

	local function submit()
		local raw = vim.api.nvim_buf_get_lines(ibuf, 2, 2 + #fields, false)
		local values = {}
		for i, f in ipairs(fields) do
			local v = raw[i] or ""
			v = vim.trim(v)
			if v == "" and f.default ~= nil then
				v = f.default
			end
			values[f.name] = v
		end
		close_all()
		on_submit(values)
	end

	-- keymaps
	local opts = { nowait = true, noremap = true, silent = true }
	vim.keymap.set("n", "<Esc>", function()
		close_all()
	end, vim.tbl_extend("force", opts, { buffer = buf }))
	vim.keymap.set("n", "<Esc>", function()
		close_all()
	end, vim.tbl_extend("force", opts, { buffer = ibuf }))
	vim.keymap.set("n", "<CR>", function()
		submit()
	end, vim.tbl_extend("force", opts, { buffer = ibuf }))
	vim.keymap.set("i", "<CR>", function()
		vim.cmd("stopinsert")
		submit()
	end, vim.tbl_extend("force", opts, { buffer = ibuf }))

	return { win = win, buf = buf, input_win = iwin, input_buf = ibuf, close = close_all }
end

---@param title string
---@param text_lines string[]
function M.show_output(title, text_lines)
	local width = math.min(100, vim.o.columns - 4)
	local height = math.min(#text_lines + 2, vim.o.lines - 4)

	local buf = vim.api.nvim_create_buf(false, true)
	vim.api.nvim_buf_set_lines(buf, 0, -1, false, text_lines)

	local win = vim.api.nvim_open_win(buf, true, {
		relative = "editor",
		width = width,
		height = height,
		col = math.floor((vim.o.columns - width) / 2),
		row = math.floor((vim.o.lines - height) / 2),
		style = "minimal",
		border = "rounded",
		title = title,
	})

	vim.keymap.set("n", "q", function()
		if vim.api.nvim_win_is_valid(win) then
			vim.api.nvim_win_close(win, true)
		end
		if vim.api.nvim_buf_is_valid(buf) then
			vim.api.nvim_buf_delete(buf, { force = true })
		end
	end, { buffer = buf, nowait = true, noremap = true, silent = true })
end

return M
