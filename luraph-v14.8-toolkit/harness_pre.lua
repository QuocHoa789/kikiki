--!nonstrict
-- Luraph v14.8 sandbox harness (pre-part): stubs + tracing helpers.
-- Combined by build_combined.py with the protected source and post-part.


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
    -- print immediately so a timeout-kill still captures partial traces
    print(string.rep("  ", depth) .. line)
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
local lookup_log = {}

-- IR dump: called by injected LPH_DUMP(...) right after deserialization.
-- Prints a line-based structural dump of every visible table so the
-- execution data (constants / instruction arrays / prototypes) can be
-- captured without running the payload.
local dump_lines = {}
local dump_seen = {}

local function tkind(v)
    local t = type(v)
    if t ~= "table" then return t end
    local n = 0
    local numkeys = 0
    local strkeys = 0
    for k in pairs(v) do
        n = n + 1
        if type(k) == "number" then numkeys = numkeys + 1 end
        if type(k) == "string" then strkeys = strkeys + 1 end
        if n > 200 then break end
    end
    if numkeys == n and n > 0 then
        -- homogeneous array detection
        local allnum, allstr, alltbl = 0, 0, 0
        local c = 0
        for i, val in pairs(v) do
            c = c + 1
            local vt = type(val)
            if vt == "number" then allnum = allnum + 1 end
            if vt == "string" then allstr = allstr + 1 end
            if vt == "table" then alltbl = alltbl + 1 end
            if c >= 50 then break end
        end
        if c > 0 and allnum == c then return "array:num"
        elseif c > 0 and allstr == c then return "array:str"
        elseif c > 0 and alltbl == c then return "array:tbl" end
        return "array:mixed"
    end
    if n == 0 then return "empty" end
    return "table"
end

local function dump_table(name, t, depth)
    if depth > 4 or dump_seen[t] then return end
    dump_seen[t] = true
    local kind = tkind(t)
    table.insert(dump_lines,
        string.format("T %s %s %d %d", name, kind, depth, #t))
    if kind == "array:num" then
        local parts = {}
        local n = 0
        local c = 0
        for i, val in pairs(t) do
            c = c + 1
            if c > 120 then table.insert(parts, "...") break end
            n = n + 1
            parts[n] = tostring(i) .. ":" .. tostring(val)
        end
        table.insert(dump_lines, "V " .. name .. " " .. table.concat(parts, " "))
    elseif kind == "array:str" then
        local n = 0
        for i = 1, math.min(#t, 40) do
            n = n + 1
            local s = tostring(t[i])
            if #s > 90 then s = s:sub(1, 87) .. "..." end
            table.insert(dump_lines, string.format("S %s %d %s", name, i, s))
        end
        if #t > 40 then
            table.insert(dump_lines, "S " .. name .. " - (+" .. (#t - 40) .. " more)")
        end
    elseif kind == "array:tbl" or kind == "array:mixed" or kind == "table" then
        local c = 0
        for k, v in pairs(t) do
            c = c + 1
            if c > 40 then
                table.insert(dump_lines, "K " .. name .. " - (more keys)")
                break
            end
            local kt = type(k)
            if type(v) == "table" then
                table.insert(dump_lines,
                    string.format("K %s %s -> %s", name,
                        kt == "string" and k or ("[" .. tostring(k) .. "]"),
                        tkind(v)))
                if depth < 3 and kt ~= "string" or depth < 3 then
                    dump_table(name .. "." .. tostring(k), v, depth + 1)
                end
            else
                local vs = tostring(v)
                if #vs > 80 then vs = vs:sub(1, 77) .. "..." end
                table.insert(dump_lines,
                    string.format("K %s %s = %s %s", name,
                        kt == "string" and k or ("[" .. tostring(k) .. "]"),
                        type(v), vs))
            end
        end
    end
end

LPH_DUMP = function(...)
    dump_lines = {}
    dump_seen = {}
    for i = 1, select("#", ...) do
        local name = "arg" .. i
        local v = (select(i, ...))
        if type(v) == "table" then
            dump_table(name, v, 0)
        else
            table.insert(dump_lines,
                "T " .. name .. " " .. type(v) .. " 0 0")
        end
    end
    print("=== LPH_DUMP_BEGIN ===")
    print(table.concat(dump_lines, "\n"))
    print("=== LPH_DUMP_END ===")
end

-- expose the dumper to the protected script's environment
env.LPH_DUMP = LPH_DUMP

-- full access logger: move every global behind an __index pass-through so
-- we see the exact lookup sequence (including successful ones)
local real_globals = {}
for k, v in pairs(env) do
    real_globals[k] = v
    env[k] = nil
end
setmetatable(env, {
    __index = function(t, k)
        table.insert(lookup_log, tostring(k))
        missing[tostring(k)] = (missing[tostring(k)] or 0) + 1
        return real_globals[k]
    end,
    __newindex = function(t, k, v)
        real_globals[k] = v
    end,
})

