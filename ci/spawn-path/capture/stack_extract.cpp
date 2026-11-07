#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <evntrace.h>
#include <evntcons.h>
#include <dbghelp.h>
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr GUID stackProvider{0xdef2fe46,0x7bd6,0x4b80,{0xbd,0x94,0xf5,0x7f,0xe2,0x0d,0x0c,0xe3}};
constexpr GUID perfProvider{0xce1dbfb4,0x137e,0x4da6,{0x87,0xb0,0x3f,0x59,0xaa,0x10,0x2c,0xbc}};

template<class T> T Read(const unsigned char* data) {
    T value;
    std::memcpy(&value,data,sizeof(value));
    return value;
}

using Key = std::pair<unsigned long long,unsigned>;
struct Trace {
    unsigned pid = 0;
    std::set<unsigned> threads;
    std::map<Key,unsigned> samples;
    std::map<Key,std::vector<unsigned long long>> stacks;
    unsigned long long first = 0, last = 0;
    unsigned long long stackEvents = 0, unsupported = 0;
};

void WINAPI OnEvent(EVENT_RECORD* ev) {
    auto& out = *static_cast<Trace*>(ev->UserContext);
    const auto& h = ev->EventHeader;
    const auto* data = static_cast<const unsigned char*>(ev->UserData);
    const auto size = ev->UserDataLength;
    const auto opcode = h.EventDescriptor.Opcode;
    const bool wide = !(h.Flags & EVENT_HEADER_FLAG_32_BIT_HEADER);
    if (opcode == 46 && IsEqualGUID(h.ProviderId,perfProvider)) {
        if (!wide || !data || size < 16) {
            ++out.unsupported;
            return;
        }
        const auto qpc = static_cast<unsigned long long>(h.TimeStamp.QuadPart);
        out.first = out.first ? (std::min)(out.first,qpc) : qpc;
        out.last = (std::max)(out.last,qpc);
        const auto tid = Read<unsigned>(data+8);
        if (out.threads.count(tid)) out.samples.emplace(Key{qpc,tid},data[14] & 3);
    } else if (opcode == 32 && IsEqualGUID(h.ProviderId,stackProvider)) {
        if (!data || size < 16 || Read<unsigned>(data+8) != out.pid) return;
        const auto tid = Read<unsigned>(data+12);
        if (!out.threads.count(tid)) return;
        ++out.stackEvents;
        if (!wide || size < 24 || (size-16)%8) {
            ++out.unsupported;
            return;
        }
        const auto qpc = Read<unsigned long long>(data);
        auto& current = out.stacks[{qpc,tid}];
        std::vector<unsigned long long> observed;
        for (unsigned i=16;i<size;i+=8) {
            const auto ip = Read<unsigned long long>(data+i);
            if (ip) observed.push_back(ip);
        }
        const auto userFrames = [](const auto& frames) {
            return std::count_if(frames.begin(),frames.end(),[](auto ip) { return ip < 0x0000800000000000ull; });
        };
        // ETW can issue separate kernel and user walks for the same sample.
        // Preserve a single observation per (QPC, TID), preferring the user stack.
        const auto userCount = userFrames(observed);
        const auto oldUserCount = userFrames(current);
        if (userCount > oldUserCount || (userCount == oldUserCount && observed.size() > current.size()))
            current = std::move(observed);
    }
}

