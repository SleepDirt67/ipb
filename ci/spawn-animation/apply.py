"""Keep the stock animation notification path off models with no notifications."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
animation = root / "src/Layers/xrRender"
shared = root / "src/Include/xrRender/animation_blend.h"
engine = root / "src/xrEngine"


def read(path):
    return path.read_bytes().replace(b"\r\n", b"\n").decode("latin-1")


def edit(path, changes):
    original = path.read_bytes()
    value = read(path)
    for before, after in changes:
        if value.count(before) != 1:
            raise ValueError((path, before[:80], value.count(before)))
        value = value.replace(before, after, 1)
    result = value.encode("latin-1")
    if b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
        result = result.replace(b"\n", b"\r\n")
    path.write_bytes(result)


source = animation / "SkeletonAnimated.cpp"
stock_header = read(shared)
stock_source = read(source)
edit(shared, [
    ("#pragma once", "#pragma once\n\n#include <optional>"),
    ("xr_hash_map<u16, NotifyKeyframes> notifies = {}; // per bone notifies",
     "std::optional<xr_hash_map<u16, NotifyKeyframes>> notifies; // per bone notifies"),
])
edit(engine / "SkeletonMotions.h", [
    ("anim_notify_prefetched& motion_notify\t(u16 idx, u16 bone)\t\t{\tVERIFY(p_); return p_->m_notifies[idx][bone];\t\t\t}",
     """const anim_notify_prefetched* find_motion_notify(u16 idx, u16 bone) const
    {
        VERIFY(p_);
        if (idx >= p_->m_notifies.size())
            return nullptr;
        const auto& notifies = p_->m_notifies[idx];
        const auto found = notifies.find(bone);
        return found == notifies.end() ? nullptr : &found->second;
    }"""),
])
edit(engine / "SkeletonMotions.cpp", [
    ("\tm_notifies.resize(dwCNT);", "\tm_notifies.clear();"),
    ("\t\t\tauto bones_size = notify_data->r_u32();",
     """\t\t\tauto bones_size = notify_data->r_u32();
            if (bones_size && m_notifies.empty())
                m_notifies.resize(dwCNT);"""),
])
edit(animation / "SkeletonAnimated.h", [
    ('#include "SkeletonCustom.h"', '#include "SkeletonCustom.h"\n#include <memory>'),
    ("\tvoid\t\t\t\t\t\tIBlend_Startup\t\t\t();",
     """#ifndef _EDITOR
    struct MotionLookup;
    std::shared_ptr<const MotionLookup> motionLookup;
#endif
    void RefreshMotionBindings();
\tvoid\t\t\t\t\t\tIBlend_Startup\t\t\t();"""),
])

binding = """\tfor (SMotionsSlot& MS : m_Motions)
\t{
\t\tMS.bone_motions.clear();
\t\tMS.bone_motions.reserve(bones->size());"""
both = read(source)
if both.count(binding) != 2:
    raise ValueError("Motion binding loops drifted")
start = both.index(binding)
stop = both.index("\n\t// Init blend pool", start)
load_binding = both[start:stop]
start = both.index(binding, stop)
stop = both.index("\n\t// Reinit blend pool", start)
append_binding = both[start:stop]
new_binding = """#ifndef _EDITOR
    auto lookup = std::make_shared<MotionLookup>();
#endif
    for (SMotionsSlot& slot : m_Motions)
    {
        slot.bone_motions.clear();
        slot.bone_motions.reserve(bones->size());
        for (const auto* bone : *bones)
            slot.bone_motions.push_back(slot.motions.bone_motions(bone->name));
#ifndef _EDITOR
        const auto index = static_cast<u16>(&slot - m_Motions.data());
        MotionLookup::Insert(lookup->motions, *slot.motions.motion_map(), index);
        MotionLookup::Insert(lookup->cycles, *slot.motions.cycle(), index);
        MotionLookup::Insert(lookup->effects, *slot.motions.fx(), index);
#endif
    }
#ifndef _EDITOR
    motionLookup = std::move(lookup);
#endif
"""
edit(source, [
    ("""\tblend_pool.clear\t();
\tfor (u32 i=0; i<MAX_BLENDED_POOL; i++)
\t{
\t\tblend_pool.push_back(B);
#ifdef\tDEBUG
\t\tblend_pool.back().set_free_state();
#endif
\t}""",
     """    blend_pool.resize(MAX_BLENDED_POOL);
    for (auto& slot : blend_pool)
    {
#ifndef DEBUG
        // Retain the container of a used slot. Assignment from an empty map
        // follows the original bucket policy, including when it affects a
        // later sequence of notifications after this reset.
        if (slot.notifies && !B.notifies)
            B.notifies.emplace();
        else if (!slot.notifies && B.notifies)
            B.notifies.reset();
#endif
        slot = B;
#ifdef DEBUG
        slot.set_free_state();
#endif
    }"""),
    ("""\tfor (u32 i = 0; i < P.bones.size(); i++)
\t{
\t\tB->notifies[(*bones)[P.bones[i]]->GetSelfID()] = {};
\t}""",
     """    if (!P.bones.empty())
    {
        if (!B->notifies)
            B->notifies.emplace();
        for (const auto bone : P.bones)
            (*B->notifies)[(*bones)[bone]->GetSelfID()] = {};
    }"""),
    ("""\t\tauto& Notify = m_Motions[motion_ID.slot].motions.motion_notify(motion_ID.idx, (*bones)[P.bones[i]]->GetSelfID());
\t\tauto& BoneNotifySlot = B->notifies[(*bones)[P.bones[i]]->GetSelfID()];
\t\tBoneNotifySlot.keyframes.resize(Notify.order.size());
\t\tBoneNotifySlot.current_notify_index = B->speed > 0 ? 0 : Notify.order.size()-1;
\t\tfor (u32 i = 0; i < Notify.order.size(); ++i)
\t\t{
\t\t\tauto& notify = BoneNotifySlot.keyframes[i];
\t\t\tnotify.key = Notify.order[i];
\t\t\tnotify.assigned = Notify.data[notify.key];
\t\t}""",
     """        {
            const u16 bone = (*bones)[P.bones[i]]->GetSelfID();
            auto& slot = (*B->notifies)[bone];
            const auto* notify = m_Motions[motion_ID.slot].motions.find_motion_notify(motion_ID.idx, bone);
            slot.current_notify_index = B->speed > 0 ? 0 : -1;
            if (notify)
            {
                slot.keyframes.resize(notify->order.size());
                slot.current_notify_index = B->speed > 0 ? 0 : static_cast<s64>(notify->order.size()) - 1;
                for (size_t key = 0; key < notify->order.size(); ++key)
                {
                    auto& frame = slot.keyframes[key];
                    frame.key = notify->order[key];
                    if (const auto found = notify->data.find(frame.key); found != notify->data.end())
                        frame.assigned = found->second;
                }
            }
        }"""),
    ("\t\t\tfor (auto& BoneNotify : B.notifies)",
     """            if (!B.notifies)
                continue;
\t\t\tfor (auto& BoneNotify : *B.notifies)"""),
    ("\tPCOPY\t\t\t(m_Motions);", """\tPCOPY\t\t\t(m_Motions);
#ifndef _EDITOR
    PCOPY(motionLookup);
#endif"""),
    (load_binding, "    RefreshMotionBindings();\n"),
    (append_binding, "    RefreshMotionBindings();\n"),
    ("void CKinematicsAnimated::append_motion_from_path", "void CKinematicsAnimated::RefreshMotionBindings()\n{\n" + new_binding + "}\n\nvoid CKinematicsAnimated::append_motion_from_path"),
])


