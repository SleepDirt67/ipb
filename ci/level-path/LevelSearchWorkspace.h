#pragma once

#include <algorithm>
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
        bool expanded;
    };
    static constexpr std::size_t maxBoundaryChecks = 4096;
    static constexpr unsigned pageBits = 10;
    static constexpr unsigned pageSize = 1u << pageBits;
    using Page = std::array<Node, pageSize>;
    std::vector<std::unique_ptr<Page>> pages_;
    std::uint32_t generation_ = 0;
    std::uint32_t visited_ = 0;
    const void* graph_ = nullptr;
    std::uint64_t graphIdentity_ = 0;
    std::size_t probeWords_ = 0;
    struct Region
    {
        std::vector<std::uint64_t> reached;
        std::vector<std::uint32_t> boundary;

        bool Contains(std::uint32_t vertex) const
        {
            return vertex / 64 < reached.size() &&
                (reached[vertex / 64] & (std::uint64_t{1} << (vertex % 64))) != 0;
        }
    };
    Region probe_, proven_;
    std::vector<std::uint64_t> blocked_;

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

    static bool SetBit(std::vector<std::uint64_t>& bits, std::uint32_t vertex)
    {
        auto& word = bits[vertex / 64];
        const auto bit = std::uint64_t{1} << (vertex % 64);
        const bool fresh = (word & bit) == 0;
        word |= bit;
        return fresh;
    }

    void AddProbeVertex(std::uint32_t vertex)
    {
        if (SetBit(probe_.reached, vertex))
            probeQueue_.push_back(vertex);
    }

public:
    void Begin(const void* graph, std::uint64_t identity, std::size_t vertexCount)
    {
        if (graph_ != graph || graphIdentity_ != identity)
        {
            proven_.reached.clear();
            proven_.boundary.clear();
            graph_ = graph;
            graphIdentity_ = identity;
            generation_ = 0;
            pages_.clear();
        }
        if (++generation_ == 0)
        {
            pages_.clear();
            generation_ = 1;
        }
        probeWords_ = (vertexCount + 63) / 64;
        visited_ = reopenings_ = 0;
        probeQueue_.clear();
        probeHead_ = 0;
        probeFoundTarget_ = false;
    }

    template<class IsAccessible>
    bool ReuseProof(std::uint32_t start, std::uint32_t target, const IsAccessible& accessible) const
    {
        // With all recorded exits still closed, no path can leave this
        // region. Newly blocked vertices inside it cannot invalidate that.
        return proven_.Contains(start) && !proven_.Contains(target) &&
            proven_.boundary.size() <= maxBoundaryChecks &&
            std::none_of(proven_.boundary.begin(), proven_.boundary.end(), accessible);
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
        {
            probe_.reached.assign(probeWords_, 0);
            probe_.boundary.clear();
            blocked_.assign(probeWords_, 0);
            AddProbeVertex(start);
        }
        auto budget = reopenings_ == initialWork ? initialWork : batch;
        while (probeHead_ != probeQueue_.size() && budget-- != 0)
        {
            const auto vertex = probeQueue_[probeHead_++];
            visit(vertex, [&](std::uint32_t next, bool accessible) {
                if (!accessible)
                {
                    if (probe_.boundary.size() <= maxBoundaryChecks && SetBit(blocked_, next))
                        probe_.boundary.push_back(next);
                }
                else if (next == target)
                    probeFoundTarget_ = true;
                else
                    AddProbeVertex(next);
            });
            if (probeFoundTarget_)
                return false;
        }
        if (probeHead_ != probeQueue_.size())
            return false;
        std::swap(proven_, probe_);
        return true;
    }

    std::uint32_t Visited() const { return visited_; }
};
}
