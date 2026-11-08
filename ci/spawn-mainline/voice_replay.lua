stalker_ids = {sound_script = 1000}
snd_type = {talk = 0x4000}
native_applied = 0
local native = ixray_apply_spawn_voice
ixray_apply_spawn_voice = function(...)
    local applied = native(...)
    if applied then native_applied = native_applied + 1 end
    return applied
end

utils = {
    cfg_get_bool = function(ini, section, name, _, _, default)
        local value = ini[section][name]
        if value == nil then return default end
        return value
    end,
    cfg_get_string = function(ini, section, name, _, _, _, default)
        return ini[section][name] or default
    end,
    cfg_get_number = function(ini, section, name, _, _, default)
        return ini[section][name] or default
    end
}

function parse_names(s)
    local result = {}
    for word in s:gmatch("[^ ,]+") do result[#result + 1] = word end
    return result
end
function character_community() return "stalker" end
function abort(...) error(string.format(...)) end

function replay_spawn()
    local fixtures = {"line", "single", "line2"}
    local order = {}
    for i = 1, 48 do
        local name = string.format("theme%02d", i)
        order[#order + 1] = name
        local config = {}
        config[name] = {
            path = fixtures[(i % 3) + 1],
            npc_prefix = i % 4 ~= 0,
            group_snd = i % 2 == 0,
            is_combat_sound = i % 7 == 0,
            avail_communities = i % 6 == 0 and "army" or "stalker",
        }
        theme[name] = npc_sound(config, name)
    end
    if replay_mode == "getfs_override" then
        local old = getFS
        getFS = function() return old() end
    elseif replay_mode == "fs_override" then
        local old = getFS().exist
        FS.exist = function(...) return old(...) end
    elseif replay_mode == "debug_hook" then
        debug.sethook(function() end, "c")
    end

    local ordinal, total = {}, 0
    for name, entry in pairs(theme) do
        if entry.avail_communities.stalker then
            ordinal[name], total = total, total + 1
        end
    end
    for i = 1, 24 do
        local npc = game_object()
        npc:set_id(i)
        if replay_mode == "npc_override" then
            local old = npc.other_add_sound
            npc.add_sound = old
            local combat = npc.add_combat_sound
            npc.add_combat_sound = function(...) return combat(...) end
        end
        local expected = "characters_voice\\model\\"
        if replay_mode == "uppercase_prefix" then
            expected = "CHARACTERS_VOICE\\MODEL\\"
            npc:sound_prefix(expected)
        end
        with_spawn(npc, init_npc_sound, replay_mode == "foreign_scope")
        assert(npc:sound_prefix() == expected)
    end
    if replay_mode == "debug_hook" then debug.sethook() end

    local values = {}
    for _, name in ipairs(order) do
        local entry = theme[name]
        values[#values + 1] = tostring(entry.can_play_group_sound)
        for i = 1, 24 do
            local state, paths = entry.npc[i], entry.sound_path[i]
            if state then
                assert(state.id == 11000 + (i - 1) * total + ordinal[name])
                values[#values + 1] = table.concat({state.max,
                    tostring(entry.can_play_sound[i]), table.concat(paths, ",")}, ":")
            end
        end
    end
    replay_result = table.concat(values, "\n")
end
