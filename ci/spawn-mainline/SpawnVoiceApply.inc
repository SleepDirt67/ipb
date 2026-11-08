namespace SpawnVoice
{
bool ReadTalkingType(lua_State* L, int index)
{
    using luabind::detail::class_rep;
    const class_rep* soundType = nullptr;
    if (!PlainTable(L, index))
    {
        if (lua_type(L, index) != LUA_TUSERDATA || lua_objlen(L, index) < sizeof(class_rep) ||
            !lua_getmetatable(L, index))
            return false;
        RawField(L, -1, Index);
        const bool native = lua_tocfunction(L, -1) == class_rep::static_class_gettable;
        lua_pop(L, 2);
        if (!native)
            return false;
        soundType = static_cast<const class_rep*>(lua_touserdata(L, index));
        soundType->get_default_table(L);
        if (!PlainTable(L, -1))
            return false;
        index = lua_gettop(L);
    }

    RawField(L, index, Talk);
    u32 type;
    bool matches = ReadUnsigned(L, -1, type) && type == SOUND_TYPE_TALKING;
    if (soundType && lua_isnil(L, -1))
    {
        const auto& constants = soundType->static_constants();
        const auto talk = constants.find(Keys[Talk - 1]);
        matches = talk != constants.end() && talk->second == SOUND_TYPE_TALKING;
    }
    lua_pop(L, soundType ? 2 : 1);
    return matches;
}

int ApplyImpl(lua_State* L)
{
    // A rejection must happen before registering a collection. Lua then
    // uses the original path, including any installed replacements.
    using luabind::detail::class_rep;
    constexpr int npc = 1, theme = 2, npcIdArg = 3;
    u32 npcId, limit, id;
    if (lua_gettop(L) != npcIdArg || lua_gethook(L) || !ReadUnsigned(L, npcIdArg, npcId) ||
        npcId >= u16(-1) || !lua_checkstack(L, 22))
        return 0;

    const auto* wrapper = ReadWrapper(L, npc, class_rep::gettable_dispatcher);
    if (!wrapper || !wrapper->ptr())
        return 0;
    RawField(L, LUA_REGISTRYINDEX, NpcKey);
    const int nativeNpc = lua_gettop(L);
    if (!PlainTable(L, nativeNpc))
        return 0;
    RawField(L, nativeNpc, Class);
    const bool nativeNpcClass = wrapper->crep() == lua_touserdata(L, -1);
    lua_pop(L, 1);
    if (!nativeNpcClass)
        return 0;
    auto& object = *static_cast<CScriptGameObject*>(wrapper->ptr());
    if (!object.object().cast_stalker())
        return 0;
    const auto admitted = Scope::Prepared(&object.object());
    if (!admitted || FS.acquire_spawn_voice_catalogue().get() != admitted.get())
        return 0;

    // The original function has already assigned its fresh state tables and
    // ID. Only raw per-instance values may be consumed ahead of a Lua effect.
    const auto* sound = ReadWrapper(L, theme, class_rep::lua_class_gettable);
    if (!sound || !sound->get_lua_table().is_valid())
        return 0;
    sound->get_lua_table().get(L);
    const int fields = lua_gettop(L);
    if (!PlainTable(L, fields))
        return 0;
    RawField(L, fields, Combat);
    if (lua_type(L, -1) != LUA_TBOOLEAN)
        return 0;
    const bool combat = lua_toboolean(L, -1) != 0;
    lua_pop(L, 1);
    RawField(L, fields, Path);
    if (lua_type(L, -1) != LUA_TSTRING)
        return 0;
    size_t length = 0;
    const char* path = lua_tolstring(L, -1, &length);
    if (length != std::strlen(path) || !length || length > 240)
        return 0;
    RawField(L, fields, NpcState);
    if (!PlainTable(L, -1))
        return 0;
    lua_rawgeti(L, -1, static_cast<int>(npcId));
    const int state = lua_gettop(L);
    if (!PlainTable(L, state))
        return 0;
    RawField(L, state, Id);
    if (!ReadUnsigned(L, -1, id))
        return 0;
    lua_pop(L, 1);
    RawField(L, fields, SoundPaths);
    if (!PlainTable(L, -1))
        return 0;
    lua_rawgeti(L, -1, static_cast<int>(npcId));
    const int paths = lua_gettop(L);
    if (!PlainTable(L, paths) ||
        !SameMember(L, *wrapper, nativeNpc, combat ? CombatAdd : Add) ||
        !SameMember(L, *wrapper, nativeNpc, Prefix))
        return 0;

    lua_Debug caller{};
    if (!lua_getstack(L, 1, &caller) || !lua_getinfo(L, "f", &caller))
        return 0;
    lua_getfenv(L, -1);
    const int environment = lua_gettop(L);
    if (!lua_istable(L, environment) || !PushGlobal(L, environment, Limit) ||
        !ReadUnsigned(L, -1, limit) || limit != 64)
        return 0;
    lua_pop(L, 1);
    if (!PushGlobal(L, environment, SoundType) || !ReadTalkingType(L, lua_gettop(L)))
        return 0;
    lua_pop(L, 1);

    RawField(L, LUA_REGISTRYINDEX, FsKey);
    const int nativeFs = lua_gettop(L);
    if (!PlainTable(L, nativeFs) || !PushGlobal(L, environment, GetFs))
        return 0;
    RawField(L, nativeFs, GetFs);
    const bool sameGetFs = lua_iscfunction(L, -1) && lua_rawequal(L, -1, -2);
    lua_pop(L, 2);
    if (!sameGetFs)
        return 0;
    RawField(L, nativeFs, Class);
    const auto* fsClass = static_cast<const class_rep*>(lua_touserdata(L, -1));
    lua_pop(L, 1);
    if (!fsClass)
        return 0;
    fsClass->get_table(L);
    if (!PlainTable(L, -1))
        return 0;
    RawField(L, -1, Exist);
    RawField(L, nativeFs, Exist);
    const bool sameExist = lua_iscfunction(L, -1) && lua_rawequal(L, -1, -2);
    lua_pop(L, 2);
    if (!sameExist)
        return 0;
    RawField(L, -1, VariantCount);
    RawField(L, nativeFs, VariantCount);
    const bool sameCount = lua_iscfunction(L, -1) && lua_rawequal(L, -1, -2);
    lua_pop(L, 3);
    if (!sameCount)
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
    lua_pushvalue(L, lua_upvalueindex(Max));
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
            Scope::Mark(true);
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

    Scope::Mark(false);
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
    for (const auto* key : Keys)
        lua_pushstring(L, key);
    lua_pushcclosure(L, Apply, KeyCount);
    lua_setglobal(L, "ixray_apply_spawn_voice");
}
}
