-- lua/latexzettel/client.lua
local M = {}

local uv = vim.uv or vim.loop

---@class LatexZettelClientConfig
---@field cmd string[]                  -- command to start server
---@field protocol_version integer      -- must match server PROTOCOL_VERSION
---@field initialize_params table       -- params for initialize
---@field debug boolean                 -- log stderr lines to :messages
---@field request_timeout_ms integer    -- default timeout per request
---@field on_server_exit fun(code: integer, signal: integer)|nil

---@class LatexZettelClient
---@field job_id integer|nil
---@field chan integer|nil
---@field pending table<any, {cb: function, timer: any|nil}>
---@field next_id integer
---@field config LatexZettelClientConfig
---@field initialized boolean
---@field stderr_buf table
---@field stdout_buf string

local function notify(msg, level)
	vim.schedule(function()
		vim.notify(msg, level or vim.log.levels.INFO, { title = "latexzettel" })
	end)
end

local function json_encode(obj)
	return vim.json.encode(obj)
end

local function json_decode(line)
	return vim.json.decode(line, { luanil = { object = true, array = true } })
end

local function default_config()
	return {
		cmd = { "latexzettel-server" },
		protocol_version = 1,
		initialize_params = {
			client = {
				name = "latexzettel.nvim",
				version = "0.1.0",
				capabilities = {
					cancel = true,
					transport = "stdio-jsonl",
				},
			},
		},
		debug = false,
		request_timeout_ms = 30000,
		on_server_exit = nil,
	}
end

---@param cfg LatexZettelClientConfig|nil
function M.new(cfg)
	local c = {
		job_id = nil,
		chan = nil,
		pending = {},
		next_id = 1,
		config = vim.tbl_deep_extend("force", default_config(), cfg or {}),
		initialized = false,
		stderr_buf = {},
		stdout_buf = "",
	}
	return setmetatable(c, { __index = M })
end

---@param self LatexZettelClient
function M.is_running(self)
	return self.job_id ~= nil and self.job_id > 0
end

---@param self LatexZettelClient
local function _clear_pending(self, err)
	for id, entry in pairs(self.pending) do
		if entry.timer then
			entry.timer:stop()
			entry.timer:close()
		end
		self.pending[id] = nil
		vim.schedule(function()
			entry.cb(nil, err or "server stopped")
		end)
	end
end

---@param self LatexZettelClient
---@param line string
local function _handle_stdout_line(self, line)
	if line == nil or line == "" then
		return
	end

	local ok, msg = pcall(json_decode, line)
	if not ok then
		-- protocol violation from server; ignore but keep running
		notify("Invalid JSON from server: " .. tostring(msg), vim.log.levels.WARN)
		return
	end

	local id = msg.id
	if id == nil then
		notify("Server response missing id", vim.log.levels.WARN)
		return
	end

	local entry = self.pending[id]
	if not entry then
		-- late response or unknown id
		return
	end

	if entry.timer then
		entry.timer:stop()
		entry.timer:close()
	end
	self.pending[id] = nil

	if msg.ok == true then
		entry.cb(msg.result, nil)
	else
		local err = msg.error or {}
		entry.cb(nil, err)
	end
end

---@param self LatexZettelClient
local function _stdout_on_data(self, data)
	-- data is table of lines (without trailing \n) in jobstart callbacks
	if type(data) ~= "table" then
		return
	end
	for _, line in ipairs(data) do
		if line ~= nil then
			_handle_stdout_line(self, line)
		end
	end
end

---@param self LatexZettelClient
local function _stderr_on_data(self, data)
	if type(data) ~= "table" then
		return
	end
	for _, line in ipairs(data) do
		if line ~= nil and line ~= "" then
			table.insert(self.stderr_buf, line)
			if self.config.debug then
				notify("server: " .. line, vim.log.levels.DEBUG)
			end
		end
	end
end

---@param self LatexZettelClient
function M.start(self)
	if M.is_running(self) then
		return true
	end

	self.stderr_buf = {}
	self.initialized = false

	local job_id = vim.fn.jobstart(self.config.cmd, {
		rpc = false,
		pty = false,
		stdin = "pipe",
		stdout_buffered = false,
		stderr_buffered = false,
		on_stdout = function(_, data, _)
			_stdout_on_data(self, data)
		end,
		on_stderr = function(_, data, _)
			_stderr_on_data(self, data)
		end,
		on_exit = function(_, code, signal)
			self.job_id = nil
			self.chan = nil
			self.initialized = false
			local msg = ("server exited (code=%s signal=%s)"):format(tostring(code), tostring(signal))
			_clear_pending(self, msg)
			if self.config.on_server_exit then
				self.config.on_server_exit(code, signal)
			end
		end,
	})

	if job_id <= 0 then
		notify("No se pudo iniciar latexzettel-server. Verifique PATH y dependencias.", vim.log.levels.ERROR)
		return false
	end

	self.job_id = job_id
	self.chan = job_id

	-- initialize handshake
	local ok = self:initialize(function(result, err)
		if err then
			notify("initialize failed: " .. vim.inspect(err), vim.log.levels.ERROR)
		else
			self.initialized = true
		end
	end)

	return ok
end

---@param self LatexZettelClient
function M.stop(self)
	if not M.is_running(self) then
		return
	end
	-- best effort: stop job
	vim.fn.jobstop(self.job_id)
	self.job_id = nil
	self.chan = nil
	self.initialized = false
	_clear_pending(self, "server stopped")
end

---@param self LatexZettelClient
function M.restart(self)
	self:stop()
	return self:start()
end

---@param self LatexZettelClient
---@param payload table
local function _send(self, payload)
	if not self.chan then
		return false
	end
	local line = json_encode(payload) .. "\n"
	vim.fn.chansend(self.chan, line)
	return true
end

---@param self LatexZettelClient
---@param method string
---@param params table|nil
---@param cb fun(result: table|nil, err: table|string|nil)
---@param timeout_ms integer|nil
function M.request(self, method, params, cb, timeout_ms)
	if not M.is_running(self) then
		cb(nil, "server not running")
		return false
	end

	local id = self.next_id
	self.next_id = self.next_id + 1

	local payload = {
		v = self.config.protocol_version,
		id = id,
		method = method,
		params = params or {},
	}

	local timer = uv.new_timer()
	local to = timeout_ms or self.config.request_timeout_ms
	timer:start(to, 0, function()
		timer:stop()
		timer:close()
		if self.pending[id] then
			self.pending[id] = nil
			vim.schedule(function()
				cb(
					nil,
					{ code = "TIMEOUT", message = "Request timed out", data = { method = method, timeout_ms = to } }
				)
			end)
		end
	end)

	self.pending[id] = { cb = cb, timer = timer }

	local ok = _send(self, payload)
	if not ok then
		if self.pending[id] and self.pending[id].timer then
			self.pending[id].timer:stop()
			self.pending[id].timer:close()
		end
		self.pending[id] = nil
		cb(nil, "failed to send")
		return false
	end

	return true
end

---@param self LatexZettelClient
---@param cb fun(result: table|nil, err: table|string|nil)
function M.initialize(self, cb)
	return self:request("initialize", self.config.initialize_params, function(result, err)
		if err then
			cb(nil, err)
			return
		end
		cb(result, nil)
	end, 10000)
end

---@param self LatexZettelClient
---@param id_to_cancel string|integer
---@param cb fun(result: table|nil, err: table|string|nil)
function M.cancel(self, id_to_cancel, cb)
	return self:request("cancel", { id_to_cancel = id_to_cancel }, cb, 5000)
end

return M
