--!nonstrict
-- Luraph v14.8 sandbox harness: runs a protected script with a stubbed
-- Roblox environment and traces every global lookup and API call.
-- Usage: luau run_sandbox.lua <protected.lua> <trace_out.txt>

local input = ...
local outfile = select(2, ...)

if not input or not outfile then
    print("usage: luau run_sandbox.lua <protected.lua> <trace.txt>")
    return
end
if not input or not outfile then
    print("usage: luau run_sandbox.lua -a <protected.lua> <trace.txt>")
    return
end

local trace = {}
local depth = 0

local function fmt(v, seen)
    local t = typeof and typeof(v) or type(v)
    if t == "string" then
        if #v > 120 then return string.format("%q", v:sub(1, 117)) .. "..." end
        return string.format("%q", v)
    elseif t == "number" then
        return tostring(v)
    elseif t == "boolean" or t == "nil" then
        return tostring(v)
    elseif t == "table" then
        if seen[v] then return "<cyclic>" end
        seen[v] = true
        local parts = {}
        local n = 0
        for k, val in pairs(v) do
            n = n + 1
            if n > 8 then table.insert(parts, "...") break end
            table.insert(parts, tostring(k) .. "=" .. fmt(val, seen))
        end
        return "{" .. table.concat(parts, ", ") .. "}"
    end
    return "<" .. t .. ">"
end

local function log(line)
    table.insert(trace, string.rep("  ", depth) .. line)
end

-- call-tracing wrapper for stub functions
local function traced_stub(name, fn)
    return function(...)
        local args = {}
        for i = 1, select("#", ...) do
            args[i] = fmt((select(i, ...)), {})
        end
        log(name .. "(" .. table.concat(args, ", ") .. ")")
        depth = depth + 1
        local results = table.pack(fn(...))
        depth = depth - 1
        local rets = {}
        for i = 1, results.n do rets[i] = fmt(results[i], {}) end
        if results.n > 0 then
            log("-> " .. table.concat(rets, ", "))
        end
        return unpack(results, 1, results.n)
    end
end

local function return_stub(what)
    return function(...)
        local args = {}
        for i = 1, select("#", ...) do
            args[i] = fmt((select(i, ...)), {})
        end
        log(what .. "(" .. table.concat(args, ", ") .. ")")
        return nil
    end
end

-- ---------------------------------------------------------------------------
-- Stub Roblox environment
-- ---------------------------------------------------------------------------

local services = {}

local function make_service(name)
    local svc = {}
    local mt = {
        __index = function(t, k)
            local key = tostring(k)
            if services[name .. "." .. key] then
                return services[name .. "." .. key]
            end
            -- auto-member: nested service or method stub
            local sub = make_service(name .. "." .. key)
            services[name .. "." .. key] = sub
            rawset(t, key, sub)
            return sub
        end,
        __call = function(t, ...)
            local args = {}
            for i = 1, select("#", ...) do
                args[i] = fmt((select(i, ...)), {})
            end
            log(name .. "(...)" .. " called with (" .. table.concat(args, ", ") .. ")")
            return make_service(name .. "()")
        end,
        __newindex = function(t, k, v)
            log(name .. "." .. tostring(k) .. " = " .. fmt(v, {}))
            rawset(t, k, v)
        end,
    }
    return setmetatable(svc, mt)
end

local game = make_service("game")

local shared_stub = {}
setmetatable(shared_stub, {
    __index = function(t, k)
        return return_stub("<shared:" .. tostring(k) .. ">")
    end,
    __call = function(t, ...)
        return return_stub("<shared>")
    end,
})

local env = {
    -- Roblox globals
    game = game,
    workspace = make_service("workspace"),
    script = make_service("script"),
    Instance = setmetatable({}, {
        __index = function(t, k)
            local cls = tostring(k)
            return function(props, parent)
                log("Instance.new(\"" .. cls .. "\")")
                return make_service("Instance:" .. cls)
            end
        end,
    }),
    Enum = make_service("Enum"),
    task = make_service("task"),
    shared = shared_stub,
    _G = {},
    print = function(...)
        local args = {}
        for i = 1, select("#", ...) do
            args[i] = fmt((select(i, ...)), {})
        end
        log("print(" .. table.concat(args, ", ") .. ")")
    end,
    warn = function(...)
        local args = {}
        for i = 1, select("#", ...) do
            args[i] = fmt((select(i, ...)), {})
        end
        log("warn(" .. table.concat(args, ", ") .. ")")
    end,
    pcall = pcall,
    xpcall = xpcall,
    select = select,
    typeof = typeof,
    type = type,
    tostring = tostring,
    tonumber = tonumber,
    error = error,
    assert = assert,
    unpack = unpack,
    rawset = rawset,
    rawget = rawget,
    rawequal = rawequal,
    setmetatable = setmetatable,
    getmetatable = getmetatable,
    setfenv = setfenv,
    getfenv = getfenv,
    loadstring = loadstring,
    require = return_stub("require"),
    getgenv = function()
        return {}
    end,
    identifyexecutor = function()
        return "sandbox", "1.0"
    end,
    gameLoaded = function()
        return true
    end,
    -- Luau stdlib passthrough
    string = string,
    table = table,
    math = math,
    os = os,
    bit32 = bit32,
    buffer = buffer,
    coroutine = coroutine,
    utf8 = utf8,
    debug = debug,
}

-- missing-global tracker: log any lookup that falls through env
local missing = {}
setmetatable(env, {
    __index = function(t, k)
        missing[tostring(k)] = (missing[tostring(k)] or 0) + 1
        return nil
    end,
})

-- ---------------------------------------------------------------------------
-- Run
-- ---------------------------------------------------------------------------

local f = io and io.open and io.open(input, "r") or nil
local chunk, err
if f then
    local src = f:read("*a")
    f:close()
    chunk, err = loadstring(src, "@" .. input)
else
    -- Luau CLI has no io library; read via require-less trick is impossible,
    -- so the harness expects the source through the command line instead
    chunk, err = nil, "cannot open " .. input
end
if not chunk then
    print("load error: " .. tostring(err))
    return
end

setfenv(chunk, env)

log("=== begin execution: " .. input .. " ===")

local ok, run_err = pcall(chunk)
if not ok then
    log("RUNTIME ERROR: " .. tostring(run_err))
end

log("=== end execution ===")

for k, n in pairs(missing) do
    log("MISSING GLOBAL: " .. k .. " (looked up " .. n .. "x)")
end

-- write trace to stdout (shell redirects to file)
print(table.concat(trace, "\n"))