lookup_definition = """#ifndef _EDITOR
struct CKinematicsAnimated::MotionLookup
{
    using Index = std::unordered_map<std::string_view, MotionID>;
    Index motions, cycles, effects;

    static void Insert(Index& index, const accel_map& names, u16 slot)
    {
        for (const auto& [name, id] : names)
        {
            MotionID result;
            result.set(slot, id);
            index.insert_or_assign(name.c_str(), result);
        }
    }

    static MotionID Find(const Index& index, const char* name)
    {
        const auto found = index.find(name);
        return found == index.end() ? MotionID{} : found->second;
    }
};
#endif

"""
methods = (
    ("LL_MotionID\t(LPCSTR B)", "motions", "B"),
    ("ID_Cycle_Safe(LPCSTR  N)", "cycles", "N"),
    ("ID_Cycle_Safe(shared_str  N)", "cycles", "N.c_str()"),
    ("ID_FX_Safe\t\t(LPCSTR  N)", "effects", "N"),
)
edit(source, [
    ('#include \t"SkeletonAnimated.h"', '#include \t"SkeletonAnimated.h"\n#include <string_view>\n#include <unordered_map>'),
    ("MotionID CKinematicsAnimated::" + methods[0][0],
     lookup_definition + "MotionID CKinematicsAnimated::" + methods[0][0]),
    *[(("MotionID CKinematicsAnimated::" + name + "\n{"),
       ("MotionID CKinematicsAnimated::" + name + "\n{\n#ifndef _EDITOR\n"
        f"    if (motionLookup && {arg})\n"
        f"        return MotionLookup::Find(motionLookup->{index}, {arg});\n#endif"))
      for name, index, arg in methods],
])

if len(sys.argv) > 2:
    generated = Path(sys.argv[2])
    generated.mkdir(parents=True, exist_ok=True)
    for name, blend, cpp in (("Stock", stock_header, stock_source), ("Candidate", read(shared), read(source))):
        first = blend.index("class  CBlend ")
        last = blend.index("class IBlendDestroyCallback", first)
        startup = cpp[cpp.index("void CKinematicsAnimated::IBlend_Startup"):cpp.index("CBlend* CKinematicsAnimated::IBlend_Create")]
        begin = cpp.index("CBlend*\tCKinematicsAnimated::LL_PlayCycle")
        end = cpp.index("CBlend*\tCKinematicsAnimated::LL_PlayCycle", begin + 1)
        (generated / (name + "Blend.inc")).write_text(blend[first:last], encoding="latin-1")
        (generated / (name + "Engine.inc")).write_text(startup + cpp[begin:end], encoding="latin-1")
    (generated / "Lookup.inc").write_text(lookup_definition, encoding="latin-1")
    (generated / "FixedVector.h").write_text(read(root / "src/xrCore/FixedVector.h"), encoding="latin-1")
