// Post-process the kernel Thread_V2 scheduling events. No decoder runs in gameplay.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <evntrace.h>
#include <evntcons.h>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <limits>
#include <map>
#include <set>
#include <string>

namespace {
constexpr GUID threadProvider = {0x3d6fa8d1,0xfe05,0x11d0,{0x9d,0xda,0x00,0xc0,0x4f,0xd7,0xba,0x7c}};
constexpr unsigned cswitch = 36, ready = 50;

struct Decoder {
    FILE* out = nullptr;
    std::set<unsigned> threads;
    struct Cpu { long long first = 0, last = 0; unsigned lastThread = 0; };
    std::map<unsigned, Cpu> cpus;
    unsigned long long chainBreaks = 0;
    unsigned long long switches = 0, wakeups = 0, written = 0, unknown = 0;
};

unsigned ReadU32(const unsigned char* data) {
    unsigned value;
    std::memcpy(&value, data, sizeof(value));
    return value;
}

bool KnownPayload(unsigned kind, unsigned version, unsigned size) {
    if (kind == cswitch && version == 5) return size == 28;
    return version >= 2 && version <= 4 && size >= (kind == cswitch ? 24 : 8);
}

void WINAPI OnEvent(EVENT_RECORD* event) {
    auto& d = *static_cast<Decoder*>(event->UserContext);
    const auto& h = event->EventHeader;
    if (!IsEqualGUID(h.ProviderId, threadProvider)) return;
    const auto kind = h.EventDescriptor.Opcode;
    if (kind != cswitch && kind != ready) return;
    const auto qpc = h.TimeStamp.QuadPart;
    const auto* data = static_cast<const unsigned char*>(event->UserData);
    // Win11 build 26100 emits a 28-byte CSwitch v5 with the same decoded prefix.
    if (!data || !KnownPayload(kind,h.EventDescriptor.Version,event->UserDataLength)) {
        ++d.unknown;
        return;
    }
    const auto tid = ReadU32(data);
    const auto cpu = static_cast<unsigned>(event->BufferContext.ProcessorIndex);
    if (kind == cswitch) {
        ++d.switches;
        const auto previous = ReadU32(data+4);
        auto& lane = d.cpus[cpu];
        if (!lane.first) lane.first = qpc;
        else if (qpc < lane.last || lane.lastThread != previous) ++d.chainBreaks;
        lane.last = qpc;
        lane.lastThread = tid;
        if (!d.threads.count(tid) && !d.threads.count(previous)) return;
        std::fprintf(d.out,"%lld,switch,%u,%u,%u,%u,%u\n",qpc,cpu,tid,previous,data[14],data[12]);
    } else {
        ++d.wakeups;
        if (!d.threads.count(tid)) return;
        std::fprintf(d.out,"%lld,ready,%u,%u,%lu,0,%u\n",qpc,cpu,tid,h.ThreadId,data[6]);
    }
    ++d.written;
}

ULONG QuerySession(const wchar_t* name) {
    struct Buffer {
        EVENT_TRACE_PROPERTIES properties;
        wchar_t logger[1024];
        wchar_t file[4096];
    } buffer{};
    buffer.properties.Wnode.BufferSize = sizeof(buffer);
    buffer.properties.LoggerNameOffset = FIELD_OFFSET(Buffer, logger);
    buffer.properties.LogFileNameOffset = FIELD_OFFSET(Buffer, file);
    return ControlTraceW(0,name,&buffer.properties,EVENT_TRACE_CONTROL_QUERY);
}
}

int wmain(int argc,wchar_t** argv) {
    if (argc == 2 && std::wstring(argv[1]) == L"--self-test") {
        return KnownPayload(cswitch,2,24) && KnownPayload(cswitch,5,28) &&
            !KnownPayload(cswitch,5,24) && !KnownPayload(cswitch,6,28) &&
            KnownPayload(ready,2,8) && !KnownPayload(ready,5,8) ? 0 : 1;
    }
    if (argc == 3 && std::wstring(argv[1]) == L"--session-active")
        return QuerySession(argv[2]) == ERROR_SUCCESS ? 0 : 1;
    if (argc != 5 || std::wstring(argv[1]) != L"--extract") {
        std::fprintf(stderr,"Usage: ixray_etw_decode --extract trace.etl schedule.csv tid,tid,...\n");
        return 2;
    }

    Decoder decoder;
    try {
        const std::wstring ids = argv[4];
        std::size_t start = 0;
        while (start < ids.size()) {
            std::size_t count;
            const unsigned tid = std::stoul(ids.substr(start), &count);
            decoder.threads.insert(tid);
            start += count;
            if (start < ids.size() && ids[start++] != L',') return 2;
        }
    } catch (...) { return 2; }
    if (decoder.threads.empty()) return 2;

    EVENT_TRACE_LOGFILEW log{};
    log.LogFileName = argv[2];
    log.ProcessTraceMode = PROCESS_TRACE_MODE_EVENT_RECORD | PROCESS_TRACE_MODE_RAW_TIMESTAMP;
    log.EventRecordCallback = OnEvent;
    log.Context = &decoder;
    auto trace = OpenTraceW(&log);
    if (trace == INVALID_PROCESSTRACE_HANDLE) {
        std::fprintf(stderr,"OpenTrace failed: %lu\n",GetLastError());
        return 3;
    }

    // The ETL header records which clock ETW used. Never treat FILETIME as QPC.
    const auto clock = log.LogfileHeader.ReservedFlags;
    const auto frequency = log.LogfileHeader.PerfFreq.QuadPart;
    if (clock != 1 || frequency <= 0) {
        std::fprintf(stderr,"Trace is not in raw QPC units: clock=%lu frequency=%lld\n",clock,frequency);
        CloseTrace(trace);
        return 4;
    }
    if (_wfopen_s(&decoder.out,argv[3],L"wb") || !decoder.out) {
        CloseTrace(trace);
        return 5;
    }
    std::fputs("qpc,kind,cpu,tid,other_tid,old_state,wait_reason_or_ready_flags\n",decoder.out);
    const auto status = ProcessTrace(&trace,1,nullptr,nullptr);
    CloseTrace(trace);
    const bool ioOk = std::fclose(decoder.out) == 0;
    if (status != ERROR_SUCCESS || !ioOk || !decoder.written || !decoder.switches) {
        std::fprintf(stderr,"ETW decode incomplete: status=%lu rows=%llu switches=%llu unsupported=%llu\n",
            status,decoder.written,decoder.switches,decoder.unknown);
        return 6;
    }
    long long first = 0, last = std::numeric_limits<long long>::max();
    for (const auto& item : decoder.cpus) {
        if (item.second.first > first) first = item.second.first;
        if (item.second.last < last) last = item.second.last;
    }
    std::printf("{\"qpc_frequency\":%lld,\"qpc_first\":%lld,\"qpc_last\":%lld,\"switch_events\":%llu,"
        "\"ready_events\":%llu,\"filtered_rows\":%llu,\"unsupported_events\":%llu,"
        "\"events_lost\":%lu,\"buffers_lost\":%lu,\"cpu_lanes\":%zu,\"switch_chain_breaks\":%llu}\n",
        frequency,first,last,decoder.switches,decoder.wakeups,decoder.written,
        decoder.unknown,log.LogfileHeader.EventsLost,log.LogfileHeader.BuffersLost,decoder.cpus.size(),decoder.chainBreaks);
    return 0;
}
