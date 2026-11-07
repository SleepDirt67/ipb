"""Compile the exact stock Lua parser's static condition inputs for the engine."""
from collections import Counter
import argparse
import ctypes
import hashlib
from pathlib import Path
import re

STOCK_SHA = '845d3094861268f9e620eaa1b5575a20fc01b6a2dc349ab57225049095839e62'
TEMPLATE_MARKER = b'function parse_condlist(npc, section, field, src)\n\tlocal lst = {}'
END_MARKER = b'\n\treturn lst\nend'
HELPERS = b'local original_find, original_sub, original_len, original_gfind = string.find, string.sub, string.len, string.gfind\nlocal original_number, original_insert = tonumber, table.insert\nlocal original_infop, original_params = parse_infop, parse_func_params\n'
COMPILER_TAIL = rb'''
local function literal(s)
    return '"' .. string.gsub(s, '.', function(c)
        local b = string.byte(c)
        if b >= 32 and b < 127 and b ~= 34 and b ~= 92 then return c end
        return string.format('\\%03d', b)
    end) .. '"'
end
local function expression(v)
    local kind = type(v)
    if kind == 'string' then return literal(v) end
    if kind == 'number' then
        if v ~= v or v == math.huge or v == -math.huge then error('nonfinite') end
        if v == 0 and 1 / v < 0 then return '-0.0' end
        return string.format('%.17g', v)
    end
    if kind == 'boolean' then return tostring(v) end
    assert(kind == 'table')
    local result, seen = {}, 0
    for i, entry in ipairs(v) do result[#result + 1] = expression(entry); seen = seen + 1 end
    for _, name in ipairs({'section', 'infop_check', 'infop_set', 'name', 'required', 'prob', 'func', 'expected', 'params'}) do
        if v[name] ~= nil then
            result[#result + 1] = name .. '=' .. expression(v[name])
            seen = seen + 1
        end
    end
    local total = 0
    for _ in pairs(v) do total = total + 1 end
    assert(total == seen)
    return '{' .. table.concat(result, ',') .. '}'
end
local out = {}
for _, value in ipairs(sources) do
    local ok, result = pcall(parse_condlist, nil, nil, nil, value)
    if ok then
        local encodable, body = pcall(expression, result)
        if encodable then
            out[#out+1] = 'templates[' .. literal(value) .. ']=function() return ' .. body .. ' end'
        end
    end
end
return table.concat(out, '\n')
'''


def lua_quote(data):
    return b'"' + b''.join(bytes([c]) if 32 <= c < 127 and c not in (34, 92)
                            else ('\\%03d' % c).encode() for c in data) + b'"'


class Lua:
    def __init__(self, library):
        dll = self.dll = ctypes.CDLL(str(Path(library).resolve()))
        state = ctypes.c_void_p
        definitions = {
            'luaL_newstate': (state, []),
            'luaL_openlibs': (None, [state]),
            'luaL_loadbuffer': (ctypes.c_int, [state, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p]),
            'lua_pcall': (ctypes.c_int, [state, ctypes.c_int, ctypes.c_int, ctypes.c_int]),
            'lua_tolstring': (ctypes.c_void_p, [state, ctypes.c_int, ctypes.POINTER(ctypes.c_size_t)]),
            'lua_close': (None, [state]),
        }
        for name, (result, args) in definitions.items():
            function = getattr(dll, name)
            function.restype, function.argtypes = result, args

    def run(self, source):
        dll = self.dll
        state = dll.luaL_newstate()
        if not state:
            raise RuntimeError('LuaJIT state allocation failed')
        try:
            dll.luaL_openlibs(state)
            status = dll.luaL_loadbuffer(state, source, len(source), b'@stock_condition_compiler')
            if not status:
                status = dll.lua_pcall(state, 0, 1, 0)
            size = ctypes.c_size_t()
            result = dll.lua_tolstring(state, -1, ctypes.byref(size))
            output = ctypes.string_at(result, size.value) if result else b''
            if status:
                raise ValueError(output.decode(errors='replace'))
            return output
        finally:
            dll.lua_close(state)


def stock_logic(engine):
    data = (engine / 'gamedata/scripts/xr_logic.script').read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(data).hexdigest() != STOCK_SHA:
        raise ValueError('unexpected pinned xr_logic')
    return data


def parser_section(data):
    start = data.rindex(b'function abort_syntax_error_in_cond', 0, data.index(TEMPLATE_MARKER))
    stop = data.index(END_MARKER, data.index(TEMPLATE_MARKER)) + len(END_MARKER)
    return data[start:stop]


