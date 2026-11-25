setfenv(RUN_PROTECTED, env)

local ok, run_err = xpcall(RUN_PROTECTED, function(e)
    return tostring(e) .. "\n" .. debug.traceback(e, 2)
end)
if not ok then
    log("RUNTIME ERROR: " .. tostring(run_err))
end

log("=== end execution ===")

for k, n in pairs(missing) do
    log("MISSING GLOBAL: " .. k .. " (looked up " .. n .. "x)")
end

log("=== lookup sequence (last 40) ===")
local start = math.max(1, #lookup_log - 39)
for i = start, #lookup_log do
    log(i .. ": " .. lookup_log[i])
end
