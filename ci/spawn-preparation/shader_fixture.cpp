#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <d3d11shader.h>
#include <d3dcompiler.h>
#include <immintrin.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

using Microsoft::WRL::ComPtr;
namespace fs = std::filesystem;
using u8 = unsigned char;
using u32 = unsigned;
using string_path = char[1024];

struct xr_string : std::string {
    using std::string::string;
    static std::string ToString(u32 value) { return std::to_string(value); }
};
struct StringHash {
    size_t operator()(const xr_string& value) const { return std::hash<std::string_view>{}(value); }
};
using OptionMap = std::unordered_map<xr_string, xr_string, StringHash>;
static void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
#define VERIFY(x) require((x), #x)
#define _RELEASE(x) do { if (x) (x)->Release(); } while (false)
#define _VER ""
#ifndef D3D_OK
constexpr HRESULT D3D_OK = S_OK;
#endif
#define xr_sprintf sprintf_s
#define xr_strlen strlen
#define xr_strcmp strcmp
#define xr_strcpy strcpy_s
#define xr_strcat strcat_s

template<size_t N, class... Pieces> void xr_strconcat(char (&out)[N], Pieces... pieces) {
    strcpy_s(out, (std::string{} + ... + pieces).c_str());
}
template<class T> T* xr_alloc(size_t size) { return new T[size]; }
void xr_free(LPCVOID p) { delete[] static_cast<const u8*>(p); }
template<class... T> void Msg(const char* format, T... args) {
    std::printf(format, args...);
    std::putchar('\n');
}
u32 crc32(const void* p, size_t size, u32 previous = 0) {
    auto* data = static_cast<const u8*>(p);
    u32 crc = ~previous;
    for (size_t i = 0; i < size; ++i)
        crc = _mm_crc32_u8(crc, data[i]);
    return crc;
}

struct IReader {
    std::vector<u8> bytes;
    size_t pos = 0;
    void* pointer() const { return const_cast<u8*>(bytes.data() + pos); }
    u32 length() const { return static_cast<u32>(bytes.size()); }
    u32 elapsed() const { return length() - static_cast<u32>(pos); }
    u32 r_u32() { u32 value; std::memcpy(&value, pointer(), 4); pos += 4; return value; }
};
struct IWriter {
    std::ofstream stream;
    bool valid() const { return bool(stream); }
    void w(const void* data, u32 size) { stream.write(static_cast<const char*>(data), size); }
    void w_u32(u32 value) { w(&value, 4); }
};
struct FileSystem {
    fs::path cacheRoot, shaderRoot;
    bool exist(const char* name) const { return fs::is_regular_file(name); }
    IReader* r_open(const char* name) {
        std::ifstream in(name, std::ios::binary);
        if (!in) return nullptr;
        auto result = std::make_unique<IReader>();
        result->bytes.assign(std::istreambuf_iterator<char>(in), {});
        return result.release();
    }
    IReader* r_open(const char*, const char* name) { return r_open((shaderRoot / name).string().c_str()); }
    void r_close(IReader*& file) { delete file; file = nullptr; }
    template<size_t N> void update_path(char (&path)[N], const char*, const char* name) {
        strcpy_s(path, (cacheRoot / name).lexically_normal().string().c_str());
    }
    IWriter* w_open(const char* name) {
        fs::create_directories(fs::path(name).parent_path());
        return new IWriter{std::ofstream(name, std::ios::binary)};
    }
    void w_close(IWriter*& file) { delete file; file = nullptr; }
} FS;

enum {
    RFLAG_CLOUD_SHADOWS = 1, R4FLAG_SCREEN_SPACE_HUD_SHADOWS = 2, R4FLAG_HASHED_ALPHA_TEST = 4,
    R4FLAG_SSLR_ON_WATER = 8, R2FLAG_SOFT_WATER = 16, R2FLAG_SOFT_PARTICLES = 32,
    R2FLAG_DOF = 64, R2FLAG_STEEP_PARALLAX = 128, RFLAG_USE_CACHE = 256
};
struct Bits {
    unsigned flags = 0;
    bool test(unsigned bit) const { return (flags & bit) != 0; }
};
Bits ps_r__common_flags{RFLAG_USE_CACHE};
const Bits ps_r2_ls_flags_ext{RFLAG_CLOUD_SHADOWS | R4FLAG_SCREEN_SPACE_HUD_SHADOWS |
    R4FLAG_HASHED_ALPHA_TEST | R4FLAG_SSLR_ON_WATER};
