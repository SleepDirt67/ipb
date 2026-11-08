namespace SpawnVoice
{
int ApplyImpl(lua_State* L)
{
    // A rejection must happen before registering a collection. Lua then
    // uses the original path, including any installed replacements.
    constexpr int npc = 1, getFs = 2, pathArg = 3, limitArg = 4, typeArg = 5,
        combatArg = 6, state = 7, paths = 8;
    u32 limit, type, id;
    if (lua_gettop(L) != paths || lua_gethook(L) || lua_type(L, npc) != LUA_TUSERDATA ||
        lua_objlen(L, npc) < sizeof(luabind::detail::object_rep) ||
        !luabind::detail::is_class_object(L, npc) ||
        lua_type(L, pathArg) != LUA_TSTRING || !ReadUnsigned(L, limitArg, limit) || limit != 64 ||
        !ReadUnsigned(L, typeArg, type) || type != SOUND_TYPE_TALKING ||
        lua_type(L, combatArg) != LUA_TBOOLEAN || !PlainTable(L, state) || !PlainTable(L, paths))
        return 0;
    lua_pushliteral(L, "id");
    lua_rawget(L, state);
    const bool validId = ReadUnsigned(L, -1, id);
    lua_pop(L, 1);
    if (!validId)
        return 0;

    lua_getfield(L, LUA_REGISTRYINDEX, npcKey);
    const int nativeNpc = lua_gettop(L);
    lua_getfield(L, LUA_REGISTRYINDEX, fsKey);
    const int nativeFs = lua_gettop(L);
    if (!lua_istable(L, nativeNpc) || !lua_istable(L, nativeFs))
        return 0;
    lua_getfield(L, nativeNpc, "class");
    auto* npcClass = static_cast<luabind::detail::class_rep*>(lua_touserdata(L, -1));
    lua_pop(L, 1);
    auto* wrapper = static_cast<luabind::detail::object_rep*>(lua_touserdata(L, npc));
    if (!npcClass || wrapper->crep() != npcClass || !wrapper->ptr())
        return 0;

    const bool combat = lua_toboolean(L, combatArg) != 0;
    if (!SameMember(L, npc, nativeNpc, combat ? "add_combat_sound" : "add_sound") ||
        !SameMember(L, npc, nativeNpc, "sound_prefix"))
        return 0;
    lua_getfield(L, nativeFs, "getFS");
    const bool sameGetFs = lua_iscfunction(L, -1) && lua_rawequal(L, -1, getFs);
    lua_pop(L, 1);
    if (!sameGetFs)
        return 0;
    lua_getfield(L, nativeFs, "class");
    auto* fsClass = static_cast<luabind::detail::class_rep*>(lua_touserdata(L, -1));
    lua_pop(L, 1);
    if (!fsClass)
        return 0;
    fsClass->get_table(L);
    const bool sameExist = SameMember(L, lua_gettop(L), nativeFs, "exist");
    lua_pop(L, 1);
    if (!sameExist)
        return 0;

    size_t length = 0;
    const char* path = lua_tolstring(L, pathArg, &length);
    if (length != std::strlen(path) || !length || length > 240)
        return 0;
    auto& object = *static_cast<CScriptGameObject*>(wrapper->ptr());
    if (!object.object().cast_stalker())
        return 0;
    const auto admitted = Scope::Prepared(&object.object());
    if (!admitted || FS.acquire_spawn_voice_catalogue().get() != admitted.get())
        return 0;
    const char* prefix = object.sound_prefix();
    if (!prefix || std::strlen(prefix) + length > 240)
        return 0;
    std::string base(prefix);
    base.append(path, length);
    int count = FS.prepared_spawn_voice_count(base.c_str());
    if (count == -2)
        return 0;

    const auto added = combat ? object.add_combat_sound(path, limit, SOUND_TYPE_TALKING, 2, 1, id, "bip01_head") :
        object.add_sound(path, limit, SOUND_TYPE_TALKING, 2, 1, id);
    lua_pushliteral(L, "max");
    lua_pushnumber(L, static_cast<lua_Number>(added) - 1);
    lua_rawset(L, state);

    // Keep names and the stock single-vs-numbered precedence even if a
    // synchronous resource hook invalidated the index during registration.
    const char* currentPrefix = object.sound_prefix();
    if (currentPrefix)
    {
        base.assign(currentPrefix);
        base.append(path, length);
    }
    // Emit the detached path plan when its spelling matches Lua exactly.
    // Reacquire after registration so a changed VFS root or revision cannot
    // publish old filenames. No VFS lock is held across a Lua allocation.
    const auto catalogue = FS.acquire_spawn_voice_catalogue();
    if (catalogue)
    {
        if (const auto* names = catalogue->Paths(base))
        {
            for (size_t i = 0; i < names->size(); ++i)
            {
                const auto& name = (*names)[i];
                lua_pushlstring(L, name.data(), name.size());
                lua_rawseti(L, paths, static_cast<int>(i + 1));
            }
            lua_pushboolean(L, 1);
            return 1;
        }
    }
    count = FS.prepared_spawn_voice_count(base.c_str());
    if (count == -2)
    {
        if (FS.exist("$game_sounds$", (base + ".ogg").c_str()))
            count = -1;
        else
        {
            count = 0;
            while (FS.exist("$game_sounds$", (base + std::to_string(count + 1) + ".ogg").c_str()))
                ++count;
        }
    }
    if (count == -1)
    {
        lua_pushlstring(L, base.data(), base.size());
        lua_rawseti(L, paths, 1);
    }
    for (int i = 1; i <= count; ++i)
    {
        const auto name = base + std::to_string(i);
        lua_pushlstring(L, name.data(), name.size());
        lua_rawseti(L, paths, i);
    }

    lua_pushboolean(L, 1);
    return 1;
}

int Apply(lua_State* L)
{
    try
    {
        return ApplyImpl(L);
    }
    catch (const std::exception& e)
    {
        lua_pushstring(L, e.what());
    }
    catch (...)
    {
        lua_pushliteral(L, "NPC voice registration failed");
    }
    return lua_error(L);
}

void RegisterNativeApply(lua_State* L)
{
    const char* admission = std::getenv("IXRAY_SPAWN_PREPARE");
    const char* disabled = std::getenv("IXRAY_SPAWN_VOICE_PLAN");
    if (!admission || xr_strcmp(admission, "1") != 0 ||
        (disabled && xr_strcmp(disabled, "0") == 0))
        return;
    static constexpr const char* methods[] = {"sound_prefix", "add_sound", "add_combat_sound"};
    Capture(L, npcKey, "game_object", methods, std::size(methods));
    lua_pushcfunction(L, Apply);
    lua_setglobal(L, "ixray_apply_spawn_voice");
}
}
