from pathlib import Path
import sys
from conditions import Lua, corpus, lua_quote

engine, library, compiled = map(Path, sys.argv[1:])
source = b'local stock=' + lua_quote((compiled/'stock_logic.lua').read_bytes()) + b'\n'
source += b'local prepared=' + lua_quote((compiled/'prepared_logic.lua').read_bytes()) + b'\n'
source += b'local corpus={' + b','.join(map(lua_quote, corpus(engine))) + b'}\n'
source += Path(__file__).with_name('replay.lua').read_bytes()
print(Lua(library).run(source).decode())
