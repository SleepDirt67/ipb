#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <vector>

namespace LevelSearch
{
class Workspace
{
    struct Node
    {
        float cost;
        std::uint32_t parent;
        std::uint32_t generation;
        std::uint32_t probeGeneration;
        bool expanded;
    };
    static constexpr unsigned pageBits = 10;
    static constexpr unsigned pageSize = 1u << pageBits;
    using Page = std::array<Node, pageSize>;
    std::vector<std::unique_ptr<Page>> pages_;
    std::uint32_t generation_ = 0;
    std::uint32_t visited_ = 0;
    const void* graph_ = nullptr;
    std::vector<std::uint32_t> probeQueue_;
    std::size_t probeHead_ = 0;
    std::uint32_t reopenings_ = 0;
    bool probeFoundTarget_ = false;

    Node& Slot(std::uint32_t vertex)
    {
        const auto page = vertex >> pageBits;
        if (page >= pages_.size())
            pages_.resize(page + 1);
        auto& slot = pages_[page];
        if (!slot)
            slot = std::make_unique<Page>();
        return (*slot)[vertex & (pageSize - 1)];
    }

    void AddProbeVertex(std::uint32_t vertex)
    {
        auto& node = Slot(vertex);
        if (node.probeGeneration != generation_)
        {
            node.probeGeneration = generation_;
            probeQueue_.push_back(vertex);
        }
    }

public:
    void Begin(const void* graph)
    {
        if (graph_ != graph || ++generation_ == 0)
        {
            pages_.clear();
            graph_ = graph;
            generation_ = 1;
        }
        visited_ = reopenings_ = 0;
        probeQueue_.clear();
        probeHead_ = 0;
        probeFoundTarget_ = false;
    }

    const Node* Find(std::uint32_t vertex) const
    {
        const auto page = vertex >> pageBits;
        if (page >= pages_.size() || !pages_[page])
            return nullptr;
        const auto& node = (*pages_[page])[vertex & (pageSize - 1)];
        return node.generation == generation_ ? &node : nullptr;
    }

    void Set(std::uint32_t vertex, float cost, std::uint32_t parent)
    {
        auto& node = Slot(vertex);
        visited_ += node.generation != generation_;
        node.cost = cost;
        node.parent = parent;
        node.generation = generation_;
        node.expanded = false;
    }

    bool BeginExpansion(std::uint32_t vertex)
    {
        auto& node = Slot(vertex);
        if (node.expanded)
            return false;
        node.expanded = true;
        return true;
    }

    // An independent reachability proof is worthwhile only if A* keeps
    // lowering costs on known vertices. Its work is paid for by those
    // repeated relaxations. Finding the target merely disables the proof.
    template<class VisitNeighbors>
    bool ProveUnreachable(std::uint32_t start, std::uint32_t target, const VisitNeighbors& visit)
    {
        constexpr std::uint32_t initialWork = 2048;
        constexpr std::uint32_t batch = 128;
        if (probeFoundTarget_ || ++reopenings_ < initialWork || reopenings_ % batch != 0)
            return false;
        if (probeQueue_.empty())
            AddProbeVertex(start);
        auto budget = reopenings_ == initialWork ? initialWork : batch;
        while (probeHead_ != probeQueue_.size() && budget-- != 0)
        {
            const auto vertex = probeQueue_[probeHead_++];
            visit(vertex, [&](std::uint32_t next) {
                if (next == target)
                    probeFoundTarget_ = true;
                else
                    AddProbeVertex(next);
            });
            if (probeFoundTarget_)
                return false;
        }
        return probeHead_ == probeQueue_.size();
    }

    std::uint32_t Visited() const { return visited_; }
};
}
