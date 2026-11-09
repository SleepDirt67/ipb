stalker_ids = {sound_script = 1000}

utils = {
    cfg_get_bool = function(ini, section, field, _, _, default)
        local value = ini[section][field]
        if value == nil then return default end
        return value
    end,
    cfg_get_string = function(ini, section, field, _, _, _, default)
        return ini[section][field] or default
    end,
    cfg_get_number = function(ini, section, field, _, _, default)
        return ini[section][field] or default
    end,
}
function parse_names(value)
    local result = {}
    for name in value:gmatch("[^ ,]+") do result[#result + 1] = name end
    return result
end
function character_community() return "stalker" end
function abort(...) error(string.format(...)) end

local env = setmetatable({}, {__index = _G})
local source = assert(loadfile(voice_file))
setfenv(source, env)
source()

local order = {}
for _, row in ipairs(assert(loadfile(themes_file))()) do
    local name, path, prefix, combat = unpack(row)
    order[#order + 1] = name
    env.theme[name] = env.npc_sound({[name] = {
        path = path, npc_prefix = prefix, group_snd = false,
        is_combat_sound = combat,
    }}, name)
end

local assigned = {}
local nextTheme = 0
for name in pairs(env.theme) do
    assigned[name] = nextTheme
    nextTheme = nextTheme + 1
end

function run_cohort()
    local ordinal = 0
    for actor, profile in ipairs({0, 1, 0, 2, 3, 3, 0, 4, 1}) do
        local npc = game_object()
        npc:set_id(actor)
        local prefix = "characters_voice\\cohort_" .. profile .. "\\"
        npc:sound_prefix(prefix)
        with_spawn(npc, env.init_npc_sound, false)
        assert(npc:sound_prefix() == prefix)
        local items = actor <= 2 and 4 or 3
        for i = 1, items do
            read_cohort_item("fixture_item_" .. ordinal .. ".dat")
            ordinal = ordinal + 1
        end
    end
    assert(ordinal == 29)
end

function compare_cohort()
    local sum, count = 0, 0
    for _, name in ipairs(order) do
        local entry = env.theme[name]
        for id = 1, 9 do
            local data, paths = entry.npc[id], entry.sound_path[id]
            assert(data.max == 2 and #paths == 3)
            assert(data.id == 11000 + (id - 1) * 569 + assigned[name])
            assert(paths[1]:sub(-1) == "1" and paths[3]:sub(-1) == "3")
            assert(entry.can_play_sound[id])
            sum = sum + data.id
            count = count + 1
        end
    end
    assert(count == 569 * 9)
    return sum
end
