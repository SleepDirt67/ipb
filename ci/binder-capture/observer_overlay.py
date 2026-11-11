"""Measure added instrumentation in the existing native voice/registration replay."""
from pathlib import Path
import shutil
import sys

from engine_overlay import change, one

HERE = Path(__file__).resolve().parent


def apply(engine, input_script, output):
    shutil.copyfile(HERE / "ObserverReplay.inc", engine / "BinderObserverReplay.inc")

    def voice(source):
        source = one(source, "class CScriptGameObject\n", '#include "BinderObserverReplay.inc"\n\nclass CScriptGameObject\n')
        source = one(source, "    int code;\n    {",
                     "    int code;\n    ObserverReplay::Scope observer;\n    observer.Enter(L);\n    {")
        source = one(source, "    if (code)\n        return lua_error(L);",
                     "    observer.Leave();\n    if (code)\n        return lua_error(L);")
        source = one(source, "    luaL_openlibs(L);", "    luaL_openlibs(L);\n    ObserverReplay::Configure(L);")
        source = one(source, '    Require(argc == 5, "stock, previous, candidate and replay input");',
                     '    Require(argc == 5 || argc == 6, "stock, previous, candidate and replay input");')
        anchor = '    for (const auto* mode : {"normal", "npc_override", "fs_override", "getfs_override",'
        probe = r"""
    if (argc == 6)
    {
        Require(std::string_view(argv[5]) == "--binder-observer", "observer argument");
        using namespace ObserverReplay;
        Require(SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_HIGHEST) != 0, "observer thread priority");
        DWORD_PTR allowed = 0, system = 0;
        if (GetProcessAffinityMask(GetCurrentProcess(), &allowed, &system) && allowed)
            SetThreadAffinityMask(GetCurrentThread(), allowed & (~allowed + 1));
        for (const auto* workload : {"binder_545", "binder_569"})
        {
            std::vector<double> fullDelta, boundaryDelta, offDelta;
            uint64_t observedCalls = 0, timedCalls = 0;
            for (unsigned trial = 0; trial != 21; ++trial)
            {
                Result witness;
                std::vector<double> measured[4];
                for (unsigned repeat = 0; repeat != 5; ++repeat)
                    for (unsigned step = 0; step != 4; ++step)
                    {
                        const unsigned variant = (step + trial + repeat) % 4;
                        mode = static_cast<Mode>(variant);
                        const auto state = Replay(argv[3], argv[4], workload);
                        measured[variant].push_back(Milliseconds());
                        Require(completed == 10, "observer NPC count");
                        Require(state.added == (std::string_view(workload) == "binder_545" ? 5450 : 5690),
                            "observer registration count");
                        if (repeat == 0 && step == 0) witness = state;
                        else Require(state.state == witness.state && state.added == witness.added &&
                            state.applied == witness.applied, "observer changed replay state or effects");
                        for (const auto& window : windows)
                            std::printf("OBSERVER_SAMPLE %s %u %u %u %lu %llu %llu\n", workload, trial, repeat, variant,
                                GetCurrentThreadId(), static_cast<unsigned long long>(window.begin),
                                static_cast<unsigned long long>(window.end));
                        if (mode == Full) { observedCalls = calls; timedCalls = timed; }
                    }
                double times[4]{};
                for (unsigned variant = 0; variant != 4; ++variant)
                {
                    std::sort(measured[variant].begin(), measured[variant].end());
                    times[variant] = measured[variant][2];
                }
                if (trial)
                {
                    boundaryDelta.push_back(times[1] - times[0]);
                    fullDelta.push_back(times[2] - times[0]);
                    offDelta.push_back(std::abs(times[3] - times[0]));
                }
            }
            std::printf("OBSERVER %s p95_boundaries=%.6f p95_full=%.6f p95_off_noise=%.6f external_calls=%llu timed_calls=%llu\n",
                workload, P95(boundaryDelta), P95(fullDelta), P95(offDelta),
                static_cast<unsigned long long>(observedCalls), static_cast<unsigned long long>(timedCalls));
        }
        admittedPlan.reset();
        Core._destroy();
        std::filesystem::remove_all(root);
        return 0;
    }

"""
        return one(source, anchor, probe + anchor)
    change(engine / "ixray_spawn_mainline_replay.cpp", voice)

    script = input_script.read_text(encoding="utf-8")
    script = one(script, '    local actorCount = replay_mode == "cohort" and 9 or 24',
                 '''    local captureCohort = replay_mode == "binder_545" or replay_mode == "binder_569"
    local actorCount = captureCohort and 10 or (replay_mode == "cohort" and 9 or 24)''')
    script = one(script, '    local themeCount = replay_mode == "cohort" and 569 or 48',
                 '''    local themeCount = captureCohort and (replay_mode == "binder_545" and 545 or 569)
        or (replay_mode == "cohort" and 569 or 48)''')
    script = one(script, 'avail_communities = replay_mode ~= "cohort"',
                 'avail_communities = not captureCohort and replay_mode ~= "cohort"')
    output.write_text(script, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    apply(*(Path(arg) for arg in sys.argv[1:]))
