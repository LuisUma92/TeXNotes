-- plugin/latexzettel.lua
local lz = require("latexzettel")

-- setup con defaults; el usuario puede sobrescribir en su config de Lazy.nvim
lz.setup({})

vim.api.nvim_create_user_command("LatexZettelStart", function()
	lz.start()
end, {})

vim.api.nvim_create_user_command("LatexZettelStop", function()
	lz.stop()
end, {})

vim.api.nvim_create_user_command("LatexZettelRestart", function()
	lz.restart()
end, {})

vim.api.nvim_create_user_command("LatexZettelNewNote", function()
	lz.notes_new_form()
end, {})

vim.api.nvim_create_user_command("LatexZettelRenderUpdates", function()
	lz.render_updates_form()
end, {})

vim.api.nvim_create_user_command("LatexZettelRecent", function()
	lz.notes_list_recent()
end, {})

-- Keymaps default (cámbialos en tu config si deseas)
vim.keymap.set("n", "<leader>zn", "<cmd>LatexZettelNewNote<cr>", { desc = "latexzettel: new note" })
vim.keymap.set("n", "<leader>zu", "<cmd>LatexZettelRenderUpdates<cr>", { desc = "latexzettel: render updates" })
vim.keymap.set("n", "<leader>zr", "<cmd>LatexZettelRecent<cr>", { desc = "latexzettel: recent notes" })
