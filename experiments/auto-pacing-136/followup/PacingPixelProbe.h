#pragma once

#include <d3d11.h>
#include <wrl/client.h>
#include <array>
#include <cstdint>

// Reads eight points from the final swap-chain texture, four frames behind.
class PacingPixelProbe
{
    using Texture = Microsoft::WRL::ComPtr<ID3D11Texture2D>;
    struct Slot {
        Texture texture;
        unsigned frame = 0;
        unsigned long long qpc = 0;
        bool pending = false;
    };
    std::array<Slot,4> slots_{};
    unsigned next_ = 0;
    DXGI_FORMAT format_ = DXGI_FORMAT_UNKNOWN;
    ID3D11Device* device_ = nullptr;
    bool available_ = false;
    static constexpr unsigned points_ = 8;

public:
    enum class Result { Submitted, Busy, Unsupported, Failed };
    void Reset() { *this = PacingPixelProbe{}; }

    template<class Record>
    Result Observe(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11RenderTargetView* view,
        unsigned frame, unsigned long long qpc, Record record)
    {
        if (!view) return Result::Unsupported;
        Microsoft::WRL::ComPtr<ID3D11Resource> resource;
        view->GetResource(&resource);
        Texture source;
        if (!resource || FAILED(resource.As(&source))) return Result::Unsupported;
        D3D11_TEXTURE2D_DESC desc{};
        source->GetDesc(&desc);
        if (desc.SampleDesc.Count != 1 || desc.Width < 8 || desc.Height < 4 ||
            (desc.Format != DXGI_FORMAT_B8G8R8A8_UNORM && desc.Format != DXGI_FORMAT_R8G8B8A8_UNORM))
            return Result::Unsupported;
        if (device_ != device || format_ != desc.Format) {
            Reset();
            device_ = device;
            format_ = desc.Format;
            D3D11_TEXTURE2D_DESC staging{};
            staging.Width = points_;
            staging.Height = staging.MipLevels = staging.ArraySize = staging.SampleDesc.Count = 1;
            staging.Format = format_;
            staging.Usage = D3D11_USAGE_STAGING;
            staging.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
            available_ = true;
            for (auto& slot : slots_) {
                if (FAILED(device->CreateTexture2D(&staging, nullptr, &slot.texture))) {
                    available_ = false;
                    break;
                }
            }
        }
        if (!available_) return Result::Failed;
        auto& slot = slots_[next_];
        if (slot.pending) {
            D3D11_MAPPED_SUBRESOURCE mapped{};
            const HRESULT status = context->Map(slot.texture.Get(), 0, D3D11_MAP_READ,
                D3D11_MAP_FLAG_DO_NOT_WAIT, &mapped);
            if (status == DXGI_ERROR_WAS_STILL_DRAWING) return Result::Busy;
            if (FAILED(status)) return Result::Failed;
            const auto* bytes = static_cast<const std::uint8_t*>(mapped.pData);
            unsigned long long levels = 0;
            const unsigned red = format_ == DXGI_FORMAT_B8G8R8A8_UNORM ? 2 : 0;
            for (unsigned i = 0; i < points_; ++i) {
                const unsigned level = (54u * bytes[i*4+red] + 183u * bytes[i*4+1] +
                    19u * bytes[i*4+2-red] + 128u) >> 8;
                levels |= static_cast<unsigned long long>(level) << (i*8);
            }
            context->Unmap(slot.texture.Get(), 0);
            record(slot.frame, slot.qpc, levels);
        }
        for (unsigned i = 0; i < points_; ++i) {
            const UINT x = desc.Width * (2*(i%4)+1) / 8;
            const UINT y = desc.Height * (2*(i/4)+1) / 4;
            const D3D11_BOX box{x,y,0,x+1,y+1,1};
            context->CopySubresourceRegion(slot.texture.Get(),0,i,0,0,source.Get(),0,&box);
        }
        slot.frame = frame;
        slot.qpc = qpc;
        slot.pending = true;
        next_ = (next_+1) % slots_.size();
        return Result::Submitted;
    }
};
