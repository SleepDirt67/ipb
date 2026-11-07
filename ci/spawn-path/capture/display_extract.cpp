#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <evntrace.h>
#include <evntcons.h>
#include <algorithm>
#include <array>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <utility>
#include <vector>

namespace {
using Qpc = unsigned long long;
struct Provider { GUID guid; const char* name; };
constexpr Provider providers[] = {
    {{0x802ec45a,0x1e99,0x4b83,{0x99,0x20,0x87,0xc9,0x82,0x77,0xba,0x9d}}, "DxgKrnl"},
    {{0xca11c036,0x0102,0x4a2d,{0xa6,0xad,0xf0,0x3c,0xfe,0xd5,0xd3,0xc9}}, "DXGI"},
    {{0x9e9bba3c,0x2e38,0x40cb,{0x99,0xf4,0x9e,0x82,0x81,0x42,0x51,0x64}}, "Dwm-Core"},
    {{0x8c416c79,0xd49b,0x4f01,{0xa4,0x67,0xe5,0x6d,0x3a,0xa8,0x23,0x4c}}, "Win32k"},
};
struct Capture {
    FILE* file = nullptr;
    std::vector<std::pair<Qpc,Qpc>> windows;
    std::array<Qpc,std::size(providers)> counts{};
    Qpc first = 0, last = 0, exported = 0;
};
void WINAPI OnEvent(EVENT_RECORD* event) {
    auto& capture = *static_cast<Capture*>(event->UserContext);
    const auto& header = event->EventHeader;
    const auto provider = std::find_if(std::begin(providers), std::end(providers), [&](const Provider& item) {
        return IsEqualGUID(item.guid, header.ProviderId);
    });
    if (provider == std::end(providers))
        return;

    const auto qpc = static_cast<Qpc>(header.TimeStamp.QuadPart);
    ++capture.counts[provider - std::begin(providers)];
    capture.first = capture.first ? std::min(capture.first, qpc) : qpc;
    capture.last = std::max(capture.last, qpc);
    const auto after = std::upper_bound(capture.windows.begin(), capture.windows.end(), qpc,
        [](Qpc value, const auto& interval) { return value < interval.first; });
    if (after == capture.windows.begin() || std::prev(after)->second < qpc)
        return;

    const auto& desc = header.EventDescriptor;
    std::fprintf(capture.file, "%llu,%s,%u,%u,%u,%u,%lu,%lu,%u,", qpc, provider->name,
        desc.Id, desc.Version, desc.Opcode, desc.Task, header.ProcessId, header.ThreadId, header.Flags);
    const auto* payload = static_cast<const unsigned char*>(event->UserData);
    for (unsigned i = 0; payload && i < event->UserDataLength; ++i)
        std::fprintf(capture.file, "%02x", static_cast<unsigned>(payload[i]));
    std::fputc('\n', capture.file);
    ++capture.exported;
}
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 4)
        return 2;
    Capture capture;
    std::ifstream windows{std::filesystem::path(argv[2])};
    if (!windows)
        return 2;
    Qpc from, to;
    while (windows >> from >> to) {
        if (from > to || (!capture.windows.empty() && from <= capture.windows.back().second))
            return 2;
        capture.windows.emplace_back(from, to);
    }
    if (!windows.eof() || _wfopen_s(&capture.file, argv[3], L"wb") || !capture.file)
        return 2;
    std::fputs("qpc,provider,event_id,version,opcode,task,pid,tid,header_flags,payload_hex\n", capture.file);

    EVENT_TRACE_LOGFILEW log{};
    log.LogFileName = argv[1];
    log.ProcessTraceMode = PROCESS_TRACE_MODE_EVENT_RECORD | PROCESS_TRACE_MODE_RAW_TIMESTAMP;
    log.EventRecordCallback = OnEvent;
    log.Context = &capture;
    const auto trace = OpenTraceW(&log);
    if (trace == INVALID_PROCESSTRACE_HANDLE) {
        std::fclose(capture.file);
        return 3;
    }
    const bool qpc = log.LogfileHeader.ReservedFlags == 1;
    auto handle = trace;
    const auto status = qpc ? ProcessTrace(&handle, 1, nullptr, nullptr) : ERROR_INVALID_DATA;
    CloseTrace(trace);
    const int flush = std::fclose(capture.file);
    if (status != ERROR_SUCCESS || flush || !capture.first)
        return 4;
    std::printf("{\"qpc_frequency\":%lld,\"first_qpc\":%llu,\"last_qpc\":%llu,\"exported\":%llu,"
        "\"events_lost\":%lu,\"buffers_lost\":%lu,\"providers\":{", log.LogfileHeader.PerfFreq.QuadPart,
        capture.first, capture.last, capture.exported, log.LogfileHeader.EventsLost, log.LogfileHeader.BuffersLost);
    for (size_t i = 0; i < std::size(providers); ++i)
        std::printf("%s\"%s\":%llu", i ? "," : "", providers[i].name, capture.counts[i]);
    std::puts("}}");
}