const Bits ps_r2_ls_flags{R2FLAG_SOFT_WATER | R2FLAG_SOFT_PARTICLES | R2FLAG_STEEP_PARALLAX};
const int ps_r_sun_shafts = 3, ps_r_sun_quality = 3;
const auto RFeatureLevel = D3D_FEATURE_LEVEL_11_0;
const bool g_dedicated_server = false;
namespace ECoreParams { enum { renderdoc = 1, dxdebug = 2 }; }
struct { Bits ParamsData; } Core;
struct { struct { int skinning = -1; int GetSkinningMode() const { return skinning; } } External; } Engine;
struct ExternalConfig { OptionMap ShadersOptions{{"USE_LEGACY_LIGHT", "1"}}; };
const ExternalConfig& EngineExternal() { static const ExternalConfig config; return config; }

struct CRender {
    using ShaderOptions = OptionMap;
    ShaderOptions m_ShaderOptions;
    struct { int smapsize = 2048; bool sunstatic = false, offscreen_reflecitons = false,
        deffered_reflecitons = false, disasm = false; } o;
    LPCSTR getShaderPath() const { return "d3d11\\"; }
    xr_string getShaderParams();
    template<class Options> static xr_string ShaderParams(const Options&);
    HRESULT shader_compile(LPCSTR, DWORD const*, UINT, LPCSTR, LPCSTR, DWORD, void*&);
    template<class Options>
    HRESULT CompileShader(LPCSTR, DWORD const*, UINT, LPCSTR, LPCSTR, DWORD, void*&, const Options&, int, bool);
    void PrewarmPacingShaderCache();
} renderer;
CRender* Render = &renderer;
ComPtr<ID3D11Device> device;
HRESULT create_shader(LPCSTR target, DWORD* data, u32 size, LPCSTR path, void*& result, bool) {
    static_cast<std::vector<u8>*>(result)->assign(reinterpret_cast<u8*>(data), reinterpret_cast<u8*>(data) + size);
    if (std::strstr(path, "forward_base_")) {
        // The PDA alpha shader already executes on the target hardware. The
        // fixture validates its DXBC and tests the exact cache read/compile path.
        ComPtr<ID3D11ShaderReflection> reflection;
        const HRESULT hr = D3DReflect(data, size, __uuidof(ID3D11ShaderReflection),
            reinterpret_cast<void**>(reflection.GetAddressOf()));
        if (FAILED(hr))
            return hr;
        D3D11_SHADER_DESC desc{};
        return reflection->GetDesc(&desc);
    }
    if (target[0] == 'v') {
        ComPtr<ID3D11VertexShader> shader;
        return device->CreateVertexShader(data, size, nullptr, shader.GetAddressOf());
    }
    ComPtr<ID3D11PixelShader> shader;
    return device->CreatePixelShader(data, size, nullptr, shader.GetAddressOf());
}

int compilerCalls = 0;
template<class... Args> HRESULT countCompile(Args... args) {
    ++compilerCalls;
    return D3DCompile(args...);
}
#define D3DCompile countCompile
#include "renderer.inc"
#undef D3DCompile

