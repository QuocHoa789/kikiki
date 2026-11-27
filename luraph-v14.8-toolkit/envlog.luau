--!nonstrict
--[[
	envlog.luau — Luau environment logger for Luraph deobfuscation
	==============================================================
	Wraps an execution environment so every global lookup, function call
	and property access performed by a protected script is traced.

	Use with the luraph-v14.8-toolkit sandbox:
	    local env = require("apiroblox")          -- stub Roblox API
	    local logged = require("envlog").wrap(env, logfn)
	    setfenv(protected_chunk, logged)

	Behaviour traced:
	  * global reads  -> "<name> read"
	  * global writes -> "<name> = <value>"
	  * function calls-> "<name>(<args>)" with compact value formatting
	  * missing globals (nil fallthrough) -> MISSING markers

	Also exposes envlog.dump() to print the accumulated trace (call it
	from a pcall handler or at the end of the run).
]]

local envlog = {}

-- compact value formatter --------------------------------------------------

local function typestr(v)
	local ok, t = pcall(function() return typeof and typeof(v) or type(v) end)
	return ok and t or type(v)
end

local function fmt(v, seen, depth)
	seen = seen or {}
	depth = depth or 0
	local t = typestr(v)
	if t == "string" then
		if #v > 80 then
			return string.format("%q", v:sub(1, 77)) .. "..."
		end
		return string.format("%q", v)
	elseif t == "number" then
		return tostring(v)
	elseif t == "boolean" or t == "nil" then
		return tostring(v)
	elseif t == "table" then
		if seen[v] then return "<cyclic>" end
		if depth > 2 then return "{...}" end
		seen[v] = true
		local parts, n = {}, 0
		for k, val in pairs(v) do
			n = n + 1
			if n > 6 then
				table.insert(parts, "...")
				break
			end
			local ks = type(k) == "string" and k or ("[" .. tostring(k) .. "]")
			table.insert(parts, ks .. "=" .. fmt(val, seen, depth + 1))
		end
		return "{" .. table.concat(parts, ", ") .. ")"
	elseif t == "function" then
		return "<function>"
	end
	return "<" .. t .. ">"
end
envlog.fmt = fmt

-- trace wrap ---------------------------------------------------------------

-- wrap(env, logfn, opts) -> logged environment (metatable-based).
--   logfn(line) is called for every traced event.
--   opts.call_depth — how deep to wrap nested tables (default 1)
function envlog.wrap(env, logfn, opts)
	opts = opts or {}
	local maxdepth = opts.call_depth or 1
	local seen_wrapped = {}

	local function wrap_table(t, path, depth)
		if seen_wrapped[t] then return t end
		seen_wrapped[t] = true
		local proxy = {}
		setmetatable(proxy, {
			__index = function(_, k)
				local v = rawget(t, k)
				if v == nil then
					logfn(path .. tostring(k) .. " read (nil)")
					return nil
				end
				logfn(path .. tostring(k) .. " read -> " .. fmt(v, {}, 1))
				if depth < maxdepth and type(v) == "table" then
					local wrapped = wrap_table(v, path .. tostring(k) .. ".", depth + 1)
					return wrapped
				end
				return v
			end,
			__newindex = function(_, k, v)
				logfn(path .. tostring(k) .. " = " .. fmt(v, {}, 1))
				rawset(t, k, v)
			end,
			__call = function(_, ...)
				local args = {}
				for i = 1, select("#", ...) do
					args[i] = fmt((select(i, ...)), {}, 1)
				end
				logfn(path:sub(1, -2) .. "(" .. table.concat(args, ", ") .. ")")
				local fn = rawget(t, "__call_fn")
				if fn then return fn(...) end
				return nil
			end,
		})
		return proxy
	end

	-- wrap function values so calls are traced with args
	local function wrap_fn(name, fn)
		if type(fn) ~= "function" then return fn end
		return function(...)
			local args = {}
			for i = 1, select("#", ...) do
				args[i] = fmt((select(i, ...)), {}, 1)
			end
			logfn(name .. "(" .. table.concat(args, ", ") .. ")")
			local results = table.pack(fn(...))
			local rets = {}
			for i = 1, results.n do
				rets[i] = fmt(results[i], {}, 1)
			end
			if results.n > 0 then
				logfn("  -> " .. table.concat(rets, ", "))
			end
			return unpack(results, 1, results.n)
		end
	end

	local logged = {}
	local real = {}

	for k, v in pairs(env) do
		real[k] = v
		if type(v) == "function" then
			-- functions are wrapped so their calls are traced
			logged[k] = wrap_fn(tostring(k), v)
		else
			logged[k] = v
		end
	end

	setmetatable(logged, {
		__index = function(_, k)
			local v = real[k]
			logfn(tostring(k) .. (v == nil and " MISSING" or
				" read -> " .. fmt(v, {}, 1)))
			return v
		end,
		__newindex = function(_, k, v)
			logfn(tostring(k) .. " = " .. fmt(v, {}, 1))
			real[k] = v
		end,
	})

	return logged
end

-- trace buffer helpers -------------------------------------------------------

local buffer_trace = {}
local function default_log(line)
	table.insert(buffer_trace, line)
	print(line)
end

-- logf() returns the default print+buffer logger
function envlog.logf()
	return default_log
end

-- dump() returns the accumulated default-buffer trace
function envlog.dump()
	return table.concat(buffer_trace, "\n")
end

return envlog
