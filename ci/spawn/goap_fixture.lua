local stock_path, prepared_path = ...
local stock_environment = setmetatable({}, {__index = _G})
local prepared_environment = setmetatable({}, {__index = _G})
setfenv(assert(loadfile(stock_path)), stock_environment)()
setfenv(assert(loadfile(prepared_path)), prepared_environment)()

local apply = ixray_apply_stock_goap_rules
local applied, missed
local log
local recording
local variant
local function record(...)
    if recording then log[#log + 1] = table.concat({...}, ':') end
end
local function tracked_apply(...)
    local result = apply(...)
    if result then applied = applied + 1 else missed = missed + 1 end
    return result
end

class "fixture_action" (action_base)
function fixture_action:__init() super() end

local function make_module()
    return setmetatable({}, {__index = function(_, key)
        return function(name, st)
            if key == 'animation' then return {anim_callback = function() end} end
            record('construct', key, name, math.random(1, 1000000))
            if key:sub(1, 4) ~= 'act_' then return {name = name} end
            local action = fixture_action()
            if variant == 'override' and key == 'act_state_mgr_weapon_unstrapp' then
                local original = action.add_precondition
                action.add_precondition = function(self, property)
                    record('override')
                    original(self, property)
                end
            elseif variant == 'meta' and key == 'act_state_mgr_weapon_unstrapp' then
                local properties = st.properties
                st.properties = setmetatable({}, {__index = function(_, field)
                    record('index', field)
                    return properties[field]
                end})
            elseif variant == 'modified-id' and key == 'act_state_mgr_weapon_unstrapp' then
                st.properties.locked = 199
            end
            return action
        end
    end})
end
for _, name in ipairs({'state_mgr', 'state_mgr_weapon', 'state_mgr_movement', 'state_mgr_mental',
    'state_mgr_bodystate', 'state_mgr_direction', 'state_mgr_animation', 'state_mgr_animstate', 'state_mgr_smartcover'}) do
    _G[name] = make_module()
end

callback = {script_animation = 7}
function world_state()
    return {add_property = function(self, property) self.property = property end}
end
function action_planner()
    return {
        setup = function(_, npc) record('planner', npc.id) end,
        add_evaluator = function(_, id, evaluator) record('evaluator', id, evaluator.name) end,
        add_action = function(_, id, action)
            if recording then record('publish action', id, action:serialize()) end
        end,
        set_goal_world_state = function(_, goal) assert(goal.property); record('goal') end,
    }
end

local function packet(goap, mixed)
    local online = {}
    for id = 1, 28 do
        local parent = mixed and id % 7 == 0 and id - 1
        if parent then assert(online[parent]); record('parent', parent, id) end
        local npc = {id = id, set_callback = function(self, kind)
            record('callback', self.id, kind, online[self.id] and 1 or 0)
        end}
        if not mixed or id % 7 < 5 then
            goap({}, npc)
        else
            record('script-only', id)
        end
        online[id] = true
        record('publish object', id, math.random(1, 1000000))
    end
end

local function replay(goap, mixed)
    log = {}
    math.randomseed(483113)
    local seed = fixture_rng_seed()
    packet(goap, mixed)
    assert(fixture_rng_seed() == seed, 'native RNG seed changed')
    record('next rng', math.random(1, 1000000))
    return table.concat(log, '\n')
end

recording = true
for _, scenario in ipairs({'stock', 'override', 'meta', 'modified-id', 'constructor'}) do
    variant = scenario
    applied, missed = 0, 0
    local constructor = world_property
    if scenario == 'constructor' then
        _G.world_property = function(...) record('constructor'); return constructor(...) end
    end
    prepared_environment.ixray_apply_stock_goap_rules = tracked_apply
    local stock = replay(stock_environment.goap_graph, true)
    assert(stock == replay(prepared_environment.goap_graph, true), 'ordered effects differ: ' .. scenario)
    _G.world_property = constructor
    if scenario == 'stock' or scenario == 'modified-id' then
        assert(applied > 1000 and missed == 0, 'stock rules did not apply')
    elseif scenario == 'constructor' then
        assert(applied == 0 and missed > 1000, 'changed constructor did not fall back')
    else
        assert(missed > 0, 'changed input did not fall back')
    end
    print(string.format('%s: effects/RNG/registration equal, %d groups applied, %d fallback', scenario, applied, missed))
end

variant, recording = 'stock', false
prepared_environment.ixray_apply_stock_goap_rules = apply
local baseline, candidate = {}, {}
local function measure(goap)
    collectgarbage('collect')
    local start = fixture_clock()
    packet(goap, false)
    return fixture_clock() - start
end
for _ = 1, 8 do
    measure(stock_environment.goap_graph)
    measure(prepared_environment.goap_graph)
end
for i = 1, 41 do
    if i % 2 == 0 then
        baseline[i], candidate[i] = measure(stock_environment.goap_graph), measure(prepared_environment.goap_graph)
    else
        candidate[i], baseline[i] = measure(prepared_environment.goap_graph), measure(stock_environment.goap_graph)
    end
end
table.sort(baseline)
table.sort(candidate)
print(string.format('28 NPC state graphs, 41 paired runs: median %.3f -> %.3f ms; p95 %.3f -> %.3f ms',
    baseline[21], candidate[21], baseline[39], candidate[39]))
