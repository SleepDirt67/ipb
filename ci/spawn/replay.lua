-- Both namespaces execute the actual stock CoP parser, scheme readers and evaluator.
-- The host substitutes only game effects and the INI and clock APIs.
string.gfind = string.gfind or string.gmatch
local function equal(left, right)
    if type(left) ~= type(right) then return false end
    if type(left) ~= 'table' then
        return left == right and (left ~= 0 or 1 / left == 1 / right)
    end
    for key, value in pairs(left) do if not equal(value, right[key]) then return false end end
    for key in pairs(right) do if left[key] == nil then return false end end
    return true
end

local function environment(source)
    local e = setmetatable({}, {__index = _G})
    e.abort = function(...) error(string.format(...)) end
    e.printf = function() end
    local loaded = assert(loadstring(source, '@xr_logic'))
    setfenv(loaded, e)()
    return e
end

local baseline = environment(stock)
local candidate = environment(prepared)
for _, value in ipairs(corpus) do
    local a, old = pcall(baseline.parse_condlist, {name=function() return 'fixture' end}, 's', 'f', value)
    local b, new = pcall(candidate.parse_condlist, {name=function() return 'fixture' end}, 's', 'f', value)
    assert(a == b and (not a or equal(old, new)), value)
    if a and new[1] then
        new[1].section = 'mutated instance'
        new[1].infop_check[99] = {name='instance only'}
        local fresh = candidate.parse_condlist(nil, nil, nil, value)
        assert(equal(old, fresh), 'compiled template leaked mutable state')
    end
end