int main(int argc, char** argv) try {
    require(argc == 3, "usage: fixture shader-root test-root");
    FS.shaderRoot = argv[1];
    const fs::path testRoot = argv[2];
    FS.cacheRoot = testRoot / "warm";
    require(SUCCEEDED(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, 0, nullptr, 0,
        D3D11_SDK_VERSION, device.GetAddressOf(), nullptr, nullptr)), "WARP device");
    renderer.PrewarmPacingShaderCache();
    require(compilerCalls == 8, "eight fresh prewarm compiles");
    renderer.PrewarmPacingShaderCache();
    require(compilerCalls == 8, "valid variants are reused by prewarm");
    struct Request {
        const char* base;
        const char* key;
        const char* mask;
        int skinning;
        bool pixel;
        bool bumped;
        bool alpha = false;
        bool high = false;
    };
    constexpr Request requests[] = {
        {"model_distort", "model_distort_3_3182295050", "2048100000101001011133101", 3, false, false},
        {"model_distort", "model_distort_4_3182295050", "2048100000011001011133101", 4, false, false},
        {"model_distort4ghost", "model_distort4ghost_0_3182295050", "2048100100001001011133101", 0, false, false},
        {"model_distort4ghost", "model_distort4ghost_1_3182295050", "2048100010001001011133101", 1, false, false},
        {"deffer_model", "deffer_model_4_11943794", "2048100000011001011133101", 4, false, true, false, true},
        {"particle_hard", "particle_hard_3182295050", "2048100000011001011133101", 4, true, false},
        {"forward_base", "forward_base_1903968529", "2048100100001001011133101", 0, true, true, true, false},
        {"forward_base", "forward_base_4131883862", "2048100100001001011133101", 0, true, true, true, true},
    };
    for (const auto& request : requests) {
        std::cout << "Verify cache key " << request.key << std::endl;
        FS.cacheRoot = testRoot / "warm";
        const auto file = FS.cacheRoot / "shaders_cache/d3d11" /
            (std::string(request.key) + (request.pixel ? ".ps" : ".vs")) / request.mask;
        require(fs::is_regular_file(file), request.key);
        const auto sourcePath = std::string("d3d11/") + request.base + (request.pixel ? ".ps.hlsl" : ".vs.hlsl");
        std::unique_ptr<IReader> source(FS.r_open("$game_shaders$", sourcePath.c_str()));
        require(bool(source), "stock source");
        renderer.m_ShaderOptions = EngineExternal().ShadersOptions;
        if (request.bumped) {
            // Locate the engine map iteration order observed in the gameplay cache key.
            std::vector<const char*> keys{"USE_BUMP", "USE_LEGACY_LIGHT"};
            if (request.alpha)
                keys.push_back("USE_AREF");
            if (request.high)
                keys.push_back("USE_HIGH_QUALITY");
            std::sort(keys.begin(), keys.end(), [](const char* a, const char* b) { return std::strcmp(a, b) < 0; });
            const auto alphabetical = [](const char* a, const char* b) { return std::strcmp(a, b) < 0; };
            do {
                renderer.m_ShaderOptions.clear();
                for (const auto* key : keys)
                    renderer.m_ShaderOptions[key] = "1";
                if (std::string_view(request.key).ends_with(renderer.getShaderParams()))
                    break;
            } while (std::next_permutation(keys.begin(), keys.end(), alphabetical));
        }
        require(std::string_view(request.key).ends_with(renderer.getShaderParams()), "runtime macro hash");
        Engine.External.skinning = request.skinning;
        auto normal = [&] {
            std::vector<u8> bytes;
            void* result = &bytes;
            require(SUCCEEDED(renderer.shader_compile(request.key, static_cast<DWORD*>(source->pointer()),
                source->length(), "main", request.pixel ? "ps_2_0" : "vs_2_0",
                D3DCOMPILE_PACK_MATRIX_ROW_MAJOR, result)), "normal path and WARP create");
            return bytes;
        };
        const int start = compilerCalls;
        const auto warm = normal();
        require(start == compilerCalls, "normal shader creation used prewarmed bytecode");
        FS.cacheRoot = testRoot / "cold";
        const auto cold = normal();
        require(compilerCalls == start + 1 && warm == cold, "cold and prewarmed bytecode differ");
        FS.cacheRoot = testRoot / "warm";
        std::ofstream(file, std::ios::binary | std::ios::trunc).write("short", 5);
        require(normal() == cold && compilerCalls == start + 2, "truncated cache did not recover");
    }
    ps_r__common_flags.flags = 0;
    const auto calls = compilerCalls;
    renderer.PrewarmPacingShaderCache();
    require(compilerCalls == calls, "prewarm ignored disabled cache");
    std::cout << "PASS: eight observed cache keys, no recompile on warm create, byte-identical cold DXBC, "
                 "WARP creation for original variants, PDA DXBC reflection, truncated cache recovery, cache-off guard\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr << e.what() << '\n';
    return 1;
}
