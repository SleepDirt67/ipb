#!/usr/bin/env python3
"""Repair class layout ABI compatibility with the separately installed xrUI.dll.

The earlier hotpath experiment inserted std::map into IGame_ObjectPool, which
is an embedded member of IGame_Persistent. The existing four-module artifact
does NOT replace xrUI.dll, so that changes offsets across module boundaries.
Keep model index and other behavior-neutral optimizations, but restore the
EXACT upstream IGame_ObjectPool class layout and original object factory.
Run after apply_ixray_mainmenu_crashfix.py.
"""
from pathlib import Path
ROOT=Path("ixray/src")
def modify(path, changes):
    p=ROOT/path
    s=p.read_bytes().replace(b"\r\n",b"\n").decode("latin-1")
    for label,before,after in changes:
        n=s.count(before)
        if n!=1:
            raise RuntimeError(f"{path}: {label}: expected exactly one anchor, found {n}")
        s=s.replace(before,after,1)
    p.write_bytes(s.encode("latin-1"))
    print("ABI restored:",path)

modify("xrEngine/IGame_ObjectPool.h",[
  ("remove map includes", "#pragma once\n#include <map>\n#include <string>\nclass CInifile;", "#pragma once"),
  ("restore exact class fields", 
   "\tObjectVec\t\t\t\t\tm_PrefetchObjects;\n"
   "    const CInifile* m_classSettings = nullptr;\n"
   "    std::map<std::string, CLASS_ID, std::less<>> m_classIds;",
   "\tObjectVec\t\t\t\t\tm_PrefetchObjects;")
])
modify("xrEngine/IGame_ObjectPool.cpp",[
  ("remove cache clear",
   "    m_PrefetchObjects.clear();\n    m_classIds.clear();\n    m_classSettings = nullptr;",
   "\tm_PrefetchObjects.clear\t(); "),
  ("remove class-ID caching from create",
   '''    if (m_classSettings != pSettings)
    {
        m_classIds.clear();
        m_classSettings = pSettings;
    }
    const auto cached = m_classIds.find(name);
    CLASS_ID CLS;
    if (cached == m_classIds.end())
    {
        CLS = pSettings->r_clsid(name, "class");
        m_classIds.emplace(name, CLS);
    }
    else
        CLS = cached->second;''',
   '''\tCLASS_ID CLS\t\t=\tpSettings->r_clsid\t\t(name,"class");''')
])
print("IGame_ObjectPool fields/order and size restored; same CLS_ID lookup as upstream.")
