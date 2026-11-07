#pragma once

#include <algorithm>
#include <cstdint>
#include <iterator>

namespace DetailGridShift
{
inline bool CoversGrid(int oldX, int oldZ, int newX, int newZ, unsigned side)
{
    const auto x = std::int64_t(newX) - oldX;
    const auto z = std::int64_t(newZ) - oldZ;
    const auto width = std::int64_t(side);
    return x >= width || x <= -width || z >= width || z <= -width;
}

template<class Grid>
void Rotate(Grid& grid, std::int64_t deltaX, std::int64_t deltaZ)
{
    const auto side = std::int64_t(grid.size());
    const auto x = (deltaX % side + side) % side;
    const auto z = (-deltaZ % side + side) % side;
    for (auto& row : grid)
        std::rotate(row.begin(), std::next(row.begin(), x), row.end());

    // Rotate pointers between rows, never move the rows. CacheSlot1 keeps
    // pointers to the addresses of individual cells in these rows.
    for (std::int64_t column = 0; column < side && z; ++column)
    {
        auto reverse = [&](std::int64_t first, std::int64_t last) {
            while (first < --last)
                std::swap(grid[first++][column], grid[last][column]);
        };
        reverse(0, z);
        reverse(z, side);
        reverse(0, side);
    }
}
}
