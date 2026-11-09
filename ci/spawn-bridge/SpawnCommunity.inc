// The byte-matched _g.script supplies the stock function identities and its
// current class set. Every call still reads the object's current community.
int ReadCommunity(lua_State* L)
{
    using luabind::detail::class_rep;
    constexpr int npc = 1, isStalker = 2, getClsid = 3, stalkerClasses = 4;
    if (lua_gettop(L) != stalkerClasses || lua_gethook(L) ||
        !PlainTable(L, stalkerClasses) || !lua_checkstack(L, 10))
        return 0;
    const auto* wrapper = ReadWrapper(L, npc, class_rep::gettable_dispatcher);
    if (!wrapper || !wrapper->ptr())
        return 0;

    RawField(L, LUA_REGISTRYINDEX, NpcKey);
    const int nativeNpc = lua_gettop(L);
    if (!PlainTable(L, nativeNpc))
        return 0;
    RawField(L, nativeNpc, Class);
    const bool nativeClass = wrapper->crep() == lua_touserdata(L, -1);
    lua_pop(L, 1);
    if (!nativeClass || !SameMember(L, *wrapper, nativeNpc, Clsid) ||
        !SameMember(L, *wrapper, nativeNpc, Community))
        return 0;

    auto& object = *static_cast<CScriptGameObject*>(wrapper->ptr());
    if (!object.object().cast_stalker() || !Scope::Contains(&object.object()))
        return 0;
    // IsStalker can have a different environment through setfenv.
    lua_getfenv(L, isStalker);
    if (!PushGlobal(L, lua_gettop(L), GetClsid) || !lua_rawequal(L, -1, getClsid))
        return 0;
    lua_rawgeti(L, stalkerClasses, object.clsid());
    if (!lua_isboolean(L, -1) || !lua_toboolean(L, -1))
        return 0;
    const auto* community = object.CharacterCommunity();
    if (!community)
        return 0;
    lua_pushstring(L, community);
    return 1;
}
