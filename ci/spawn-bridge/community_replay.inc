static void CheckCommunity(const char* original, const char* prepared)
{
    auto* L = luaL_newstate();
    Require(L != nullptr, "community Lua state");
    luaL_openlibs(L);
    Register(L);
    Load(L, R"LUA(
        local actors = {}
        for i = 1, 9 do
            actors[i] = game_object()
            actors[i]:set_id(i)
        end

        function verify_community()
            local actor = actors[1]
            with_spawn(actor, function(npc)
                assert(ixray_read_spawn_community(npc, IsStalker, get_clsid, {[42] = true}) == "stalker")
                assert(character_community(npc) == "stalker")
                local original = get_clsid
                get_clsid = function() return 0 end
                assert(character_community(npc) == "monster")
                get_clsid = original
                local old = IsStalker
                IsStalker = function() return false end
                assert(character_community(npc) == "monster")
                IsStalker = old
                npc.character_community = function() return "custom" end
                assert(character_community(npc) == "custom")
                npc.character_community = nil
                local env = getfenv(IsStalker)
                setfenv(IsStalker, {get_clsid = function() return 0 end})
                assert(character_community(npc) == "monster")
                setfenv(IsStalker, env)
                with_spawn(actors[2], function()
                    assert(ixray_read_spawn_community(npc, IsStalker, get_clsid, {[42] = true}) == nil)
                end)
                assert(character_community(npc) == "stalker")
            end)
            assert(ixray_read_spawn_community(actor, IsStalker, get_clsid, {[42] = true}) == nil)
        end

        local function visit(npc)
            for i = 1, 571 do
                if character_community(npc) == "stalker" then
                    tally = tally + 1
                end
            end
        end

        function run_community()
            tally = 0
            for repetition = 1, 60 do
                for _, npc in ipairs(actors) do
                    with_spawn(npc, visit)
                end
            end
            assert(tally == 60 * 9 * 571)
        end
    )LUA", false);
    Load(L, prepared, true);
    Load(L, "verify_community()", false);

    std::vector<double> times[2];
    for (unsigned trial = 0; trial < 11; ++trial)
    {
        for (unsigned order = 0; order < 2; ++order)
        {
            const auto variant = (trial + order) % 2;
            Load(L, variant ? prepared : original, true);
            const auto start = std::chrono::steady_clock::now();
            Load(L, "run_community()", false);
            if (trial)
                times[variant].push_back(std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - start).count() / 60.0);
        }
    }
    for (auto& values : times)
        std::sort(values.begin(), values.end());
    std::printf("Community reads per 9 actors with 571 stock themes: baseline %.4f ms, guarded %.4f ms\n",
        (times[0][4] + times[0][5]) / 2, (times[1][4] + times[1][5]) / 2);
    lua_close(L);
}
