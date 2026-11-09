"""Reset pooled kinematics' render history at the live Spawn transition."""
import argparse
from pathlib import Path


def patch(root):
    path = root / "src/Layers/xrRender/SkeletonCustom.cpp"
    raw = path.read_bytes()
    data = raw.replace(b"\r\n", b"\n")
    anchor = b"void CKinematics::Spawn\t\t\t()\n{\n\tinherited::Spawn\t\t\t();"
    if data.count(anchor) != 1:
        raise ValueError("kinematics Spawn anchor changed")
    replacement = anchor + b"""
    // A pooled visual may have been rendered for a different object.
    // Initialize its previous transforms from the first pose of this life.
    dwFirstRenderFrame = 0;"""
    output = data.replace(anchor, replacement, 1)
    if b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""):
        output = output.replace(b"\n", b"\r\n")
    path.write_bytes(output)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("engine", type=Path)
    patch(cli.parse_args().engine)
