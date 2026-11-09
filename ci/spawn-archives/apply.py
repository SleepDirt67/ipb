"""Share a read-only view across packed resource readers on Windows x64."""
import argparse
from pathlib import Path


def edit(path, before, after):
    raw = path.read_bytes()
    data = raw.replace(b"\r\n", b"\n")
    before, after = before.encode(), after.encode()
    if data.count(before) != 1:
        raise ValueError((path, before[:100], data.count(before)))
    result = data.replace(before, after, 1)
    if b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""):
        result = result.replace(b"\n", b"\r\n")
    path.write_bytes(result)


def patch(root):
    core = root / "src/xrCore"
    edit(core / "LocatorAPI.h", "    archives_vec\t\t\t\tm_archives;",
         """    archives_vec\t\t\t\tm_archives;
#ifdef IXR_WINDOWS
    std::shared_ptr<void> acquire_archive_view(const archive& source);
#endif""")
    loc = core / "LocatorAPI.cpp"
    edit(loc, '#include "SpawnVoiceVfs.inc"',
         '''#include "SpawnVoiceVfs.inc"
#include "SpawnPreparationConfig.h"
#include <unordered_map>

#ifdef IXR_WINDOWS
namespace
{
struct PackedViews
{
    std::shared_mutex mutex;
    std::unordered_map<void*, std::shared_ptr<void>> byMapping;
};
PackedViews packedViews;
}

std::shared_ptr<void> CLocatorAPI::acquire_archive_view(const archive& source)
{
    std::shared_lock guard(packedViews.mutex);
    const auto found = packedViews.byMapping.find(source.hSrcMap);
    return found != packedViews.byMapping.end() ? found->second : nullptr;
}
#endif''')
    edit(loc, "\tsize\t\t\t= Platform::GetFileSize(hSrcFile);\n\tR_ASSERT\t\t(size>0);",
         """\tsize\t\t\t= Platform::GetFileSize(hSrcFile);
\tR_ASSERT\t\t(size>0);
#if defined(IXR_WINDOWS) && defined(_M_X64)
    // A view is virtual address space. OS paging still fetches individual
    // archive pages on demand. Fall back if a whole view cannot be mapped.
    if (SpawnPreparation::Requested() && size <= 0x7fffffffu)
    {
        if (auto* view = MapViewOfFile(hSrcMap, FILE_MAP_READ, 0, 0, size))
        {
            try
            {
                auto owner = std::shared_ptr<void>(view, [](void* address) {
                    UnmapViewOfFile(address);
                });
                std::unique_lock guard(packedViews.mutex);
                packedViews.byMapping.emplace(hSrcMap, std::move(owner));
            }
            catch (const std::bad_alloc&)
            {
                // The shared_ptr constructor invokes its deleter on failure.
            }
        }
    }
#endif""")
    edit(loc, "\tCloseHandle\t\t(hSrcMap);\n\thSrcMap\t\t\t= nullptr;",
         """    {
        std::unique_lock guard(packedViews.mutex);
        packedViews.byMapping.erase(hSrcMap);
    }
\tCloseHandle\t\t(hSrcMap);
\thSrcMap\t\t\t= nullptr;""")
    edit(loc, "void CLocatorAPI::file_from_archive\t(IReader *&R, LPCSTR fname, const file &desc)",
         """#ifdef IXR_WINDOWS
namespace
{
class SharedArchiveReader final : public IReader
{
    std::shared_ptr<void> view_;

public:
    SharedArchiveReader(std::shared_ptr<void> view, void* data, size_t size)
        : IReader(data, size), view_(std::move(view)) {}
};
}
#endif

void CLocatorAPI::file_from_archive\t(IReader *&R, LPCSTR fname, const file &desc)""")
    edit(loc, "\tarchive& A\t\t\t\t\t= m_archives[desc.vfs];",
         """\tarchive& A\t\t\t\t\t= m_archives[desc.vfs];
#ifdef IXR_WINDOWS
    if (auto view = acquire_archive_view(A); view && desc.size_compressed &&
        u64(desc.ptr) + desc.size_compressed <= A.size)
    {
        auto* bytes = static_cast<u8*>(view.get()) + desc.ptr;
        if (desc.size_real == desc.size_compressed)
        {
            R = new SharedArchiveReader(std::move(view), bytes, desc.size_real);
            return;
        }

        auto* decompressed = xr_alloc<u8>(desc.size_real);
        rtc_decompress(decompressed, desc.size_real, bytes, desc.size_compressed);
        R = new CTempReader(decompressed, desc.size_real, 0);
        return;
    }
#endif""")
    sound = root / "src/xrSound/SoundRender_Source_loader.cpp"
    edit(sound, '''    if (!archive.hSrcMap || std::uint64_t(file.ptr) + file.size_real > archive.size)
        return {};

    const DWORD offset''',
         '''    if (!archive.hSrcMap || std::uint64_t(file.ptr) + file.size_real > archive.size)
        return {};
    if (const auto view = FS.acquire_archive_view(archive))
    {
        const auto* bytes = static_cast<const unsigned char*>(view.get()) + file.ptr;
        return {bytes, bytes + file.size_real};
    }

    const DWORD offset''')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    patch(parser.parse_args().engine)
