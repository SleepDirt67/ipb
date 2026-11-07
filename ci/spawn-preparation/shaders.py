"""Put OGG preparation and observed DX11 variants on the level-loading path."""
from pathlib import Path
import shutil
import sys

bundle = Path(__file__).resolve().parent
root = Path(sys.argv[1])


def edit(path, changes):
    target = root / path
    raw = target.read_bytes()
    crlf = b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    text = raw.replace(b"\r\n", b"\n").decode("latin-1")
    for before, after in changes:
        if text.count(before) != 1:
            raise ValueError(f"{path}: expected one anchor {before[:80]!r}, found {text.count(before)}")
        text = text.replace(before, after, 1)
    target.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("latin-1"))


render = "src/Layers/xrRenderPC_R4/r4.cpp"
edit(render, [
    ('\tstruct Variant {\n\t\tLPCSTR name;', """\tenum class Options { Base, BumpHigh, AlphaBump, AlphaBumpHigh };
\tstruct Variant {
\t\tLPCSTR name;"""),
    ('\t\tbool bumpedHighQuality;', '\t\tOptions options;'),
    ('''        { "model_distort", 3, false, false },'''.replace("        ", "\t\t"),
     '\t\t{ "model_distort", 3, false, Options::Base },'),
    ('\t\t{ "model_distort", 4, false, false },', '\t\t{ "model_distort", 4, false, Options::Base },'),
    ('\t\t{ "model_distort4ghost", 0, false, false },', '\t\t{ "model_distort4ghost", 0, false, Options::Base },'),
    ('\t\t{ "model_distort4ghost", 1, false, false },', '\t\t{ "model_distort4ghost", 1, false, Options::Base },'),
    ('\t\t{ "deffer_model", 4, false, true },', '\t\t{ "deffer_model", 4, false, Options::BumpHigh },'),
    ('\t\t{ "particle_hard", 4, true, false },', '''\t\t{ "particle_hard", 4, true, Options::Base },
\t\t{ "forward_base", 0, true, Options::AlphaBump },
\t\t{ "forward_base", 0, true, Options::AlphaBumpHigh },'''),
    ('''\tfor (const auto& variant : observed) {
\t\tconst std::span options(measuredOptions, variant.bumpedHighQuality ? 3u : 1u);''',
     '''\tconst std::pair<xr_string, xr_string> alphaOptions[] = {
\t\t{ "USE_LEGACY_LIGHT", "1" }, { "USE_AREF", "1" },
\t\t{ "USE_BUMP", "1" }, { "USE_HIGH_QUALITY", "1" },
\t};

\tfor (const auto& variant : observed) {
\t\tstd::span<const std::pair<xr_string, xr_string>> options(measuredOptions, 1);
\t\tswitch (variant.options) {
\t\tcase Options::Base: break;
\t\tcase Options::BumpHigh: options = measuredOptions; break;
\t\tcase Options::AlphaBump: options = std::span(alphaOptions, 3); break;
\t\tcase Options::AlphaBumpHigh: options = alphaOptions; break;
\t\t}'''),
])
shutil.copyfile(bundle / "shader_fixture.cpp",
                bundle.parents[1] / "experiments/periodic-136/shader-warmup/fixture.cpp")
