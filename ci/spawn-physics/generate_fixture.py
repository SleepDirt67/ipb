"""Copy the actual world phase operations into the no-GOG differential fixture."""
from pathlib import Path
import sys

engine, output = map(Path, sys.argv[1:])
source = (engine / 'src/xrPhysics/PHWorld.cpp').read_text(encoding='latin-1')
begin = source.index('bool CPHWorld::DeferFreezeForActivation()')
end = source.index('bool CPHWorld::IsFreezed()', begin)
output.mkdir(parents=True, exist_ok=True)
(output / 'freeze_functions.inc').write_text(source[begin:end], encoding='ascii')
