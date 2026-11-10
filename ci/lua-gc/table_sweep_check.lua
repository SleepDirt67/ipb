local ffi = require "ffi"
local finalized = {}
local strong = {}
local weak = setmetatable({}, {__mode = "kv"})
local array = setmetatable({}, {__mode = "v"})
local resurrected
local function make_proxy(id)
    local value = newproxy(true)
    getmetatable(value).__gc = function(self)
        finalized[#finalized + 1] = id
        if id == 64 then resurrected = {self, strong[5]} end
        collectgarbage("step", 4)
    end
    return value
end
collectgarbage("stop")
for i = 1, 512 do
    local t = {id = i}
    t.cycle = t
    if i % 5 == 0 then strong[i] = t end
    weak[t] = {i}
    array[i] = t
end
for i = 1, 64 do make_proxy(i) end
local thread = coroutine.create(function()
    local capture = {1, 2, 3}
    coroutine.yield(function() return capture end)
    capture[4] = 4
    return capture
end)
local ok, open = coroutine.resume(thread)
assert(ok)
collectgarbage("collect")
assert(#finalized == 64 and resurrected[2] == strong[5])
for i = 1, 64 do assert(finalized[i] == 65 - i) end
for i = 1, 512 do
    local value = array[i]
    if i % 5 == 0 then
        assert(value == strong[i] and value.cycle == value and value.id == i)
    else
        assert(value == nil)
    end
end
assert(next(weak) == nil)
local cdata_finalized = {}
for i = 1, 64 do
    ffi.gc(ffi.new("int[1]", i), function(value)
        cdata_finalized[#cdata_finalized + 1] = tonumber(value[0])
    end)
end
for i = 1, 30000 do
    local t = {i, {id = i}}
    if i % 11 == 0 then strong[5].last = t end
    if i % 7 == 0 then collectgarbage("step", i % 51 + 1) end
    if i % 137 == 0 then collectgarbage("collect") end
end
local closed
ok, closed = coroutine.resume(thread)
assert(ok and open() == closed and closed[4] == 4)
resurrected = nil
collectgarbage("collect")
assert(#finalized == 64 and #cdata_finalized == 64)
for i = 1, 64 do assert(cdata_finalized[i] == 65 - i) end
assert(strong[5].last[1] == 29997)
-- Close with a mix of retained tables and newly allocated tables.
for i = 1, 100 do
    strong[i * 5].last = {i}
    collectgarbage("step", 1)
end
print("PASS: weak tables, resurrection, userdata/FFI finalizer order, open upvalues and interleaved collection")
