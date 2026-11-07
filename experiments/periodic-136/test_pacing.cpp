#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#define ENGINE_API
#include "PacingDiagnostics.h"
#include <thread>
#include <vector>
#include <cassert>
#include <string>
#include <cstdio>
#undef NDEBUG
int main(int argc,char** argv) {
    if(argc>1 && std::string(argv[1])=="disabled") {
        SetEnvironmentVariableW(L"IXRAY_PACING",L"0");
        for(unsigned i=0;i<100000;++i){PacingDiag::SetFrame(i,0,0);PacingDiag::Span span(PacingDiag::Kind::OnIdle);}
        PacingDiag::Flush();puts("Pacing disabled: no buffer, event or output initialized");return 0;
    }
    SetEnvironmentVariableW(L"IXRAY_PACING",L"1");
    SetEnvironmentVariableW(L"IXRAY_PACING_DEEP",L"1");
    PacingDiag::SetFrame(123,17,456);
    const auto name=L"Local\\IXRayPacingSync_"+std::to_wstring(GetCurrentProcessId());
    const auto event=OpenEventW(EVENT_MODIFY_STATE,FALSE,name.c_str());
    if(!event||!SetEvent(event))return 2;
    CloseHandle(event);PacingDiag::SetFrame(124,17,457);
    if(!PacingDiag::SyncVisible())return 3;
    std::vector<std::thread> threads;
    for(unsigned k=0;k<4;++k)threads.emplace_back([=]{
        for(unsigned i=0;i<(argc>1?300000u:50000u);++i){
            const auto q=PacingDiag::Counter();
            PacingDiag::Record(PacingDiag::Kind::Present,124,q,PacingDiag::Counter(),k);
        }
    });
    for(auto& t:threads)t.join();
    {PacingDiag::Span span(PacingDiag::Kind::WaitWorkers);Sleep(3);}
    PacingDiag::Flush();puts("Pacing concurrent capture / sync event / bounded overflow fixture completed");
}
