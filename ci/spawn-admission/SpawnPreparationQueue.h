#pragma once

#include <array>
#include <condition_variable>
#include <cstdint>
#include <mutex>
#include <optional>
#include <thread>
#include <utility>

namespace SpawnPreparation
{
// One level owns one worker. Neither the producer nor the gameplay consumer
// waits for the worker. Its sole lifetime fence is level teardown.
template<class Input, class Output, class Prepare, std::size_t Capacity = 24>
class Queue
{
    enum class State { Empty, Pending, Running, Ready, Retired };
    struct Slot
    {
        State state = State::Empty;
        std::uint16_t object = 0;
        std::uint64_t sequence = 0;
        std::optional<Input> input;
        std::optional<Output> output;
    };

    Prepare prepare_;
    std::array<Slot, Capacity> slots_{};
    std::mutex mutex_;
    std::condition_variable work_;
    bool stopped_ = false;
    std::uint64_t sequence_ = 0;
    std::thread thread_;

    void Run()
    {
        std::unique_lock lock(mutex_);
        while (!stopped_)
        {
            Slot* pending = nullptr;
            for (auto& slot : slots_)
                if (slot.state == State::Pending &&
                    (!pending || slot.sequence < pending->sequence))
                    pending = &slot;
            if (!pending)
            {
                work_.wait(lock);
                continue;
            }
            pending->state = State::Running;
            auto input = std::move(*pending->input);
            pending->input.reset();
            lock.unlock();
            auto result = prepare_(input);
            lock.lock();
            if (stopped_)
                break;
            if (pending->state != State::Retired)
                pending->output = std::move(result);
            pending->state = pending->output ? State::Ready : State::Empty;
        }
    }

public:
    explicit Queue(Prepare prepare)
        : prepare_(std::move(prepare)), thread_([this] { Run(); }) {}
    ~Queue()
    {
        {
            std::lock_guard lock(mutex_);
            stopped_ = true;
        }
        work_.notify_one();
        thread_.join();
    }

    bool Submit(std::uint16_t object, const Input& input)
    {
        std::unique_lock lock(mutex_, std::try_to_lock);
        if (!lock.owns_lock())
            return false;
        Slot* empty = nullptr;
        Slot* oldestReady = nullptr;
        for (auto& slot : slots_)
        {
            if (slot.state != State::Empty && slot.object == object)
                return false;
            if (slot.state == State::Empty && !empty)
                empty = &slot;
            if (slot.state == State::Ready &&
                (!oldestReady || slot.sequence < oldestReady->sequence))
                oldestReady = &slot;
        }
        auto* slot = empty ? empty : oldestReady;
        if (!slot)
            return false;
        slot->object = object;
        slot->sequence = ++sequence_;
        slot->output.reset();
        slot->input = input;
        slot->state = State::Pending;
        lock.unlock();
        work_.notify_one();
        return true;
    }

    std::optional<Output> Take(std::uint16_t object)
    {
        std::unique_lock lock(mutex_, std::try_to_lock);
        if (!lock.owns_lock())
            return {};
        for (auto& slot : slots_)
        {
            if (slot.state == State::Empty || slot.object != object)
                continue;
            if (slot.state == State::Ready)
            {
                auto result = std::move(slot.output);
                slot.output.reset();
                slot.state = State::Empty;
                return result;
            }
            return {};
        }
        return {};
    }

    void Retire(std::uint16_t object)
    {
        std::unique_lock lock(mutex_, std::try_to_lock);
        if (!lock.owns_lock())
            return;
        for (auto& slot : slots_)
        {
            if (slot.state == State::Empty || slot.object != object)
                continue;
            slot.input.reset();
            slot.output.reset();
            slot.state = slot.state == State::Running || slot.state == State::Retired
                ? State::Retired : State::Empty;
            return;
        }
    }
};
}