def corpus(engine):
    counts = Counter()
    key = re.compile(rb'^(?:active|on_[a-z0-9_]+|combat_type|combat_ignore_cond|heli_hunter)$')
    for path in sorted((engine / 'gamedata/configs').rglob('*.ltx')):
        for line in path.read_bytes().splitlines():
            name, equals, value = line.partition(b'=')
            if not equals or not key.fullmatch(name.strip().lower()):
                continue
            value = value.split(b';', 1)[0].strip()
            for part in value.split(b'|'):
                for candidate in {part, part.strip(), re.sub(rb'[ \t]+', b'', part)}:
                    if 0 < len(candidate) <= 512 and (
                        b'{' in candidate or b'%' in candidate or
                        re.fullmatch(rb'[A-Za-z_][A-Za-z_0-9@]*', candidate)
                    ):
                        counts[candidate] += 1
    return sorted(sorted(counts, key=lambda text: (-counts[text], text))[:4096])


def compile_templates(data, values, lua):
    prefix = b"local function abort(...) error('invalid condition') end\nstring.gfind = string.gfind or string.gmatch\n"
    # LuaJIT has limits on the number of constants per chunk. Bound each invocation.
    compiled = []
    for start in range(0, len(values), 128):
        chunk = b'local sources = {' + b','.join(map(lua_quote, values[start:start + 128])) + b'}\n'
        result = lua.run(prefix + parser_section(data) + b'\n' + chunk + COMPILER_TAIL)
        if result:
            compiled.extend(result.splitlines())
    # Keep builder creation in small Lua chunks within the stock namespace.
    groups = []
    for start in range(0, len(compiled), 96):
        groups.append(b'(function(templates)\n' + b'\n'.join(compiled[start:start + 96]) + b'\nend)(compiled_conditions);')
    return b'local compiled_conditions = {}\n' + b'\n'.join(groups) + b'\n', len(compiled)


def transform(data, templates):
    parser = b'''function parse_condlist(npc, section, field, src)
    local prepared = compiled_conditions[src]
    if prepared and parse_infop == original_infop and parse_func_params == original_params
        and string.find == original_find and string.sub == original_sub
        and string.len == original_len and string.gfind == original_gfind
        and tonumber == original_number and table.insert == original_insert
    then
        return prepared()
    end
\tlocal lst = {}'''
    if data.count(TEMPLATE_MARKER) != 1:
        raise ValueError('parser anchor')
    data = data.replace(TEMPLATE_MARKER, templates + HELPERS + parser, 1)
    start = data.index(b'\tlocal function add_conditions(func, cond)')
    end = data.index(b'\tadd_conditions( cfg_get_number_and_condlist', start)
    replacement = b'''\tlocal function add_conditions(func, cond)
        local next_key = type(ini) == "userdata" and ini.ixray_next_switch_key
        local line_number = 0
        while line_number < line_count do
            if next_key and string.find == original_find then
                local index, key = next_key(ini, section, cond, line_number, line_count)
                if index == -1 then return end
                if index >= 0 then
                    c = func(ini, section, key, npc)
                    n = add_condition(l, n, c)
                    line_number = index + 1
                else
                    next_key = nil
                end
            else
                local result, id, value = ini:r_line(section,line_number,"","")
                if string.find(id, "^"..cond.."%d*$") ~= nil then
                    c = func(ini, section, id, npc)
                    n = add_condition(l, n, c)
                end
                line_number = line_number + 1
            end
        end
    end

'''
    return data[:start] + replacement + data[end:]


def emit_header(name, value):
    return (f'static constexpr unsigned char {name}[] = {{\n' +
            '\n'.join(','.join(str(x) for x in value[i:i + 32]) + ',' for i in range(0, len(value), 32))
            + '\n};\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('engine', type=Path)
    parser.add_argument('lua', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    stock = stock_logic(args.engine)
    values = corpus(args.engine)
    lua = Lua(args.lua)
    templates, count = compile_templates(stock, values, lua)
    transformed = transform(stock, templates)
    # Ensure LuaJIT can parse the entire transformed stock script before C++ build.
    lua.run(b'assert(loadstring(' + lua_quote(transformed) + b')); return "ok"')
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'stock_logic.lua').write_bytes(stock)
    (args.output / 'prepared_logic.lua').write_bytes(transformed)
    (args.engine / 'src/xrScripts/PreparedStockLogic.inc').write_text(
        emit_header('stockLogic', stock) + emit_header('preparedStockLogic', transformed),
        encoding='ascii', newline='\n')
    print(f'{count} condition programs prepared from {len(values)} stock values')
    if count < 100:
        raise ValueError('unexpectedly sparse stock corpus')


if __name__ == '__main__':
    main()
