"""Conservative ROM dedup: keep one ROM per English title.

Groups every .nes/.fds under the source by the English title (the Chinese
prefix and the (region)/(Rev) tags are ignored).  The keeper is chosen by:

  region:    World > USA > Japan,USA > Europe > Japan > other
  publisher: plain release > Collection/Namco/Victor/AM/BPS
  revision:  higher Rev first

Dry-run is the default.  --apply moves each removed ROM plus its same-stem
.COV to a quarantine directory outside NES, remaps PREFS0/1.DAT path keys to
the keeper, and renames CATALOG.IDX/.NEW/.BAK to .OLD so the firmware rescans.

Hacks, translations, prototypes, betas, demos and bootlegs are protected:
they are excluded from grouping and never moved, even when they share the
retail title or live beside it.  Files under a hacks/ directory are protected
as well.

    python tools/dedup_sd.py F:/NES/famicom
    python tools/dedup_sd.py F:/NES/famicom --apply
"""
import argparse
import json
import re
import time
from pathlib import Path

import bucket_sd

ROM_SUFFIXES = ('.nes', '.fds')

# Files carrying these tags are hacks, translations, unreleased or bootleg
# builds.  They often share the retail title, so they must never be grouped
# with the original and moved away as a "duplicate".
PROTECTED_TAGS = {
    'hack', 'kaizo', 'kaoshi', 'translation', 'pirate', 'bootleg', 'unl',
    'proto', 'beta', 'demo', 'homebrew', 'patch', 'trainer', 'sample',
}
PROTECTED_RE = re.compile(r'\[h\d*\]|\[h[ab]\]', re.IGNORECASE)
TRANSLATION_RE = re.compile(
    r't[+-]?(eng|chi|chinese|jpn|japanese|rus|ger|fre|spa|ita|kor|por|dut|swe)$',
    re.IGNORECASE)


def is_protected(path):
    """True for hacks/translations/betas that must survive a dedup run."""
    lowered = {part.lower() for part in path.parts}
    if 'hacks' in lowered or 'hack' in lowered:
        return True
    if PROTECTED_RE.search(path.stem):
        return True
    for match in re.findall(r'\(([^)]*)\)|\[([^\]]*)\]', path.stem):
        tag = (match[0] or match[1]).strip().lower()
        if not tag:
            continue
        if tag in PROTECTED_TAGS or TRANSLATION_RE.match(tag):
            return True
        if tag.startswith(('hack', 'kaizo', 'translat')):
            return True
    return False


def english_title(path):
    stem = path.stem
    match = re.match(r'^\[[^\]]*\]\[[^\]]*\](.*)$', stem)
    rest = match.group(1) if match else stem
    return re.split(r'\s*[\(\[]', rest, maxsplit=1)[0].strip()


def normalized(title):
    return re.sub(r'[^0-9a-z]+', '', title.lower())


def region_rank(name):
    if '(World)' in name:
        return 0
    if '(Japan, USA)' in name or '(USA, Japan)' in name:
        return 2
    if '(USA)' in name or re.search(r'\((?:U|USA)\)', name):
        return 1
    if '(Europe)' in name or re.search(r'\(E\)', name):
        return 3
    if '(Japan)' in name or re.search(r'\(J\)', name):
        return 4
    return 5


def publisher_rank(name):
    tags = set(re.findall(r'\(([^)]*)\)', name))
    return 1 if tags & {'Collection', 'Namco', 'Victor', 'AM', 'BPS'} else 0


def revision(name):
    match = re.search(r'\(Rev (\d+)\)', name)
    return int(match.group(1)) if match else 0


def score(path):
    return (region_rank(path.name), publisher_rank(path.name),
            -revision(path.name), path.name.lower())


