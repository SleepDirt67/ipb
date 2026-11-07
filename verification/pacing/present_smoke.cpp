#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11_1.h>
#define ENGINE_API
#include "PacingDiagnostics.h"
#include <cstdio>
#include <string>
#include <fstream>
#include <filesystem>
int wmain(int argc,wchar_t** argv) {
    if(argc!=2)return 1;
    SetEnvironmentVariableW(L"IXRAY_PACING",L"1");
    SetEnvironmentVariableW(L"IXRAY_PACING_DIR",argv[1]);
    WNDCLASSW wc{};wc.lpfnWndProc=DefWindowProcW;wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"IXRayPacingSmoke";
    if(!RegisterClassW(&wc))return 2;
    HWND window=CreateWindowW(wc.lpszClassName,L"Pacing capture fixture",WS_OVERLAPPEDWINDOW,0,0,320,240,nullptr,nullptr,wc.hInstance,nullptr);
    if(!window)return 3;ShowWindow(window,SW_SHOWNOACTIVATE);
    DXGI_SWAP_CHAIN_DESC desc{};desc.BufferDesc.Width=320;desc.BufferDesc.Height=240;desc.BufferDesc.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.SampleDesc.Count=1;desc.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;desc.BufferCount=1;desc.OutputWindow=window;desc.Windowed=TRUE;desc.SwapEffect=DXGI_SWAP_EFFECT_DISCARD;
    ID3D11Device* device=nullptr;ID3D11DeviceContext* context=nullptr;IDXGISwapChain* swap=nullptr;
    HRESULT hr=D3D11CreateDeviceAndSwapChain(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&desc,&swap,&device,nullptr,&context);
    if(FAILED(hr)){printf("WARP init HRESULT %08x\n",static_cast<unsigned>(hr));return 4;}
    ID3D11Texture2D* buffer=nullptr;ID3D11RenderTargetView* view=nullptr;
    if(FAILED(swap->GetBuffer(0,__uuidof(ID3D11Texture2D),reinterpret_cast<void**>(&buffer))))return 5;
    if(FAILED(device->CreateRenderTargetView(buffer,nullptr,&view)))return 6;
    ID3D11DeviceContext1* context1=nullptr;
    if(FAILED(context->QueryInterface(__uuidof(ID3D11DeviceContext1),reinterpret_cast<void**>(&context1))))return 7;
    D3D11_TEXTURE2D_DESC stagingDesc{};buffer->GetDesc(&stagingDesc);stagingDesc.Usage=D3D11_USAGE_STAGING;stagingDesc.BindFlags=0;stagingDesc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    ID3D11Texture2D* staging=nullptr;if(FAILED(device->CreateTexture2D(&stagingDesc,nullptr,&staging)))return 8;
    PacingDiag::SetFrame(0,17,0);
    {std::ofstream ready(std::filesystem::path(std::wstring(argv[1])+L"\\ready.txt"));ready<<GetCurrentProcessId();}
    bool checkedSquare=false;unsigned presentFailures=0;
    for(unsigned frame=1;frame<=500;++frame) {
        MSG message;while(PeekMessageW(&message,nullptr,0,0,PM_REMOVE)){TranslateMessage(&message);DispatchMessageW(&message);}
        PacingDiag::SetFrame(frame,17,frame*20);
        {
            PacingDiag::Span idle(PacingDiag::Kind::OnIdle);
            const FLOAT blue[4]={0.1f,0.2f,0.3f,1};context->ClearRenderTargetView(view,blue);
            if(PacingDiag::SyncVisible()) {
                const auto q=PacingDiag::Counter();const FLOAT white[4]={1,1,1,1};const D3D11_RECT rect={0,0,64,64};context1->ClearView(view,white,&rect,1);
                PacingDiag::Record(PacingDiag::Kind::SyncPaint,frame,q,PacingDiag::Counter());
                if(!checkedSquare) {
                    context->CopyResource(staging,buffer);D3D11_MAPPED_SUBRESOURCE mapped{};
                    if(FAILED(context->Map(staging,0,D3D11_MAP_READ,0,&mapped)))return 9;
                    const auto p=static_cast<const unsigned char*>(mapped.pData);
                    const auto outside=p+100*mapped.RowPitch+100*4;
                    checkedSquare=p[0]==255&&p[1]==255&&p[2]==255&&outside[0]<250&&outside[1]<250&&outside[2]<250;
                    context->Unmap(staging,0);
                    if(!checkedSquare)return 10;
                }
            }
            const auto q=PacingDiag::Counter();hr=swap->Present(0,0);
            PacingDiag::Record(PacingDiag::Kind::Present,frame,q,PacingDiag::Counter(),static_cast<unsigned>(hr));
            if(FAILED(hr))++presentFailures;
        }
        Sleep(20);
    }
    PacingDiag::Flush();staging->Release();context1->Release();view->Release();buffer->Release();swap->Release();context->Release();device->Release();DestroyWindow(window);
    printf("WARP Present fixture: 500 calls, failures=%u, explicit IPC square pixel+outside validation=%u\n",presentFailures,checkedSquare?1:0);
    return presentFailures||!checkedSquare?11:0;
}
