#include "stdafx.h"
#include "PacingDiagnostics.h"
#include <TraceLoggingProvider.h>
#include <atomic>
#include <memory>
#include <cstdio>
#include <string>
#include <algorithm>
#pragma comment(lib, "advapi32.lib")

TRACELOGGING_DEFINE_PROVIDER(g_ixrayPacing, "IXRay.Pacing",
    (0xa6b3f9d1,0x865e,0x4c3d,0xa8,0x5b,0x31,0xc2,0xe7,0x10,0x13,0x60));

namespace PacingDiag
{
    namespace
    {
        bool Flag(const wchar_t* name) {
            wchar_t v[2] = {};
            return GetEnvironmentVariableW(name, v, 2) == 1 && v[0] == L'1';
        }
        struct Row {
            unsigned long long start, end, payload;
            unsigned frame, tid, kind;
        };
        struct State {
            static constexpr unsigned capacity = 1048576;
            std::unique_ptr<Row[]> rows;
            std::atomic<unsigned> next{0}, dropped{0}, frame{0};
            unsigned long long frequency = 0, origin = 0, utc = 0, uncertainty = 0;
            unsigned long long syncUntil = 0;
            HANDLE sync = nullptr;
            bool flushed = false;
            std::wstring path;
            State() {
                // Commit/prefault once before gameplay; never grow the buffer.
                rows.reset(new Row[capacity]());
                LARGE_INTEGER f, a, b;
                QueryPerformanceFrequency(&f); frequency = f.QuadPart;
                QueryPerformanceCounter(&a);
                FILETIME ft;
                using PreciseTime = void (WINAPI*)(LPFILETIME);
                const auto preciseTime = reinterpret_cast<PreciseTime>(GetProcAddress(GetModuleHandleW(L"kernel32.dll"),"GetSystemTimePreciseAsFileTime"));
                if (preciseTime) preciseTime(&ft); else GetSystemTimeAsFileTime(&ft);
                QueryPerformanceCounter(&b);
                origin = a.QuadPart + (b.QuadPart-a.QuadPart)/2;
                uncertainty = (b.QuadPart-a.QuadPart+1)/2;
                utc = (static_cast<unsigned long long>(ft.dwHighDateTime)<<32)|ft.dwLowDateTime;
                wchar_t directory[32768] = {};
                const DWORD n = GetEnvironmentVariableW(L"IXRAY_PACING_DIR",directory,32768);
                if (!n || n >= 32768) GetCurrentDirectoryW(32768,directory);
                path = std::wstring(directory)+L"\\ixray_pacing_"+std::to_wstring(GetCurrentProcessId())+L".csv";
                const auto name = L"Local\\IXRayPacingSync_"+std::to_wstring(GetCurrentProcessId());
                sync = CreateEventW(nullptr,FALSE,FALSE,name.c_str());
                TraceLoggingRegister(g_ixrayPacing);
                TraceLoggingWrite(g_ixrayPacing,"Clock",
                    TraceLoggingUInt64(origin,"QPC"),TraceLoggingUInt64(frequency,"Frequency"),
                    TraceLoggingUInt64(utc,"UTCFiletime"),TraceLoggingUInt64(uncertainty,"UncertaintyTicks"));
            }
            void Write() {
                if (flushed) return;
                flushed = true;
                FILE* file = nullptr;
                if (_wfopen_s(&file,path.c_str(),L"wb") || !file) return;
                const unsigned count = (std::min)(next.load(),capacity);
                fprintf(file,"#version=1,pid=%lu,qpc_frequency=%llu,qpc_origin=%llu,utc_filetime=%llu,qpc_origin_uncertainty_ticks=%llu,capacity=%u,dropped=%u,deep=%u\n",
                    GetCurrentProcessId(),frequency,origin,utc,uncertainty,capacity,dropped.load(),Deep()?1:0);
                fprintf(file,"kind,frame,thread_id,qpc_start,qpc_end,payload\n");
                for (unsigned i=0;i<count;++i) {
                    const auto& r=rows[i];
                    fprintf(file,"%u,%u,%u,%llu,%llu,%llu\n",r.kind,r.frame,r.tid,r.start,r.end,r.payload);
                }
                fclose(file);
            }
            ~State() { Write();TraceLoggingUnregister(g_ixrayPacing);if(sync)CloseHandle(sync); }
        };
        State& Data() { static State state;return state; }
    }
    bool Enabled() { static const bool enabled=Flag(L"IXRAY_PACING");return enabled; }
    bool Deep() { static const bool enabled=Enabled()&&Flag(L"IXRAY_PACING_DEEP");return enabled; }
    unsigned long long Counter() { LARGE_INTEGER q;QueryPerformanceCounter(&q);return q.QuadPart; }
    unsigned CurrentFrame() { return Data().frame.load(std::memory_order_relaxed); }
    void SetFrame(unsigned frame,unsigned flags,unsigned gameTime) {
        if(!Enabled())return;
        auto& s=Data();s.frame.store(frame,std::memory_order_relaxed);
        const auto q=Counter();
        Record(Kind::FrameState,frame,q,q,(static_cast<unsigned long long>(flags)<<32)|gameTime);
        // Only an explicit marker-helper request starts the optional video square.
        if(s.sync&&WaitForSingleObject(s.sync,0)==WAIT_OBJECT_0)s.syncUntil=q+s.frequency/5;
    }
    bool SyncVisible() { return Enabled()&&Data().syncUntil>Counter(); }
    void Record(Kind kind,unsigned frame,unsigned long long begin,unsigned long long end,unsigned long long payload) {
        if(!Enabled())return;
        auto& s=Data();
        // Deep-only per-poll/per-occlusion events retain long waits, not millions of tiny queries.
        if((kind==Kind::Occlusion||kind==Kind::Pump)&&(end-begin)<s.frequency/2000)return;
        const unsigned i=s.next.fetch_add(1,std::memory_order_relaxed);
        if(i>=State::capacity){s.dropped.fetch_add(1,std::memory_order_relaxed);return;}
        const unsigned tid=GetCurrentThreadId();
        s.rows[i]={begin,end,payload,frame,tid,static_cast<unsigned>(kind)};
        // ETW contains clock anchors, all Presents, and intervals >=1ms.
        // CSV contains fast spans too; ETW does not format names or write our own files.
        if(kind==Kind::Present||kind==Kind::SyncPaint||kind==Kind::SyncFailure||(end-begin)>=s.frequency/1000)
            TraceLoggingWrite(g_ixrayPacing,"Span",
                TraceLoggingUInt32(static_cast<unsigned>(kind),"Kind"),TraceLoggingUInt32(frame,"Frame"),
                TraceLoggingUInt64(begin,"QPCStart"),TraceLoggingUInt64(end,"QPCEnd"),TraceLoggingUInt64(payload,"Payload"));
    }
    void Flush() { if(Enabled())Data().Write(); }
}
