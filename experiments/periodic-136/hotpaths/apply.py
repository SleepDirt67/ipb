"""Apply the stack-backed sound lookup and level-search changes to IX-Ray r1.3.6."""
from pathlib import Path
import sys

engine = Path(sys.argv[1] if len(sys.argv) > 1 else "ixray")


def edit(relative, replacements):
    path = engine / relative
    data = path.read_bytes()
    source = data.decode("utf-8").replace("\r\n", "\n")
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError(f"{relative}: expected exactly one {before[:90]!r}")
        source = source.replace(before, after, 1)
    if b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""):
        source = source.replace("\n", "\r\n")
    path.write_bytes(source.encode("utf-8"))


edit("src/xrSound/SoundRender_Core.h", [
    ("\txr_vector<CSoundRender_Source*>\t\ts_sources;",
     "\txr_vector<CSoundRender_Source*>\t\ts_sources;\n"
     "\txr_map<xr_string, CSoundRender_Source*, std::less<>> s_sources_by_name;"),
])
edit("src/xrSound/SoundRender_Core.cpp", [
    ("\t// remove sources\n\tfor", "\t// remove sources\n\ts_sources_by_name.clear();\n\tfor"),
    ("CSoundRender_Core::refresh_sources()\n{", "CSoundRender_Core::refresh_sources()\n{\n"
     "\t// Reload can change a stored name by stripping another suffix.\n"
     "\ts_sources_by_name.clear();"),
])
edit("src/xrSound/SoundRender_Core_SourceManager.cpp", [
    ('#include "SoundRender_Source.h"', '#include "SoundRender_Source.h"\n\n#include <memory>'),
    ("""\tfor (u32 it=0; it<s_sources.size(); it++)\t\t{
\t\tif (0==xr_strcmp(*s_sources[it]->fname,id))\treturn s_sources[it];
\t}

\t// Load a _new one
\tCSoundRender_Source* S\t= new CSoundRender_Source\t();
\tS->load\t\t\t\t\t(id);
\ts_sources.push_back\t\t(S);
\treturn S;""",
     """\tif (s_sources_by_name.empty() && !s_sources.empty())
\t{
\t\tdecltype(s_sources_by_name) rebuilt;
\t\tfor (auto* source : s_sources)
\t\t\trebuilt.try_emplace(source->fname.c_str(), source);
\t\ts_sources_by_name.swap(rebuilt);
\t}
\tconst auto found = s_sources_by_name.find(id);
\tif (found != s_sources_by_name.end())
\t\treturn found->second;

\tauto source = std::make_unique<CSoundRender_Source>();
\tsource->load(id);
\ts_sources.push_back(source.get());
\ttry
\t{
\t\t// The loader can strip another suffix. Keep the first source with that stored name.
\t\ts_sources_by_name.try_emplace(source->fname.c_str(), source.get());
\t}
\tcatch (...)
\t{
\t\ts_sources.pop_back();
\t\tthrow;
\t}
\treturn source.release();"""),
])


