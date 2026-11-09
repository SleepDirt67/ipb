local function digest(events)
    local result = 7
    for i = 1, #events do
        result = (result * 997 + events[i]) % 1000000007
    end
    return result
end

-- The event log, weak references and resurrection must agree with the original VM.
collectgarbage("stop")
local weak_keys = setmetatable({}, {__mode = "k"})
local weak_values = setmetatable({}, {__mode = "v"})
local alive, saved, events = {}, {}, {}
local proxy = newproxy(true)
local mt = getmetatable(proxy)
mt.__gc = function(obj)
    local id = weak_keys[obj]
    if not id then return end
    events[#events + 1] = id
    if id % 19 == 0 then saved[#saved + 1] = obj end
    if id % 41 == 0 then
        local extra = newproxy()
        weak_values[-id] = extra
    end
end

local function add(id)
    local obj = newproxy(proxy)
    weak_keys[obj] = id
    weak_values[id] = obj
    alive[id] = obj
end

local function checkpoint(round, limit)
    local live_digest = 0
    for id = 1, limit do
        if weak_values[id] then live_digest = (live_digest * 137 + id) % 1000000007 end
    end
    print(round, #events, digest(events), #saved, live_digest)
end

for i = 1, 2048 do add(i) end
collectgarbage("collect")
for round = 1, 25 do
    local last = 2048 + round * 111
    for i = last - 110, last do add(i) end
    for i = round, last, 43 + round % 17 do alive[i] = nil end
    if round % 4 == 0 then saved = {} end
    if round % 3 == 0 then
        for i = 1, round * 7 do collectgarbage("step", 2) end
    end
    collectgarbage("collect")
    checkpoint(round, last)
end

-- A metatable can gain its finalizer after userdata allocation.
local late_proxy = newproxy(true)
for i = 1, 333 do alive[-i] = newproxy(late_proxy) end
collectgarbage("collect")
getmetatable(late_proxy).__gc = function() events[#events + 1] = 50000 end
alive, saved = {}, {}
for i = 1, 3 do collectgarbage("collect") end
checkpoint(26, 5000)
