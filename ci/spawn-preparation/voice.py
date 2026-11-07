"""Prepare the stock sound_theme path with a guarded native catalogue query."""
import hashlib

STOCK_SHA256 = '5b86e1d5ef581320917aa84b2b47a30b0e8d2dcd036c4080df8703f510713260'

HELPER = b'''local stock_getFS = getFS
local native_lookup = setmetatable({}, {__mode = "k"})
local function native_method(method)
    if type(method) ~= "function" then return false end
    local native = native_lookup[method]
    if native == nil then
        native = debug ~= nil and debug.getinfo(method, "S").what == "C"
        native_lookup[method] = native
    end
    return native
end
'''


def rewrite(stock):
    before = stock.index(b'function npc_sound:init_npc(npc)')
    start = stock.index(b'\tlocal f = getFS()', before)
    end = stock.index(b'\tif self.npc[npc_id].max < 0', start)
    legacy = stock[start:end]
    faster = b'''\tlocal f = getFS()
\tlocal count, base = -2, nil
\tif getFS == stock_getFS and type(f) == "userdata" and type(npc) == "userdata" and
\t    native_method(f.sound_variant_count) and native_method(f.exist) and native_method(npc.sound_prefix) then
\t\tbase = npc:sound_prefix()..self.path
\t\tcount = f:sound_variant_count(base)
\tend
\tif count == -1 then
\t\tself.sound_path[npc_id][1] = base
\telseif count >= 0 then
\t\tfor num = 1, count do
\t\t\tself.sound_path[npc_id][num] = base..num
\t\tend
\telse
'''
    fallback = legacy.split(b'\n', 1)[1]
    return stock[:before] + HELPER + stock[before:start] + faster + fallback + b'\tend\n' + stock[end:]


def generate(root):
    stock = (root / 'gamedata/scripts/sound_theme.script').read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(stock).hexdigest() != STOCK_SHA256:
        raise ValueError('Unexpected stock CoP voice script')
    output = root / 'src/xrScripts/StockVoiceScript.inc'

    def array(name, data):
        lines = [', '.join(str(byte) for byte in data[i:i + 24]) for i in range(0, len(data), 24)]
        return 'static constexpr unsigned char ' + name + '[] = {\n' + ',\n'.join(lines) + '\n};\n'

    output.write_text(array('stockVoiceScript', stock) + array('batchedVoiceScript', rewrite(stock)),
                      encoding='ascii')
