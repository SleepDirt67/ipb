"""Install the indexed workspace in the actual level-graph search."""
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
fixture = Path(sys.argv[2]) if len(sys.argv) > 2 else None
bundle = Path(__file__).resolve().parent
path = root / "src/xrEngine/AI/level_graph.cpp"
original = path.read_bytes()
text = original.replace(b"\r\n", b"\n").decode("utf-8")
start = text.index("bool ILevelGraph::Search(")
end = text.index("u32 ILevelGraph::SearchNearestVertex(", start)
stock = text[start:end]
candidate = stock

def change(before, after):
    global candidate
    if candidate.count(before) != 1:
        raise ValueError(f"Level graph source drift: {before}")
    candidate = candidate.replace(before, after, 1)

change('''	struct SearchNode {
		float cost;
		u32 parent;
	};

	// Reuse the same heap storage and one pooled record per visited vertex.
	thread_local xr_vector<std::pair<float, u32>> TempPriorityNode;
	thread_local std::pmr::unsynchronized_pool_resource pool_resource;
	thread_local std::pmr::unordered_map<u32, SearchNode> nodes{ &pool_resource };''',
'''	thread_local xr_vector<std::pair<float, u32>> TempPriorityNode;
	thread_local LevelSearch::Workspace nodes;''')
change('	nodes.clear();', '	nodes.Begin(m_nodes);')
change('	nodes.emplace(FromID, SearchNode{ 0.f, FromID });', '	nodes.Set(FromID, 0.f, FromID);')
change('nodes.find(NextNode)->second.parent', 'nodes.Find(NextNode)->parent')
change('		const SearchNode& current = nodes.find(CurrentNodeID)->second;',
       '		const float currentCost = nodes.Find(CurrentNodeID)->cost;')
change('float NewCost = current.cost + CalcCost(Node, Neighbor);',
       'float NewCost = currentCost + CalcCost(Node, Neighbor);')
change('''			const auto next = nodes.find(NeighborID);
			if (next != nodes.end() && next->second.cost <= NewCost) {''',
       '''			const auto* next = nodes.Find(NeighborID);
			if (next && next->cost <= NewCost) {''')
change('nodes.size() >= MaxVisitedNodeCount', 'nodes.Visited() >= MaxVisitedNodeCount')
change('''			const SearchNode updated{ NewCost, CurrentNodeID };
			if (next != nodes.end())
				next->second = updated;
			else
				nodes.emplace(NeighborID, updated);''',
       '''			nodes.Set(NeighborID, NewCost, CurrentNodeID);''')

change('		CVertex* Node = vertex(CurrentNodeID);',
       '''		// Keep every original heap pop so equal priorities retain their
		// order. Re-expanding a vertex at the same cost cannot relax an edge.
		if (!nodes.BeginExpansion(CurrentNodeID))
			continue;
		CVertex* Node = vertex(CurrentNodeID);''')
change('			nodes.Set(NeighborID, NewCost, CurrentNodeID);',
       '''			if (next && nodes.ProveUnreachable(FromID, ToID, [this](u32 current, const auto& add) {
				const auto* vertex = this->vertex(current);
				for (s32 edge = 0; edge < 4; ++edge) {
					const u32 next = vertex->link(edge);
					if (is_accessible(next))
						add(next);
				}
			}))
				return false;

			nodes.Set(NeighborID, NewCost, CurrentNodeID);''')

output = (text[:start] + candidate + text[end:]).replace(
    '#include "level_graph.h"', '#include "level_graph.h"\n#include "LevelSearchWorkspace.h"', 1).encode("utf-8")
if b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
    output = output.replace(b"\n", b"\r\n")
path.write_bytes(output)
shutil.copyfile(bundle / "LevelSearchWorkspace.h", path.with_name("LevelSearchWorkspace.h"))
if fixture:
    fixture.mkdir(parents=True, exist_ok=True)
    (fixture / "Stock.inc").write_text(stock.replace("::Search(", "::Stock(", 1), encoding="utf-8")
    (fixture / "Candidate.inc").write_text(candidate, encoding="utf-8")
