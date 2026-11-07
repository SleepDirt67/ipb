#!/usr/bin/env python3
"""Crash follow-up: restore original file retry and stop null script-factory dereference.
Based on actual 2026-11-03 minidump: ACCESS_VIOLATION write 0x8 in
xrFactory_Create(MAIN_MNU); CObjectItemScript swallowed the constructor error.
Apply AFTER apply_ixray_engine_hotpath_fixes.py.
"""
from pathlib import Path
ROOT=Path("ixray/src")
def modify(path,changes):
    p=ROOT/path
    s=p.read_bytes().replace(b"\r\n",b"\n").decode("latin-1")
    for label,old,new in changes:
        count=s.count(old)
        if count!=1:
            raise RuntimeError(f"{path} [{label}] expected one match, found {count}")
        s=s.replace(old,new,1)
    p.write_bytes(s.encode("latin-1"))
    print("Crash-fix:",path,len(changes),"anchors")

# Abort the risky experiment that omitted the original 1-ms retry for ENOENT.
# The original behavior must be retained until a real failing path is identified.
modify("xrCore/FS.cpp", [
 ("remove extra errno header", '#include "FS_internal.h"\n#include <cerrno>', '#include "FS_internal.h"'),
 ("restore exact original retry", '''    const errno_t first_error = open_internal(file_name, file_handle);
    if (first_error)
    {
        // A missing path should not force a scheduler sleep (which can exceed
        // one millisecond). Keep delayed retry for potentially transient errors.
        if (first_error == ENOENT || first_error == ENOTDIR)
            return false;
        Sleep(1);
        if (open_internal(file_name, file_handle))
            return false;
    }''', '''\tif (open_internal(file_name, file_handle))
\t{
\t\tSleep(1);
\t\tif (open_internal(file_name, file_handle))
\t\t\treturn (false);
\t}''')
])

# Scripted factory constructors previously swallowed any Lua/C++ exception,
# concealing the real cause. Log the failing CLSID and exception.
modify("xrServerEntities/object_item_script.cpp", [
 ("catch and report script-client creation errors", '''\tcatch(...) {
\t\treturn\t(0);
\t}
\tR_ASSERT\t(object);
\treturn\t\t(object->_construct());''', '''    catch (const std::exception& e)
    {
        string16 name = {};
        CLSID2TEXT(clsid(), name);
        Msg("! [SCRIPT-FACTORY] failed to create client class [%s]: %s", name, e.what());
        return nullptr;
    }
    catch (...)
    {
        string16 name = {};
        CLSID2TEXT(clsid(), name);
        Msg("! [SCRIPT-FACTORY] failed to create client class [%s]: unknown exception", name);
        return nullptr;
    }
    R_ASSERT(object);
    return object->_construct();''')
])
# The Release version used a debug-only null check. The main menu caller
# explicitly handles a nullptr result, so honor that contract in Release too.
modify("xrGame/xrGame.cpp", [
 ("null check release build", '''#ifdef DEBUG
\t\tif (!object)
\t\t\treturn\t\t\t(0);
#endif

\t\tobject->CLS_ID = clsid;''', '''        if (!object)
        {
            string16 name = {};
            CLSID2TEXT(clsid, name);
            Msg("! [GAME-FACTORY] null client object for class [%s]", name);
            return nullptr;
        }

\t\tobject->CLS_ID = clsid;''')
])
print("Original FS semantics restored; Release null dereference guarded; script-factory errors logged.")