int Extract(wchar_t** argv) {
    Trace result;
    result.pid = std::stoul(argv[4]);
    const std::wstring ids = argv[5];
    std::size_t start = 0;
    while (start < ids.size()) {
        std::size_t count = 0;
        result.threads.insert(std::stoul(ids.substr(start),&count));
        start += count;
        if (start < ids.size() && ids[start++] != L',') return 2;
    }
    if (!result.pid || result.threads.empty()) return 2;
    EVENT_TRACE_LOGFILEW log{};
    log.LogFileName = argv[2];
    log.ProcessTraceMode = PROCESS_TRACE_MODE_EVENT_RECORD | PROCESS_TRACE_MODE_RAW_TIMESTAMP;
    log.EventRecordCallback = OnEvent;
    log.Context = &result;
    const auto trace = OpenTraceW(&log);
    if (trace == INVALID_PROCESSTRACE_HANDLE) {
        std::fprintf(stderr,"OpenTrace: %lu\n",GetLastError());
        return 3;
    }
    if (log.LogfileHeader.ReservedFlags != 1 || log.LogfileHeader.PointerSize != 8) {
        CloseTrace(trace);
        std::fprintf(stderr,"Stack ETL requires x64 and raw QPC\n");
        return 4;
    }
    auto handle = trace;
    const auto status = ProcessTrace(&handle,1,nullptr,nullptr);
    CloseTrace(trace);
    if (status != ERROR_SUCCESS) {
        std::fprintf(stderr,"ProcessTrace: %lu\n",status);
        return 5;
    }
    FILE* file = nullptr;
    if (_wfopen_s(&file,argv[3],L"wb") || !file) return 6;
    std::fputs("qpc,tid,interrupt_flags,ips\n",file);
    unsigned long long matched = 0;
    for (const auto& [key,stack] : result.stacks) {
        const auto sample = result.samples.find(key);
        if (sample == result.samples.end() || stack.empty()) continue;
        std::fprintf(file,"%llu,%u,%u,",key.first,key.second,sample->second);
        for (const auto ip : stack) std::fprintf(file,"%llx ",ip);
        std::fputc('\n',file);
        ++matched;
    }
    if (std::fclose(file) || !matched) {
        std::fprintf(stderr,"No usable joined stack samples, profile samples=%zu stack events=%llu unsupported=%llu\n",
            result.samples.size(),result.stackEvents,result.unsupported);
        return 7;
    }
    std::printf("{\"qpc_frequency\":%lld,\"first_cpu_sample_qpc\":%llu,\"last_cpu_sample_qpc\":%llu,"
        "\"target_samples\":%zu,\"stack_events\":%llu,\"matched_stack_samples\":%llu,\"unsupported\":%llu,"
        "\"events_lost\":%lu,\"buffers_lost\":%lu}\n",
        log.LogfileHeader.PerfFreq.QuadPart,result.first,result.last,result.samples.size(),
        result.stackEvents,matched,result.unsupported,log.LogfileHeader.EventsLost,log.LogfileHeader.BuffersLost);
    return 0;
}

struct SymbolOutput { FILE* file; DWORD64 base; std::size_t count = 0; };
BOOL CALLBACK OnSymbol(PSYMBOL_INFO info,ULONG size,void* context) {
    auto& out = *static_cast<SymbolOutput*>(context);
    // SymTagFunction is 5. Exclude export labels and symbols without an extent.
    if (info->Tag != 5 || !size || info->Address < out.base) return TRUE;
    std::string name(info->Name,info->NameLen);
    for (char& ch : name) if (ch == '\t' || ch == '\r' || ch == '\n') ch = ' ';
    std::fprintf(out.file,"%llx\t%lx\t%s\n",info->Address-out.base,size,name.c_str());
    ++out.count;
    return TRUE;
}

int IndexSymbols(wchar_t** argv) {
    const auto proc = GetCurrentProcess();
    SymSetOptions(SYMOPT_UNDNAME | SYMOPT_EXACT_SYMBOLS | SYMOPT_NO_PROMPTS | SYMOPT_FAIL_CRITICAL_ERRORS);
    if (!SymInitializeW(proc,argv[3],FALSE)) return 8;
    constexpr DWORD64 base = 0x140000000ull;
    const auto load = SymLoadModuleExW(proc,nullptr,argv[2],nullptr,base,0,nullptr,0);
    IMAGEHLP_MODULEW64 module{};
    module.SizeOfStruct = sizeof(module);
    if (!load || !SymGetModuleInfoW64(proc,load,&module) || module.SymType != SymPdb) {
        std::fprintf(stderr,"Exact PDB load failed: %lu\n",GetLastError());
        SymCleanup(proc);
        return 9;
    }
    FILE* file = nullptr;
    if (_wfopen_s(&file,argv[4],L"wb") || !file) {
        SymCleanup(proc);
        return 10;
    }
    SymbolOutput output{file,base};
    const auto ok = SymEnumSymbols(proc,base,nullptr,OnSymbol,&output);
    const auto close = std::fclose(file);
    SymCleanup(proc);
    std::printf("Exact PDB: %zu function extents\n",output.count);
    return ok && !close && output.count ? 0 : 11;
}
}

int wmain(int argc,wchar_t** argv) {
    try {
        if (argc == 6 && std::wstring(argv[1]) == L"--extract") return Extract(argv);
        if (argc == 5 && std::wstring(argv[1]) == L"--index") return IndexSymbols(argv);
    } catch (const std::exception& e) {
        std::fprintf(stderr,"%s\n",e.what());
    }
    return 2;
}
