#pragma once

#include <memory>

namespace SpawnVoice
{
// The only consumer is the exact object whose net_Spawn is running.
// Nested dispatch restores the previous transaction on return.
class Scope
{
public:
    using Source = std::shared_ptr<const void>(*)(const void*);

private:
    static inline thread_local Scope* current_ = nullptr;
    Scope* previous_;
    const void* owner_;
    const void* context_;
    Source source_;
    unsigned registrations_ = 0;
    unsigned preparedNames_ = 0;

public:
    Scope(const void* owner, const void* context, Source source)
        : previous_(current_), owner_(owner), context_(context), source_(source)
    {
        current_ = this;
    }
    ~Scope() { current_ = previous_; }
    Scope(const Scope&) = delete;
    Scope& operator=(const Scope&) = delete;

    unsigned Registrations() const { return registrations_; }
    unsigned PreparedNames() const { return preparedNames_; }

    static void Mark(bool names)
    {
        if (current_)
        {
            ++current_->registrations_;
            current_->preparedNames_ += names;
        }
    }

    static std::shared_ptr<const void> Prepared(const void* owner)
    {
        if (!owner || !current_ || current_->owner_ != owner || !current_->source_)
            return {};
        return current_->source_(current_->context_);
    }
};
}