local function parse_params(s)
    local result = {}
    for value in string.gfind(s, '%s*([^|]+)%s*') do result[#result+1] = value end
    return result
end
local function make_ini(rows, mode, stats)
    local ini = newproxy(true)
    getmetatable(ini).__index = {
        section_exist = function() return true end,
        line_count = function() return #rows end,
        r_line = function(_, _, index)
            stats.reads = stats.reads + 1
            local row = rows[index + 1]
            return row ~= nil, row and row[1] or '', row and row[2] or ''
        end,
        ixray_next_switch_key = mode == 'unsupported' and nil or function(_, _, prefix, first, finish)
            if mode == 'fallback' then return -2 end
            local l, r = first + 1, finish + 1
            while l < r do
                local mid = math.floor((l + r) / 2)
                if rows[mid][1] < prefix then l = mid + 1 else r = mid end
            end
            for i=l,finish do
                local key = rows[i][1]
                if key:sub(1, #prefix) ~= prefix then break end
                if key:find('^'..prefix..'%d*$') then return i-1,key end
            end
            return -1
        end
    }
    if mode == 'unsupported' then getmetatable(ini).__index.ixray_next_switch_key = nil end
    local values = {}
    for _, row in ipairs(rows) do values[row[1]] = row[2] end
    return ini, values
end

-- Vary stock resource names with the actual condition strings extracted from
-- the stock configs. Include rule ordering traps and a late dynamic value.
local rows = {}
for i=1,42 do rows[#rows+1] = {('path_walk_%02d'):format(i), 'path'} end
local custom = {
    {'on_actor_dist_ge', '8|{+known}walk, idle'},
    {'on_actor_dist_ge_nvis1', '8|{~100}walk, idle'},
    {'on_actor_inside2', '{+known}walk %+marked%'},
    {'on_info', '{+known =gate(a:1) ~100}walk %=effect(a:1) +marked%,idle'},
    {'on_info10', '{+missing}idle,walk'},
    {'on_info2', '{~100}walk %=effect(b:2)%'},
    {'on_infoz', 'must_not_match'},
    {'on_timer3', '30|{+known}walk, nil'},
    {'on_npc_in_zone', 'quest_parent|zone_a|{+known}walk'},
}
for _, row in ipairs(custom) do rows[#rows+1] = row end
table.sort(rows, function(a,b) return a[1]<b[1] end)

local stockInputs = {}
for i=1,#corpus,math.max(1, math.floor(#corpus/120)) do stockInputs[#stockInputs+1] = corpus[i] end
local function batch(env, mode, n, audit)
    local effects, state, events = {}, {}, {}
    local reads = {reads=0}
    local ini, values = make_ini(rows, mode, reads)
    env.utils = {parse_params=parse_params, cfg_get_string=function(_, _, key) return values[key] end}
    env.get_story_object_id = function(id) return id end
    env.alife = function() return {object=function(_, id)
        if audit then effects[#effects+1] = 'story:' .. id end
        return state[1]
    end} end
    local actor = {give_info_portion=function(_, id) if audit then effects[#effects+1]='give:'..id end end,
                   disable_info_portion=function(_, id) if audit then effects[#effects+1]='disable:'..id end end}
    env.db = {actor=actor}
    env.has_alife_info = function(id)
        if audit then effects[#effects+1] = 'read:'..id end
        return id == 'known'
    end
    env.give_info = function(id) if audit then effects[#effects+1]='give:'..id end end
    env.disable_info = function(id) if audit then effects[#effects+1]='disable:'..id end end
    env.xr_conditions = {gate=function(_, npc, params)
        assert(params[1]=='a' and params[2]==1)
        if audit then effects[#effects+1]='gate:'..npc.id end
        params[1]='modified by callback'
        return true
    end}
    env.xr_effects = {effect=function(_, npc, params)
        assert(params[1]=='a' or params[1]=='b')
        if audit then effects[#effects+1]='effect:'..npc.id..':'..params[1] end
        params[1]='modified by callback'
    end}
    for i=1,n do
        local npc={id=i,name=function() return 'fixture' end}
        state[i]=npc  -- host model of original publication
        if audit then events[#events+1]='publish:'..i end
        local result = env.cfg_get_switch_conditions(ini,'logic',npc)
        if i % 4 == 0 then
            assert(state[i-1])
            if audit then events[#events+1]='attach:'..i..':'..(i-1) end
        end
        local branch = result[3] -- callback/params plus RNG in first on_info rule
        npc.active = env.pick_section_from_condlist(actor,npc,branch.condlist)
        -- Stock-derived condition programs. Parsing only, since actual world
        -- callbacks for these conditions need the full game.
        for offset=1,8 do
            local text = stockInputs[1+(i*8+offset)%#stockInputs]
            npc.last = env.parse_condlist(npc, 'dynamic', 'active', text)
        end
        if audit then events[#events+1]='return:'..i..':'..tostring(npc.active) end
        if i==13 and audit then events[#events+1]='script-spawn:'..i end
    end
    local serialized={}
    for i, npc in ipairs(state) do serialized[i]=i..':'..tostring(npc.active) end
    return table.concat(effects,'|'), table.concat(events,'|'), table.concat(serialized,'|'), reads.reads
end

for _, mode in ipairs({'batch','fallback','unsupported'}) do
    math.randomseed(881)
    local a,b,c,old = batch(baseline,mode,28,true)
    local next_random = math.random(1000)
    math.randomseed(881)
    local x,y,z,new = batch(candidate,mode,28,true)
    assert(a==x and b==y and c==z and math.random(1000)==next_random, mode)
    assert(a:find('gate:1',1,true) and a:find('effect:1:a',1,true) and a:find('give:marked',1,true), a:sub(1,220))
    if mode=='batch' then assert(old > 0 and new==0) else assert(new==old) end
end

local function measure(env)
    collectgarbage('collect')
    math.randomseed(19)
    local start=os.clock()
    local reads
    for _=1,100 do _,_,_,reads = batch(env,'batch',28,false) end
    return (os.clock()-start) * 10, reads
end
local timings = {}
for i=1,7 do
    local old, new, oldReads, newReads
    if i%2==1 then
        old,oldReads=measure(baseline); new,newReads=measure(candidate)
    else
        new,newReads=measure(candidate); old,oldReads=measure(baseline)
    end
    timings[#timings+1]=string.format('%.5f/%.5f',old,new)
end
return 'PASS corpus='..#corpus..' packages of 28, ordered host effects and RNG, ms/pair samples '..table.concat(timings, ',')
