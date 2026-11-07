"""Prepare the stock state-manager rules once, without running any game Lua."""
import hashlib
from pathlib import Path
import re
import sys

STOCK_SHA = 'a82fc746641235166e7171d30ea6f6a416a2029fdf6f0b191a6096348241403c'
RULE = re.compile(rb'\s*action:add_(precondition|effect)\s*\(world_property\(st\.properties\["([a-z_]+)"\],\s*(true|false)\)\)\s*')


def prepare(stock):
    if hashlib.sha256(stock).hexdigest() != STOCK_SHA:
        raise ValueError('unexpected pinned state_mgr_goap')
    lines = stock.splitlines(keepends=True)
    groups = []
    start = 0
    while start < len(lines):
        end = start
        rules = []
        while end < len(lines) and (rule := RULE.fullmatch(lines[end])):
            method, key, value = rule.groups()
            rules.append((key.decode('ascii'), value == b'true', method == b'effect'))
            end += 1
        if len(rules) >= 2:
            group = len(groups)
            groups.append(rules)
            guard = f'if not ixray_apply_stock_goap_rules(action, st.properties, world_property, {group}) then '.encode()
            lines[start] = b'\t' + guard + lines[start].lstrip()
            lines[end - 1] = lines[end - 1].rstrip(b'\n') + b' end\n'
        start = max(start + 1, end)

    if not groups or sum(map(len, groups)) < 275:
        raise ValueError('incomplete stock GOAP extraction')
    return b''.join(lines), groups


def prepare_goap(engine, output):
    stock = (engine / 'gamedata/scripts/state_mgr_goap.script').read_bytes().replace(b'\r\n', b'\n')
    prepared, groups = prepare(stock)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'stock_goap.lua').write_bytes(stock)
    (output / 'prepared_goap.lua').write_bytes(prepared)
    source = engine / 'src/xrScripts/PreparedStockGoap.inc'
    source.write_text(''.join(f'constexpr unsigned char {name}[] = {{\n' +
                           ''.join(','.join(map(str, data[i:i+32])) + ',\n' for i in range(0, len(data), 32)) +
                           '};\n' for name, data in [('stockGoap', stock), ('preparedStockGoap', prepared)]),
                      encoding='ascii', newline='\n')
    offsets = [0]
    lines = ['constexpr SpawnRule spawnRules[] = {']
    for rules in groups:
        for key, value, effect in rules:
            lines.append(f'    {{"{key}", {str(value).lower()}, {str(effect).lower()}}},')
        offsets.append(offsets[-1] + len(rules))
    lines.extend(['};', f'constexpr unsigned maxSpawnRules = {max(map(len, groups))};',
                  'constexpr unsigned spawnRuleOffsets[] = {' + ', '.join(map(str, offsets)) + '};'])
    (engine / 'src/xrGame/PreparedSpawnGoapRules.inc').write_text('\n'.join(lines) + '\n', encoding='ascii', newline='\n')
    print(f'Stock GOAP: {offsets[-1]} property operations in {len(groups)} ordered groups')


if __name__ == '__main__':
    prepare_goap(*map(Path, sys.argv[1:]))
