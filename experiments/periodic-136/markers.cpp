#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <vector>
#include <string>
#include <cstdio>
#pragma comment(lib,"user32.lib")
struct Mark { unsigned id; unsigned long long qpc; bool sent; };
int wmain(int argc,wchar_t** argv) {
    if(argc!=3){fwprintf(stderr,L"Usage: ixray_pacing_marks.exe OUTPUT.csv GAME_PID\n");return 2;}
    const DWORD target=wcstoul(argv[2],nullptr,10);
    const auto eventName=L"Local\\IXRayPacingSync_"+std::to_wstring(target);
    std::vector<Mark> marks;marks.reserve(4096);
    for(unsigned i=0;i<5;++i)if(!RegisterHotKey(nullptr,100+i,MOD_WIN|MOD_NOREPEAT,VK_F8+i)){
        fprintf(stderr,"Cannot register Win+F%u; error=%lu\n",8+i,GetLastError());return 3;
    }
    HANDLE process=OpenProcess(SYNCHRONIZE,FALSE,target);
    if(!process){fprintf(stderr,"Cannot open game process %lu\n",target);return 4;}
    LARGE_INTEGER frequency;QueryPerformanceFrequency(&frequency);
    // Check game exit every second so normal game exit saves markers automatically.
    SetTimer(nullptr,1,1000,nullptr);
    puts("Win+F8: optional video sync square; F9: blink; F10: long freeze; F11: segment boundary; F12: stop markers.");
    MSG message{};bool done=false;
    while(!done&&GetMessageW(&message,nullptr,0,0)>0) {
        if(message.message==WM_TIMER&&WaitForSingleObject(process,0)==WAIT_OBJECT_0)break;
        if(message.message!=WM_HOTKEY)continue;
        LARGE_INTEGER q;QueryPerformanceCounter(&q);bool sent=false;
        const unsigned id=static_cast<unsigned>(message.wParam)-100;
        if(id==0){HANDLE event=OpenEventW(EVENT_MODIFY_STATE,FALSE,eventName.c_str());if(event){sent=SetEvent(event)!=FALSE;CloseHandle(event);}}
        if(marks.size()<4096)marks.push_back({id,static_cast<unsigned long long>(q.QuadPart),sent});
        else {fputs("Marker buffer full\n",stderr);break;}
        if(id==4)done=true;
    }
    FILE* file=nullptr;if(_wfopen_s(&file,argv[1],L"wb")||!file)return 5;
    fprintf(file,"#version=1,game_pid=%lu,qpc_frequency=%lld,meaning=arrival_after_human_reaction_not_exact_visual_onset\n",target,frequency.QuadPart);
    fprintf(file,"kind,qpc,sync_request_sent\n");
    const char* names[]={"video_sync_request","blink_observed","long_freeze_observed","segment_boundary","stop"};
    for(const auto& m:marks)fprintf(file,"%s,%llu,%u\n",names[m.id],m.qpc,m.sent?1:0);
    fclose(file);CloseHandle(process);for(unsigned i=0;i<5;++i)UnregisterHotKey(nullptr,100+i);
    return 0;
}
