#include "DetailGridShift.h"

#ifdef _WIN32
#include "PackedWaveView.h"
#endif

#include <array>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <vector>

static void Require(bool condition)
{
    if (!condition)
        std::abort();
}

using Grid = std::vector<std::vector<int>>;

static void OriginalRotate(Grid& grid, int x, int z)
{
    const auto side = int(grid.size());
    while (x != 0)
    {
        for (auto& row : grid)
            std::rotate(row.begin(), x > 0 ? row.begin() + 1 : row.end() - 1, row.end());
        x += x > 0 ? -1 : 1;
    }
    while (z != 0)
    {
        for (int column = 0; column < side; ++column)
        {
            if (z > 0)
            {
                const auto last = grid[side - 1][column];
                for (int row = side - 1; row > 0; --row)
                    grid[row][column] = grid[row - 1][column];
                grid[0][column] = last;
            }
            else
            {
                const auto first = grid[0][column];
                for (int row = 0; row < side - 1; ++row)
                    grid[row][column] = grid[row + 1][column];
                grid[side - 1][column] = first;
            }
        }
        z += z > 0 ? -1 : 1;
    }
}

static void TestGrid()
{
    for (const auto side : {1, 5, 49})
    {
        Grid original(side, std::vector<int>(side));
        for (int row = 0; row < side; ++row)
            for (int column = 0; column < side; ++column)
                original[row][column] = side * row + column;
        for (const auto x : {-563, -98, -49, -1, 0, 1, 48, 49, 96, 841})
            for (const auto z : {-643, -127, -49, -1, 0, 1, 49, 416})
            {
                Grid legacy = original;
                Grid batch = original;
                std::vector<const int*> cells;
                for (const auto& row : batch)
                    for (const auto& value : row)
                        cells.push_back(&value);

                OriginalRotate(legacy, x, z);
                DetailGridShift::Rotate(batch, x, z);
                Require(batch == legacy);
                Require(DetailGridShift::CoversGrid(12, -79, 12 + x, -79 + z, side) ==
                    (std::abs(x) >= side || std::abs(z) >= side));
                for (int row = 0; row < side; ++row)
                    for (int column = 0; column < side; ++column)
                        Require(cells[row * side + column] == &batch[row][column]);
            }
    }
    std::cout << "PASS: 240 signed detail shifts; same grid permutation and stable cell addresses\n";
}

#ifdef _WIN32
static void TestPackedView()
{
    using SoundWavePreparation::PackedWaveView;
    const auto original = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0, 65536, nullptr);
    const auto replacement = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0, 65536, nullptr);
    Require(original && replacement);
    auto* write = static_cast<unsigned char*>(MapViewOfFile(original, FILE_MAP_WRITE, 0, 0, 65536));
    Require(write != nullptr);
    PackedWaveView read;
    Require(read.Open(original, 0, 65536));
    Require(read.MatchesSection(original));
    Require(!read.MatchesSection(replacement));
    Require(!read.MatchesSection(nullptr));
    Require(read.Bytes(65532, 5) == nullptr);
    Require(read.Bytes(65533, 3) != nullptr);
    write[230] = 42;
    Require(*read.Bytes(230, 1) == 42);
    write[230] = 71;
    Require(*read.Bytes(230, 1) == 71);
    UnmapViewOfFile(write);
    CloseHandle(original);
    CloseHandle(replacement);
    std::cout << "PASS: packed data mutation, bounds, and exact mounted section identity\n";
}
#endif

int main()
{
    TestGrid();
#ifdef _WIN32
    TestPackedView();
#endif
}
