"""Separate repeated immutable geometry work from live character activation."""
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
physics = root / "src/xrPhysics"
bundle = Path(__file__).resolve().parent

def edit(filename, replacements, directory=physics):
    path = directory / filename
    original = path.read_bytes()
    data = original.replace(b"\r\n", b"\n").decode("latin-1")
    for before, after in replacements:
        if data.count(before) != 1:
            raise ValueError((filename, before[:80], data.count(before)))
        data = data.replace(before, after, 1)
    output = data.encode("latin-1")
    if b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
        output = output.replace(b"\n", b"\r\n")
    path.write_bytes(output)

for name in ("ActivationCollisionPlan.h", "SpawnActivationContacts.h"):
    shutil.copyfile(bundle / name, physics / name)

edit("IActivationShape.cpp", [
    ('#include "PHCollideValidator.h"', '#include "PHCollideValidator.h"\n#include "SpawnActivationContacts.h"'),
    ("\tbool ret = activation_shape.Activate(vbox,1,1.f,M_PI/8.f);",
     "    SpawnCollision::Scope contacts(activation_shape.ODEBody());\n"
     "\tbool ret = activation_shape.Activate(vbox,1,1.f,M_PI/8.f);"),
])

edit("tri-colliderknoopc/dSortTriPrimitive.h", [
    ('#include "../PHWorld.h"', '#include "../PHWorld.h"\n#include "../SpawnActivationContacts.h"'),
    ("\tif (no_last_pos || !last_box.contains(box))",
     """    auto* activation = SpawnCollision::Scope::For(dGeomGetBody(o1));
    if (activation && data->callback)
    {
        activation->Clear();
        activation = nullptr;
    }
    const auto fpMode = activation ? SpawnCollision::Scope::FloatingPointMode() : 0u;
    bool newStaticQuery = false;
\tif (no_last_pos || !last_box.contains(box))"""),
    ("\tbool gb_pased = false;\n\tfor (I=B; I!=E; ++I)", '''    if (activation && !activation->Select(T_array, V_array, data->cashed_tries.size(),
        newStaticQuery, p, reinterpret_cast<const float*>(&AABB), fpMode))
        activation = nullptr;
\tbool gb_pased = false;
\tfor (I=B; I!=E; ++I)'''),
    ('''\t\tconst Point vertices[3]={Point((dReal*)&V_array[Tris->verts[0]]),Point((dReal*)&V_array[Tris->verts[1]]),Point((dReal*)&V_array[Tris->verts[2]])};
\t\tif(!aabb_tri_aabb(Point(p),Point((float*)&AABB),vertices))
\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\tcontinue;''',
     '''        Point liveVertices[3];
        const Point* vertices;
        auto* prepared = activation ? &activation->At(static_cast<std::size_t>(I - B)) : nullptr;
        if (prepared)
        {
            vertices = prepared->Vertices(*Tris, V_array);
            if (!prepared->Broad(p, AABB))
                continue;
        }
        else
        {
            for (int i = 0; i < 3; ++i)
                liveVertices[i] = Point(reinterpret_cast<const float*>(&V_array[Tris->verts[i]]));
            vertices = liveVertices;
            if (!aabb_tri_aabb(Point(p), Point(reinterpret_cast<const float*>(&AABB)), vertices))
                continue;
        }'''),
    ("\t\tCalculateTri(Tris,p,tri,vertices);", '''        if (prepared)
            prepared->TriangleAt(Tris, p, tri);
        else
            CalculateTri(Tris, p, tri, vertices);'''),
    ("\t\t\t\tif(__aabb_tri(Point(p),Point((float*)&AABB),vertices))",
     "                if (prepared ? prepared->Exact(p, AABB) :\n"
     "                    __aabb_tri(Point(p), Point(reinterpret_cast<const float*>(&AABB)), vertices))"),
])

collider = physics / "tri-colliderknoopc/dSortTriPrimitive.h"
start = "\t\tXRC.box_options(0);"
end = "\t\tdata->last_aabb_pos.set(cast_fv(p));"
source = collider.read_bytes().replace(b"\r\n", b"\n").decode("latin-1")
legacy_query = source[source.index(start):source.index(end)]
query = legacy_query.replace("\t\t//VERIFY( g_pGameLevel );\n", "").replace(
    "inl_ph_world().ObjectSpace().GetStaticModel()", "model"
)
query = "\n".join("\t" + line if line.startswith("\t") else line for line in query.split("\n"))
edit("tri-colliderknoopc/dSortTriPrimitive.h", [(legacy_query, """        const auto* model = inl_ph_world().ObjectSpace().GetStaticModel();
        newStaticQuery = !activation ||
            !activation->ReuseStaticQuery(model, p, reinterpret_cast<const float*>(&aabb),
                fpMode, data->cashed_tries.size());
        if (newStaticQuery)
        {
""" + query + """            if (activation)
                activation->SetStaticQueryCount(data->cashed_tries.size());
        }
""")])

game = root / "src/xrGame"
shutil.copyfile(bundle / "PrepareSpawnVisuals.inc", game / "PrepareSpawnVisuals.inc")
edit("Level_network_start_client.cpp", [
    ('#include "ai_space.h"', '#include "ai_space.h"\n#include "alife_simulator.h"\n#include "alife_object_registry.h"\n#include <cstdlib>'),
    ('#include "../xrEngine/string_table.h"', '#include "../xrEngine/string_table.h"\n#include "PrepareSpawnVisuals.inc"'),
    ('\t\tR_ASSERT2\t\t\t\t(Load(level_id),"Loading failed.");',
     '\t\tR_ASSERT2\t\t\t\t(Load(level_id),"Loading failed.");\n        PrepareSpawnVisuals();'),
], game)

shutil.copyfile(bundle / "contact_fixture.cpp", root / "ixray_spawn_contact_fixture.cpp")
with (root / "CMakeLists.txt").open("a", encoding="utf-8") as build:
    build.write("""
add_executable(ixray_spawn_contact_fixture ixray_spawn_contact_fixture.cpp)
target_link_libraries(ixray_spawn_contact_fixture PRIVATE xrPhysics)
""")
