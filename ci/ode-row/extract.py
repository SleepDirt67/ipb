from pathlib import Path
import sys

src = Path(sys.argv[1]).read_text()
a = src.index("static void compute_invM_JT (")
b = src.index("// compute out = J*in.", a)
common = src[a:b]
a = src.index("struct IndexError {")
b = src.index("\n/*\nstatic void SOR_LCP", a)
body = src[a:b]
assert body.count("static void SOR_LCP (") == 1
start = body.index("\t\t\t// update fc.")
end = body.index("\n\t\t}", start)
candidate = body[:start] + """            AccumulateSix(fc + 6*b1, iMJ_ptr, delta);
            if (b2 >= 0)
                AccumulateSix(fc + 6*b2, iMJ_ptr + 6, delta);""" + body[end:]
force_only = candidate
start = candidate.index("\t\t\t// @@@ potential optimization: SIMD-ize")
end = candidate.index("\n\n\t\t\t// compute lambda",start)
candidate = candidate[:start] + """            delta -= DotSix(fc_ptr, J_ptr);
            if (b2 >= 0)
                delta -= DotSix(fc + 6*b2, J_ptr + 6);""" + candidate[end:]
out = Path(sys.argv[2])
def function(source, name):
    return source[source.index("static void SOR_LCP ("):].replace("static void SOR_LCP (", f"static void {name} (", 1)
(out / "solvers.inc").write_text(common + body + function(force_only, "SOR_Vector") +
                                   function(candidate, "SOR_Dot"), encoding="utf-8")
