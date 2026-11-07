#!/usr/bin/env python3
"""IX-Ray r1.3.6 narrow performance changes; gameplay/event order unchanged.
Run after canonical HOLD, CPU, DX11 and optional diagnostics. Fail on missing anchors.
"""
from pathlib import Path
ROOT=Path("ixray/src")

def modify(path, changes):
    p=ROOT/path
    s=p.read_bytes().replace(b"\r\n",b"\n").decode("latin-1")
    for label,old,new in changes:
        n=s.count(old)
        if n!=1:
            raise RuntimeError(f"{path} [{label}]: expected one exact anchor, got {n}")
        s=s.replace(old,new,1)
    p.write_bytes(s.encode("latin-1"))
    print("Updated",path,":",len(changes),"anchors")

# ModelPool::Instance_Find originally walks every registered base model.
# The index always preserves the FIRST registered matching name, exactly as the scan.
# It is updated on register, release of a base model, and complete destruction.
modify("Layers/xrRender/ModelPool.h", [
 ("headers", "#pragma once", "#pragma once\n#include <map>\n#include <string>"),
 ("index member", "\txr_vector<ModelDef>\t\t\tModels;", 
  "\txr_vector<ModelDef>\t\t\tModels;\n"
  "\t// Same case-sensitive first-match semantics as the original linear scan.\n"
  "\tstd::map<std::string, dxRender_Visual*, std::less<>> ModelsByName;")
])
modify("Layers/xrRender/ModelPool.cpp", [
 ("index insertion", '''\tModels.push_back\t(M);
}''', '''\tModels.push_back\t(M);
    if (N && N[0])
        ModelsByName.emplace(N, V); // do not replace original first registration
}'''),
 ("index clearing", '''\tModels.clear();

\t// cleanup motions container''', '''    Models.clear();
    ModelsByName.clear();

\t// cleanup motions container'''),
 ("find", '''dxRender_Visual* CModelPool::Instance_Find(const char* N)
{
\tdxRender_Visual*\t\t\t\tModel=0;
\txr_vector<ModelDef>::iterator\tI;
\tfor (I=Models.begin(); I!=Models.end(); I++)
\t{
\t\tif (I->name[0]&&(0==xr_strcmp(*I->name,N))) {
\t\t\tModel = I->model;
\t\t\tbreak;
\t\t}
\t}
\treturn Model;
}''', '''dxRender_Visual* CModelPool::Instance_Find(const char* N)
{
    const auto found = ModelsByName.find(N);
    return found == ModelsByName.end() ? nullptr : found->second;
}'''),
 ("reindex on discard", '''\t\t\t\t\t\tModels.erase(I);
\t\t\t\t\t\tbForceDiscard = FALSE;''', '''                        Models.erase(I);
                        // A duplicate name can exist. Preserve original first-match
                        // behavior after removal by finding the earliest survivor.
                        ModelsByName.erase(*name);
                        for (const ModelDef& other : Models)
                        {
                            if (other.name.size() != 0 && xr_strcmp(*other.name, *name) == 0)
                            {
                                ModelsByName.emplace(*name, other.model);
                                break;
                            }
                        }
\t\t\t\t\t\tbForceDiscard = FALSE;''')
])

# Cache class IDs only for the lifespan of the current object pool / pSettings.
# Runtime scripts and object contents are not cached or bypassed.
modify("xrEngine/IGame_ObjectPool.h", [
 ("headers", "#pragma once", "#pragma once\n#include <map>\n#include <string>\nclass CInifile;"),
 ("member", '''\tObjectVec\t\t\t\t\tm_PrefetchObjects;''', '''\tObjectVec\t\t\t\t\tm_PrefetchObjects;
    const CInifile* m_classSettings = nullptr;
    std::map<std::string, CLASS_ID, std::less<>> m_classIds;''')
])
modify("xrEngine/IGame_ObjectPool.cpp", [
 ("cache clear", '''\tm_PrefetchObjects.clear\t(); 
}''', '''    m_PrefetchObjects.clear();
    m_classIds.clear();
    m_classSettings = nullptr;
}'''),
 ("class lookup", '''\tCLASS_ID CLS\t\t=\tpSettings->r_clsid\t\t(name,"class");
\tCObject* O\t\t\t=\t(CObject*) NEW_INSTANCE\t(CLS);''', '''    if (m_classSettings != pSettings)
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
        CLS = cached->second;
\tCObject* O\t\t\t= \t(CObject*) NEW_INSTANCE\t(CLS);''')
])

# Missing ordinary files cannot become accessible by waiting one millisecond
# within a static installed game tree. Preserve the existing retry for transient
# failures (sharing/permission/IO errors). No changed engine-side exceptions.
modify("xrCore/FS.cpp", [
 ("errno", '#include "FS_internal.h"', '#include "FS_internal.h"\n#include <cerrno>'),
 ("file open", '''\tif (open_internal(file_name, file_handle))
\t{
\t\tSleep(1);
\t\tif (open_internal(file_name, file_handle))
\t\t\treturn (false);
\t}''', '''    const errno_t first_error = open_internal(file_name, file_handle);
    if (first_error)
    {
        // A missing path should not force a scheduler sleep (which can exceed
        // one millisecond). Keep delayed retry for potentially transient errors.
        if (first_error == ENOENT || first_error == ENOTDIR)
            return false;
        Sleep(1);
        if (open_internal(file_name, file_handle))
            return false;
    }''')
])
print("No changes to schedule intervals, Lua GC step, spawn ordering or AI behavior.")
