from pathlib import Path
p = Path(r'd:\Project\BA_Game\Nes_fire_emulator\User\nes\6502.s')
t = p.read_text()
lines = t.split('\n')
result = []
count = 0
for line in lines:
    s = line.strip()
    if s == 'beq branch_taken':
        indent = line[:len(line) - len(line.lstrip())]
        label = f'skip_bt_{count}'
        result.append(f'{indent}bne {label}')
        result.append(f'{indent}b.w branch_taken')
        result.append(label)
        count += 1
    elif s == 'bne branch_taken':
        indent = line[:len(line) - len(line.lstrip())]
        label = f'skip_bt_{count}'
        result.append(f'{indent}beq {label}')
        result.append(f'{indent}b.w branch_taken')
        result.append(label)
        count += 1
    else:
        result.append(line)
t = '\n'.join(result)
t = t.replace('AREA cpu_run, CODE, READONLY\nbranch_taken',
              'AREA cpu_run, CODE, READONLY\nTHUMB\nbranch_taken')
# If branch_taken was moved earlier to cpu_code area, remove it
# (find THUMB in cpu_code area and check if branch_taken is right after)
import re
t = re.sub(r'(\tTHUMB\t ;Thumb[^\n]*)\nbranch_taken\n\tldr r1,lastbank',
           r'\1\n\tldr r1,lastbank', t)
p.write_text(t)
print(f'Restored {count} skip patterns')
