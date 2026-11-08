#pragma once

#include <chrono>

struct lua_State;

namespace DispatchSweep
{
using Control = int (*)(lua_State*, int, int);

class Window
{
    Control control_;
    lua_State* state_ = nullptr;

public:
    explicit Window(Control control) : control_(control) {}
    Window(const Window&) = delete;
    Window& operator=(const Window&) = delete;

    void Enter(lua_State* state)
    {
        if (!state_ && state && control_(state, -30100, 0) == 0)
            state_ = state;
    }

    int Exit()
    {
        if (!state_)
            return 0;
        lua_State* state = state_;
        state_ = nullptr;
        return control_(state, -30101, 0);
    }

    ~Window() { Exit(); }
};

// Called on the regular VM owner. The time limit is checked between quanta.
inline bool Maintain(Control control, lua_State* state, unsigned& quanta)
{
    if (!state || control(state, -30102, 0) != 1)
        return false;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::microseconds(200);
    while (quanta < 128 && std::chrono::steady_clock::now() < deadline &&
           control(state, -30103, 0) == 1)
        ++quanta;
    return true;
}
}