graph = "src/xrEngine/AI/level_graph.cpp"
path = engine / graph
source = path.read_text(encoding="utf-8")
start = source.index("bool ILevelGraph::Search(")
end = source.index("\nu32 ILevelGraph::SearchNearestVertex", start)
before = source[start:end]
after = before
changes = [
    ("""\tthread_local std::priority_queue<std::pair<float, u32>,
\t\txr_vector<std::pair<float, u32>>,
\t\tComparePriority> TempPriorityNode;

\tthread_local std::pmr::unordered_map<u32, u32> TempCameFrom;
\tthread_local std::pmr::unordered_map<u32, float> TempCostSoFar;

\t// Используем memory pool с очисткой между вызовами
\tthread_local std::pmr::unsynchronized_pool_resource pool_resource;
\tthread_local bool initialized = false;

\tif (!initialized) {
\t\tTempCameFrom = std::pmr::unordered_map<u32, u32>{ &pool_resource };
\t\tTempCostSoFar = std::pmr::unordered_map<u32, float>{ &pool_resource };
\t\tinitialized = true;
\t}""",
     """\tstruct SearchNode {
\t\tfloat cost;
\t\tu32 parent;
\t};

\t// Reuse the same heap storage and one pooled record per visited vertex.
\tthread_local xr_vector<std::pair<float, u32>> TempPriorityNode;
\tthread_local std::pmr::unsynchronized_pool_resource pool_resource;
\tthread_local std::pmr::unordered_map<u32, SearchNode> nodes{ &pool_resource };"""),
    ("""\tTempPriorityNode = {};
\tTempCameFrom.clear();
\tTempCostSoFar.clear();""", """\tTempPriorityNode.clear();
\tnodes.clear();"""),
    ("""\tTempPriorityNode.push({ 0.f, FromID });
\tTempCameFrom[FromID] = FromID;
\tTempCostSoFar[FromID] = 0.f;""",
     """\tTempPriorityNode.push_back({ 0.f, FromID });
\tnodes.emplace(FromID, SearchNode{ 0.f, FromID });"""),
    ("""\tu32 visited_count = 0;

""", ""),
    ("""\t\tu32 CurrentNodeID = TempPriorityNode.top().second;
\t\tTempPriorityNode.pop();""",
     """\t\tstd::pop_heap(TempPriorityNode.begin(), TempPriorityNode.end(), ComparePriority{});
\t\tconst u32 CurrentNodeID = TempPriorityNode.back().second;
\t\tTempPriorityNode.pop_back();"""),
    ("""\t\t\t\tOutPath.insert(OutPath.begin(), NextNode);
\t\t\t\tNextNode = TempCameFrom[NextNode];
\t\t\t}
\t\t\tOutPath.insert(OutPath.begin(), NextNode);""",
     """\t\t\t\tOutPath.push_back(NextNode);
\t\t\t\tNextNode = nodes.find(NextNode)->second.parent;
\t\t\t}
\t\t\tOutPath.push_back(NextNode);
\t\t\tstd::reverse(OutPath.begin(), OutPath.end());"""),
    ("""\t\tCVertex* Node = vertex(CurrentNodeID);
""", """\t\tCVertex* Node = vertex(CurrentNodeID);
\t\tconst SearchNode& current = nodes.find(CurrentNodeID)->second;
"""),
    ("TempCostSoFar[CurrentNodeID]", "current.cost"),
    ("auto cost_it = TempCostSoFar.find(NeighborID);", "const auto next = nodes.find(NeighborID);"),
    ("cost_it != TempCostSoFar.end() && cost_it->second <= NewCost",
     "next != nodes.end() && next->second.cost <= NewCost"),
    ("TempCostSoFar.size()", "nodes.size()"),
    ("""\t\t\tif (cost_it != TempCostSoFar.end()) {
\t\t\t\tcost_it->second = NewCost;
\t\t\t}
\t\t\telse {
\t\t\t\tTempCostSoFar[NeighborID] = NewCost;
\t\t\t}

\t\t\t// Добавляем в очередь с приоритетом
\t\t\tfloat priority = NewCost + Distance;
\t\t\tTempPriorityNode.push({ priority, NeighborID });

\t\t\t// Обновляем информацию о пути
\t\t\tTempCameFrom[NeighborID] = CurrentNodeID;""",
     """\t\t\tconst SearchNode updated{ NewCost, CurrentNodeID };
\t\t\tif (next != nodes.end())
\t\t\t\tnext->second = updated;
\t\t\telse
\t\t\t\tnodes.emplace(NeighborID, updated);

\t\t\tTempPriorityNode.push_back({ NewCost + Distance, NeighborID });
\t\t\tstd::push_heap(TempPriorityNode.begin(), TempPriorityNode.end(), ComparePriority{});"""),
    ("\n\t\tvisited_count++;", ""),
]
for old, new in changes:
    if after.count(old) != 1:
        raise ValueError(f"{graph}: expected exactly one {old[:90]!r}")
    after = after.replace(old, new, 1)
edit(graph, [(before, after)])
