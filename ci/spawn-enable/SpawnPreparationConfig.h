#pragma once

#include <cstdlib>

namespace SpawnPreparation
{
inline bool Requested()
{
#if defined(_M_X64) && !defined(DEBUG)
    const char* flag = std::getenv("IXRAY_SPAWN_PREPARE");
    return !flag || (flag[0] == '1' && flag[1] == '\0');
#else
    return false;
#endif
}
}