def cover_for(rom):
    for suffix in ('.COV', '.cov'):
        candidate = rom.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source', type=Path,
                        help='ROM directory to dedup, e.g. F:/NES/famicom')
    parser.add_argument('--apply', action='store_true',
                        help='move files; default is dry-run')
    parser.add_argument('--quarantine', type=Path,
                        help='removed-file directory; defaults to _dedup_removed_<time> '
                             'beside the NES folder (outside the scanned tree)')
    parser.add_argument('--keep-prefs', action='store_true',
                        help='do not remap favorites/recent keys')
    parser.add_argument('--keep-catalog', action='store_true',
                        help='do not reset CATALOG.IDX/.NEW/.BAK')
    parser.add_argument('--json', action='store_true', help='machine-readable plan')
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.is_dir():
        raise SystemExit(f'Not a directory: {source}')

    roms = sorted((p for p in source.rglob('*')
                   if p.is_file() and p.suffix.lower() in ROM_SUFFIXES),
                  key=lambda p: p.as_posix().lower())
    if not roms:
        raise SystemExit('No .nes/.fds files under the source directory.')

    protected = [p for p in roms if is_protected(p)]
    roms = [p for p in roms if not is_protected(p)]
    if not roms:
        print(f'No unprotected ROMs under {source}; nothing to dedup.')
        return

    groups = {}
    for rom in roms:
        groups.setdefault(normalized(english_title(rom)), []).append(rom)

    keepers = []
    removed = []
    for title, files in groups.items():
        files.sort(key=score)
        keepers.append(files[0])
        removed.extend((rom, files[0]) for rom in files[1:])

    pairs = []
    missing_covers = []
    for rom, keeper in removed:
        cover = cover_for(rom)
        if cover is None:
            missing_covers.append(rom.name)
        pairs.append((rom, cover, keeper))

    root = source.parent
    key_map = {}
    for rom, _, keeper in pairs:
        old_rel = f'{source.name}/{rom.relative_to(source).as_posix()}'
        new_rel = f'{source.name}/{keeper.relative_to(source).as_posix()}'
        key_map[bucket_sd.path_key(old_rel)] = bucket_sd.path_key(new_rel)

    prefs = [root / 'PREFS0.DAT', root / 'PREFS1.DAT']
    pref_counts = {}
    if not args.keep_prefs:
        for path in prefs:
            if path.exists():
                count = bucket_sd.count_pref_changes(path, key_map)
                if count is not None:
                    pref_counts[path.name] = count

    catalogs = [root / name for name in ('CATALOG.IDX', 'CATALOG.NEW', 'CATALOG.BAK')]
    catalog_reset = [p for p in catalogs if p.exists()]

    quarantine = args.quarantine or (root.parent /
                                     f'_dedup_removed_{time.strftime("%Y%m%d_%H%M%S")}')

    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    if args.json:
        print(json.dumps({
            'source': str(source),
            'roms': len(roms),
            'protected': [str(p.relative_to(source)) for p in protected],
            'titles': len(groups),
            'duplicate_groups': len(dup_groups),
            'keep': len(keepers),
            'remove': len(removed),
            'missing_covers': missing_covers,
            'prefs': pref_counts,
            'catalog_reset': [p.name for p in catalog_reset],
            'quarantine': str(quarantine),
            'keepers': [str(k.relative_to(source)) for k in keepers],
            'removed': [{'file': str(r.relative_to(source)),
                         'cover': str(c.relative_to(source)) if c else None,
                         'keeper': str(k.relative_to(source))}
                        for r, c, k in pairs],
        }, ensure_ascii=False, indent=2))
        return

    print(f'source: {source}')
    print(f'roms: {len(roms)}  english titles: {len(groups)}  '
          f'duplicate groups: {len(dup_groups)}  keep: {len(keepers)}  remove: {len(removed)}')
    if protected:
        print(f'  protected (hack/translation/beta), left untouched: {len(protected)}')
        for name in protected[:8]:
            print(f'    {name.relative_to(source)}')
    if missing_covers:
        print(f'  removed files without a matching .COV: {len(missing_covers)}')
        for name in missing_covers[:8]:
            print(f'    {name}')
    print('  examples:')
    for _, files in sorted(dup_groups.items(), key=lambda kv: -len(kv[1]))[:12]:
        files = sorted(files, key=score)
        print(f'    {len(files)}x -> keep {files[0].name}')
        for rom in files[1:]:
            print(f'        remove {rom.name}')
    if pref_counts:
        print('favorites/recent keys to remap:')
        for name, count in pref_counts.items():
            print(f'  {name}: {count}')
    elif not args.keep_prefs:
        print('favorites/recent keys to remap: none (no valid PREFS file)')
    if catalog_reset:
        print('catalog reset: ' + ', '.join(p.name + ' -> ' + p.name + '.OLD' for p in catalog_reset))
    else:
        print('catalog reset: no catalog file present')
    print(f'quarantine: {quarantine}')

    targets = []
    for rom, cover, _ in pairs:
        targets.append(quarantine / rom.relative_to(source))
        if cover is not None:
            targets.append(quarantine / cover.relative_to(source))
    conflicts = [str(p) for p in targets if p.exists()]
    if conflicts:
        raise SystemExit('Quarantine destination already exists; nothing moved:\n  '
                         + '\n  '.join(conflicts[:10]))

    if not args.apply:
        print('dry-run only; pass --apply to move the files.')
        return

    for count, (rom, cover, _) in enumerate(pairs, 1):
        destination = quarantine / rom.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        bucket_sd.move_file(rom, destination)
        if cover is not None:
            cover_destination = quarantine / cover.relative_to(source)
            cover_destination.parent.mkdir(parents=True, exist_ok=True)
            bucket_sd.move_file(cover, cover_destination)
        if count % 50 == 0 or count == len(pairs):
            print(f'moved {count}/{len(pairs)} ROM+COV pairs')

    if not args.keep_prefs:
        for path in prefs:
            if path.exists():
                changed = bucket_sd.remap_prefs(path, key_map)
                if changed:
                    print(f'remapped {changed} keys in {path.name}')

    if not args.keep_catalog:
        for path in catalog_reset:
            target = path.with_name(path.name + '.OLD')
            if target.exists():
                target.unlink()
            path.replace(target)

    print('done. Reinsert the card and power on once to rebuild the catalog.')


if __name__ == '__main__':
    main()
