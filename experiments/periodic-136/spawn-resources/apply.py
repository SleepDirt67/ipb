"""Apply independent loading-time OGG preparation and standalone Lua INI reuse."""
from pathlib import Path
import shutil
import sys

source = Path(__file__).resolve().parent
engine = Path(sys.argv[1])


def edit(name, replacements):
    path = engine / name
    data = path.read_bytes()
    content = data.decode("utf-8").replace("\r\n", "\n")
    for before, after in replacements:
        if content.count(before) != 1:
            raise ValueError(f"{name}: expected exactly one {before[:100]!r}")
        content = content.replace(before, after, 1)
    if b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""):
        content = content.replace("\n", "\r\n")
    path.write_bytes(content.encode("utf-8"))


shutil.copy2(source / "SoundWaveMetadata.h", engine / "src/xrSound/SoundWaveMetadata.h")
edit("src/xrSound/CMakeLists.txt", [
    ("setup_audio_libs(xrSound)", "setup_audio_libs(xrSound)\nif(WIN32)\n    target_link_libraries(xrSound PRIVATE bcrypt)\nendif()"),
])
edit("src/xrSound/Sound.h", [
    ("#define OGG_COMMENT_VERSION", "XRSOUND_API void PrepareSpawnSoundMetadata();\n\n#define OGG_COMMENT_VERSION"),
])
edit("src/xrSound/SoundRender_Source_loader.cpp", [
    ('#include "ogg_utils.h"',
     '#include "ogg_utils.h"\n\n' + (source / "SoundWaveWarmup.inc").read_text().rstrip()),
    ('\tov_callbacks\t\t\tovc;',
     """#ifdef IXR_WINDOWS
    Metadata prepared;
    if (TryUsePreparedWave(*m_wave, pname.c_str(), prepared))
    {
        m_wformat.nSamplesPerSec = prepared.rate;
        m_wformat.wFormatTag = WAVE_FORMAT_PCM;
        m_wformat.nChannels = prepared.channels;
        m_wformat.wBitsPerSample = 16;
        m_wformat.nBlockAlign = prepared.channels * 2;
        m_wformat.nAvgBytesPerSec = m_wformat.nSamplesPerSec * m_wformat.nBlockAlign;
        dwBytesTotal = prepared.bytes;
        fTimeTotal = s_f_def_source_footer + dwBytesTotal / float(m_wformat.nAvgBytesPerSec);
        m_fMinDist = prepared.minimum;
        m_fMaxDist = prepared.maximum;
        m_fBaseVolume = prepared.base;
        m_fMaxAIDist = prepared.ai;
        m_uGameType = prepared.type;
        FS.r_close(m_wave);
        return;
    }
#endif

\tov_callbacks\t\t\tovc;"""),
])
edit("src/xrEngine/IGame_Persistent.cpp", [
    ('#include "CustomHUD.h"', '#include "CustomHUD.h"\n#include "../xrSound/Sound.h"'),
    ('\tPROF_EVENT("Prefetch");', '\tPROF_EVENT("Prefetch");\n\tif (!g_dedicated_server)\n\t\tPrepareSpawnSoundMetadata();'),
])
edit("src/xrCore/xr_ini.h", [
    ('\tvoid Load(IReader* F,', '\tbool LoadScriptConfig();\n\tvoid Load(IReader* F,'),
])
edit("src/xrCore/Xr_ini.cpp", [
    ('#include <iterator>', '#include <iterator>\n#include <cstdlib>\n#include <memory>\n#include <mutex>\n#include <string_view>\n#include <unordered_map>'),
    ('void CInifile::Load(IReader* F,', (source / "ScriptIniCache.inc").read_text() + '\nvoid CInifile::Load(IReader* F,'),
])
edit("src/xrCore/xrCore.cpp", [
    ('void xrCore::_destroy', 'void ClearScriptIniSnapshots();\n\nvoid xrCore::_destroy'),
    ('\t\tFS._destroy', '\t\tClearScriptIniSnapshots();\n\t\tFS._destroy'),
])
edit("src/xrScripts/exports/script_ini_file.cpp", [
    ('\tinherited(path ? path : update(szFileName), ReadOnly, bLoadAtStart, SaveAtEnd)\n{',
     '\tinherited(path ? path : update(szFileName), ReadOnly, FALSE, SaveAtEnd)\n{\n'
     '    if (bLoadAtStart)\n        LoadScriptConfig();'),
])
shutil.copy2(source / "ini_fixture.cpp", engine / "ixray_spawn_ini_fixture.cpp")
with (engine / "CMakeLists.txt").open("a", encoding="utf-8") as output:
    output.write("""
add_executable(ixray_spawn_ini_check ixray_spawn_ini_fixture.cpp)
target_include_directories(ixray_spawn_ini_check PRIVATE ${CMAKE_SOURCE_DIR}/src/xrCore)
target_link_libraries(ixray_spawn_ini_check PRIVATE xrCore)
""")
