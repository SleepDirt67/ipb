"""Exercise the production LuaJIT sweep window on a mixed spawn replay."""
import ctypes as C
import json
import statistics
import sys
from time import perf_counter_ns

def replay(library, paced, jit, pending):
    vm = C.CDLL(library)
    vm.luaL_newstate.restype = C.c_void_p
    vm.lua_close.argtypes = [C.c_void_p]
    vm.luaL_openlibs.argtypes = [C.c_void_p]
    vm.luaL_loadstring.argtypes = [C.c_void_p, C.c_char_p]
    vm.lua_pcall.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int]
    vm.lua_settop.argtypes = [C.c_void_p, C.c_int]
    vm.lua_gc.argtypes = [C.c_void_p, C.c_int, C.c_int]
    vm.lua_tolstring.argtypes = [C.c_void_p, C.c_int, C.c_void_p]
    vm.lua_tolstring.restype = C.c_char_p
    state = vm.luaL_newstate()
    assert state
    try:
        vm.luaL_openlibs(state)
        def run(script, result=False):
            if vm.luaL_loadstring(state, script) or vm.lua_pcall(state, 0, int(result), 0):
                raise RuntimeError(vm.lua_tolstring(state, -1, None))
            if result:
                value = vm.lua_tolstring(state, -1, None)
                vm.lua_settop(state, 0)
                return value

        def gc(op, data=0):
            return vm.lua_gc(state, op, data)

        if not jit:
            run(b"jit.off()")
        run(b"""
            local collect = collectgarbage
            collect("collect")
            collect("stop")
            keep = {}
            local scratch = {}
            for i=1,200000 do
                local t = {i,i+1,i+2,flag=true}
                if i % 4 == 0 then keep[#keep+1]=t
                else scratch[#scratch+1]=t end
            end
            objects, log, finalizers = {}, {}, {}
            function spawn(id,parent)
                assert(objects[id] == nil)
                local o = {id=id, parent=parent and assert(objects[parent]), tick=0}
                objects[id]=o  -- Match early client registration before binder.
                local work={}
                for i=1,400 do work[i]={i+id, kind='binder', o=o} end
                assert(objects[id]==o)
                o.tick=work[400][1]
                log[#log+1]=id
            end
            function mixed_event()
                assert(objects[101] and objects[101].parent==objects[100])
                objects[101]=nil
                log[#log+1]=-101
            end
            function test_explicit()
                local proxy=newproxy(true)
                getmetatable(proxy).__gc=function() finalizers[#finalizers+1]=17 end
                proxy=nil
                collect("collect")
                assert(finalizers[#finalizers]==17)
                collect("stop")
                assert(not collect("isrunning"))
                collect("restart")
            end
        """)
        if pending:
            run(b"""
                do
                    local proxy=newproxy(true)
                    getmetatable(proxy).__gc=function() finalizers[#finalizers+1]=19 end
                end
            """)
        run(b'collectgarbage("restart")')
        # Start all timed dispatches near the same checkpoint. 0 KiB API steps
        # still advance one ordinary LuaJIT quantum through propagation.
        for _ in range(16000):
            if gc(-30106) == (2 if pending else 1):
                break
            assert gc(5, 0) == 0, 'missed target sweep phase'
        else:
            raise AssertionError('target heap never reached object sweep')

        start = perf_counter_ns()
        if paced:
            assert gc(-30100) == 0
        run(b'spawn(100); spawn(101,100); spawn(102,101); spawn(103,102)')
        if paced:
            assert gc(-30100) == 0
        run(b'for i=104,119 do spawn(i,100) end')
        if paced:
            assert gc(-30101) == 0
        run(b'for i=120,133 do spawn(i,100) end')
        yields = gc(-30101) if paced else 0
        run(b'mixed_event()')
        elapsed = perf_counter_ns() - start
        peak_kib = gc(3)
        tails = []
        quanta = 0
        for _ in range(140):
            start = perf_counter_ns()
            run(b"local small = {}; for i=1,100 do small[i]={i} end")
            if paced and gc(-30102) == 1:
                deadline = perf_counter_ns() + 200000
                for _ in range(128):
                    if perf_counter_ns() >= deadline or gc(-30103) != 1:
                        break
                    quanta += 1
            else:
                gc(5, 10)  # The existing engine maintenance without dispatch debt.
            tails.append(perf_counter_ns() - start)
        if paced:
            gc(-30100)
        run(b'test_explicit()')
        if paced:
            gc(-30101)
        result = run(b'''
            local weak=setmetatable({}, {__mode="v"})
            do weak[1]={} end
            collectgarbage("collect")
            assert(weak[1]==nil)
            return table.concat(log,",").."/"..table.concat(finalizers,",")
                .."/"..objects[133].tick
        ''', True)
        return {'dispatch_ns': elapsed, 'maintenance_max_ns': max(tails),
                'maintenance_total_ns': sum(tails), 'peak_checkpoint_kib': peak_kib,
                'yields': yields, 'maintenance_quanta': quanta, 'digest': result.decode()}
    finally:
        vm.lua_close(state)

if __name__ == '__main__':
    runtime = sys.argv[1]
    for jit in (False, True):
        for pending in (False, True):
            pairs = [(replay(runtime, False, jit, pending),
                      replay(runtime, True, jit, pending)) for _ in range(5)]
            for base, exp in pairs:
                assert base['digest'] == exp['digest'], (base, exp)
                if pending:
                    assert exp['yields'] == 0, exp
                else:
                    assert exp['yields'] > 0, exp
            metrics = tuple(key for key in pairs[0][0] if key != 'digest')
            print(json.dumps({'jit': jit, 'pending_finalizer': pending,
                              'baseline': {key: statistics.median(p[0][key] for p in pairs) for key in metrics},
                              'paced': {key: statistics.median(p[1][key] for p in pairs) for key in metrics}}))
