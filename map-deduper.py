#!/usr/bin/env python3
#
#    Copyright (C) 2021 Rodrigo Silva (MestreLion) <linux@rodrigosilva.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program. See <http://www.gnu.org/licenses/gpl.html>

"""
De-duplicate Map items and recover lost ones

https://minecraft.fandom.com/wiki/Map_item_format
"""
import argparse
import logging
import pathlib
from pprint import pprint, pformat
import sys
import typing as t

import numpy as np
import mcworldlib as mc

if t.TYPE_CHECKING:
    import os

log = logging.getLogger(__name__)
AllMaps: 't.TypeAlias' = t.Dict[int, 'Map']


# -----------------------------------------------------------------------------
# CLI functions

def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=args.loglevel, format='%(levelname)s: %(message)s')
    log.debug(args)

    if args.cmd:
        args.f(**vars(args))
        return


def parse_args(args=None):
    parser = mc.basic_parser(description=__doc__)
    commands = parser.add_subparsers(dest='cmd')

    # Frequent subcommand arguments
    mapid = argparse.ArgumentParser(add_help=False)
    mapid.add_argument('mapid', type=int, help="Map ID")

    maps = argparse.ArgumentParser(add_help=False)
    maps.add_argument('maps', nargs='+', type=int, help="Map IDs")

    # Subcommands
    commands.add_parser('list',   help="List all maps").set_defaults(f=list_maps)
    commands.add_parser('show',   help="Print map data", parents=[maps]).set_defaults(f=show_maps)
    commands.add_parser('search', help="Search all map references").set_defaults(f=search_maps)
    commands.add_parser('lost',   help="Find maps with no reference").set_defaults(f=lost_maps)
    commands.add_parser('dupes',  help="List map duplicates").set_defaults(f=print_dupes)
    commands.add_parser('merge',  help="Merge into a target map data from other maps",
                        parents=[mapid, maps]).set_defaults(f=merge)
    commands.add_parser('dedupe', help="De-duplicate all maps in world").set_defaults(f=dedupe)
    commands.add_parser('defrag', help="Defragmentate world maps list").set_defaults(f=defrag)

    return parser.parse_args(args)


def list_maps(world: str, _all_maps=None, _label="", **_kw):
    all_maps = get_all_maps(world) if _all_maps is None else _all_maps
    log.info("%s maps:", _label or "All")
    pprint(list(all_maps.values()))


def show_maps(world: str, maps: list, **_kw):
    world = mc.load(world)
    for mapid in maps:
        try:
            mapitem = Map.load_by_id(mapid, world)
        except mc.MCError as e:
            log.error(e)
            continue
        log.info("Map %d: %s", mapid, mapitem.filename)
        mc.pretty(mapitem)


def search_maps(world: str, _all_maps=None, _map_refs=None, **_kw):
    world = mc.load(world)
    all_maps = Map.load_all(world) if _all_maps is None else _all_maps
    map_refs, partial = get_map_refs(world) if _map_refs is None else _map_refs
    log.info("Map references%s:", " (partial)" if partial else "")
    for mapitem in all_maps.values():
        print(mapitem)
        for data in map_refs.get(mapitem.mapid, []):
            print(f"\t{data.path}\t{data.fqtag.path[data.fqtag.key]}")
        if mapitem.mapid in map_refs:
            print()


def lost_maps(world: str, _all_maps=None, _map_refs=None, **_kw):
    world = mc.load(world)
    all_maps = Map.load_all(world) if _all_maps is None else _all_maps
    map_refs, partial = get_map_refs(world) if _map_refs is None else _map_refs
    map_lost = [all_maps[mapid] for mapid in all_maps if mapid not in map_refs]
    log.info("Lost maps%s:", " in partial data" if partial else "")
    pprint(map_lost)


def print_dupes(world: str, _dupes_map=None, **_kw):
    dupes_map = _dupes_map
    if dupes_map is None:
        dupes_map = dict(get_duplicates(get_all_maps(world)))
    log.info("Map Duplicates:")
    for key, dupes in dupes_map.items():
        print(key)
        for dupe in sorted(dupes):
            print(f"\t{dupe}")


def merge(world: str, mapid: int, maps: t.List[int], **_kw):
    world = mc.load(world)
    target = Map.load_by_id(mapid, world)
    sources = [Map.load_by_id(_, world) for _ in maps]
    if not sources:
        raise mc.MCError("No sources to merge")

    log.info("Merging %s into %s", sources, target)
    for source in sources:
        merge_map(source, target)  # raise if too different
        # update references in world: source -> target


# Plan:
# Merge 115 into 114, 113 in 112, 111 in 110, 109 in 108
# Delete 115, 113, 111, 109
# Move 110 to 109, 112 to 110, 114 to 111 - no ref
# move 116 to 112, 117 to 113
# update refs 116 to 112, 117 to 113
# update idcounts.dat to 114
def dedupe(world: str, **_kw) -> None:
    """De-duplicate maps list by merging pixels and removing unreferenced maps

    - For each set of duplicates, choose a suitable target and candidate sources
    - Sources are suitable candidates for merging pixels if:
        - Unreferenced (lost) in World
        - DataValue not greater than target
        - No other difference to target besides pixels
    - Merge maps: apply in originally blank target pixels all non-blank source ones
    - Delete merged source maps from disk
    - "Defragmentate" maps list:
        - Find all missing map files according to idcounts.dat
        - For each missing, move next (if any) and update its references (if any)
        - Update final idcounts.dat
    """
    # Find Duplicates
    world = mc.load(world)
    log.info("De-duplicating Player maps in World %r", world.name)
    all_maps = Map.load_all(world)  # for defrag_maps()
    maps = {k: v for k, v in all_maps.items() if v.is_player}
    log.debug("Player maps:\n%s", pformat(list(maps.values())))
    dupes_map = dict(get_duplicates(maps))
    if not dupes_map:
        log.info("No duplicate maps!")
        return

    # Choose Target and Candidates
    sources : t.Dict[int, t.Tuple[Map, Map, t.List[MapPixel]]] = {}
    # Sources ordering is important not only to select the correct target,
    # but also to apply pixels from least to most significant source.
    # So always loop sources by insertion order and don't re-sort it
    for dupes in dupes_map.values():
        dupes.sort(key=lambda _: (_.data_version, -_.mapid))
        target, candidates = dupes.pop(), dupes
        log.debug("Target %s, source candidates: %s", target, candidates)
        for source in candidates:
            assert source.mapid not in sources
            mergeable, pixels = can_merge(source, target)
            if mergeable:
                sources[source.mapid] = source, target, pixels
    if not sources:
        log.info("No mergeable maps!")
        return

    log.info("Candidates for merging and removal:\n\t%s",
             "\n\t".join(f"{source!r} into {target!r}, pixels to merge: {len(pixels)}"
                         for source, target, pixels in sources.values()))

    # Rule out sources with references in world
    # This is important, as we're not updating references from source to target!
    refs, partial = get_map_refs(world)
    if partial:
        log.warning("World scanning aborted, changes will not be applied")
    sources = {mapid: sources[mapid] for mapid in sources if mapid not in refs}
    if not sources:
        log.info("All candidates maps have references in world, can only merge lost maps")
        return

    # Merge and delete
    for source, target, pixels in sources.values():
        if pixels:
            log.info("Merging %d pixels from %s into target %s",
                     len(pixels), source, target)
            apply_pixels(target, pixels)
            assert len(get_pixels_to_apply(source, target)[0]) == 0  # Why so careful?
            if not partial:
                target.save()
        log.info("Removing %s", source)
        if not partial:
            filename = pathlib.Path(source.filename)
            filename.rename(filename.with_suffix(".bak"))

    # Defragment
    defrag_maps(world, maps=all_maps, refs=refs)


def defrag(world: str, _world=None, _all_maps=None, _map_refs=None, **_kw):
    world = mc.load(world) if _world is None else world
    defrag_maps(world, maps=_all_maps, refs=_map_refs)


# -----------------------------------------------------------------------------
# Main classes

class MapKey(t.NamedTuple):
    """Key for comparing Maps and determine duplicates"""
    dimension: mc.Dimension
    center:    mc.FlatPos
    is_player: bool
    scale:     int

    def __repr__(self):
        return f"{self.dimension.name:10} {Map.get_category(self):8} map at {self.center}"


class Map(mc.File):
    dim_map = {
        'minecraft:overworld' : mc.OVERWORLD,
        'minecraft:the_nether': mc.THE_NETHER,
        'minecraft:the_end'   : mc.THE_END,
                             0: mc.OVERWORLD,
                            -1: mc.THE_NETHER,
                             1: mc.THE_END,
    }

    @property
    def data_version(self) -> int:
        return int(self['DataVersion'])

    @property
    def data(self) -> mc.Compound:
        return self['data']

    @property
    def mapid(self) -> int:
        return int(self.filename.stem.split('_')[-1])

    @property
    def center(self) -> mc.FlatPos:
        return mc.FlatPos.from_tag(self.data, suffix='Center')

    @property
    def dimension(self) -> mc.Dimension:
        return self.dim_map[self.data['dimension']]

    @property
    def is_player(self) -> bool:
        return self.data['unlimitedTracking'] == 0  # 1 otherwise

    @property
    def is_treasure(self) -> bool:
        # More efficient than category == 'Treasure', duplicates .get_category() logic
        return not self.is_player and self.scale == 1

    @property
    def is_explorer(self) -> bool:
        # More efficient than category == 'Explorer', duplicates .get_category() logic
        return not self.is_player and self.scale == 2

    @property
    def category(self) -> str:
        return self.get_category(self.key)

    @property
    def scale(self) -> int:
        return int(self.data['scale'])

    @property
    def key(self) -> MapKey:
        return MapKey(
            dimension = self.dimension,
            center    = self.center,
            is_player = self.is_player,
            scale     = self.scale,
        )

    @classmethod
    def load(cls, filename: mc.AnyPath, *args, **kwargs) -> 'Map':
        self: 'Map' = super().load(filename, *args, **kwargs)
        self.filename = pathlib.Path(self.filename)
        assert self.data['trackingPosition'] == 1
        return self

    @classmethod
    def load_by_id(cls, mapid: int, world: mc.World, *args, **kwargs) -> 'Map':
        try:
            return cls.load(pathlib.Path(world.path, f'data/map_{mapid}.dat'),
                            *args, **kwargs)
        except FileNotFoundError as e:
            raise mc.MCError(f"Map {mapid} not found in world {world.name!r}: {e}")

    @classmethod
    def load_all(cls, world: mc.World) -> t.Dict[int, 'Map']:
        maps = [cls.load(path) for path in
                pathlib.Path(world.path, 'data').glob("map_*.dat")]
        # Glob doesn't sort properly, so make sure insertion order by Map ID
        return {item.mapid: item for item in sorted(maps)}

    @classmethod
    def get_category(cls, key: MapKey):
        return ('Player'   if key.is_player else
                'Treasure' if key.scale == 1 else
                'Explorer' if key.scale == 2 else
                'Unknown')

    def __lt__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.mapid < other.mapid

    def __repr__(self):
        sig = (
            f"{self.mapid:3}:"
            f" {self.dimension.name:10} {self.category:8}"
            f" {self.scale} {self.center}"
        )
        return f"<Map {sig}>"

    __str__ = __repr__


MapPixel: 't.TypeAlias' = t.Tuple[int, mc.Byte]  # Index, Value in 'data.colors'
DiffValue: 't.TypeAlias' = t.Union[
    # Actual type depends on category
    None,       # missing key
    t.Type,     # type
    int,        # length
    mc.AnyTag,  # value
]


class TagDiff(t.NamedTuple):
    """Hold a single difference between a source and a target"""
    category: str         # Type of difference: missing, type, length or value
    path:     mc.Path     # Path to source tag
    key:      mc.TagKey   # Source tag name or index in its container
    source:   DiffValue   # Diff value in in source. Type depends on category
    target:   DiffValue   # Diff value in in target


# -----------------------------------------------------------------------------
# Auxiliary and Business logic functions

def get_all_maps(world: str):
    return Map.load_all(world=mc.load(world))


def get_map_refs(world: mc.World) -> t.Tuple[t.Dict[int, mc.FQWorldTag], bool]:

    # Theoretically, tag type is mc.AnyTag, but as we're filtering name == "map",
    # then we know it'll only be mc.Int, as tag == mapid
    log.info("Searching Map references in %r, this might take a VERY long time...",
             world.name)
    refs = {}
    aborted = False
    try:
        for data in world.walk(progress=(log.level == logging.INFO)):
            nbt = data.fqtag
            if not nbt.key == 'map':
                continue
            refs.setdefault(int(nbt.tag), []).append(data)
            log.debug("%s\t%s\t%s\t%r", data.path, nbt.path, nbt.key, nbt.tag)
    except KeyboardInterrupt:
        aborted = True
    log.info("Map references found: %d",
             sum(len(_) for _ in refs.values()))
    return refs, aborted


def merge_map(source: Map, target: Map):
    changes, diffs = get_pixels_to_apply(source, target)
    if not diffs:
        log.info("Maps %s and %s are absolutely identical!",
                 source.mapid, target.mapid)
        assert source == target
        return

    if not changes:
        log.info("%s differences from %s, but no changes required in %s",
                 diffs, source.mapid, target.mapid)
        assert not any(source[mc.Path("data.colors")])
        return

    log.info("%s differences from %s, %s changes required in %s: %s",
             diffs, len(changes), source.mapid, target.mapid, pformat(changes))
    apply_pixels(target, changes)
    assert len(get_pixels_to_apply(source, target)[0]) == 0
    target.save()


def get_map_diffs(source: Map, target: Map) -> t.Iterator[TagDiff]:
    def evaluate(data: mc.FQTag) -> t.Tuple[str, DiffValue, DiffValue]:
        src = data.tag  # source
        if data.path[data.key] not in target:
            # If container, should prune its whole subtree
            return "missing", None, None
        tag = target[data.path][data.key]  # target
        if not type(tag) == type(src):
            return "type", type(src), type(tag)
        if data.is_container:
            if not len(tag) == len(src):
                return "length", len(src), len(tag)
        else:
            if not tag == src:
                return "value", src, tag
        return "", None, None
    for full_tag in mc.deep_walk(source):
        category, source_value, target_value = evaluate(full_tag)
        if category:
            yield TagDiff(
                category = category,
                path     = full_tag.path,
                key      = full_tag.key,
                source   = source_value,
                target   = target_value,
            )


def can_merge(source: Map, target: Map) -> t.Tuple[bool, t.List[MapPixel]]:
    try:
        return True, get_pixels_to_apply(source, target)[0]
    except mc.MCError as e:
        log.info(e)  # debug
        return False, []


def get_pixels_to_apply(source: Map, target: Map) -> t.Tuple[t.List[MapPixel], int]:
    i = 0
    pixels: t.List[MapPixel] = []
    for i, diff in enumerate(get_map_diffs(source, target), 1):
        if not diff.category == "value":
            raise mc.MCError("Maps %s and %s can't be merged: %s",
                             source.mapid, target.mapid, diff)

        if diff.path[diff.key] == mc.Path("DataVersion"):
            if not diff.target >= diff.source:
                raise mc.MCError("Maps %s and %s can't be merged, target DataVersion"
                                 " must be at least equal to source's: %s < %s [%s",
                                 source.mapid, target.mapid, diff.source, diff.target, diff)
            continue

        if not diff.path == mc.Path("data.colors"):
            raise mc.MCError("Maps %s and %s can't be merged, they must diverge"
                             " only on colors data: %s",
                             source.mapid, target.mapid, diff)

        if diff.source and not diff.target:
            pixels.append((diff.key, diff.source))

    return pixels, i


def apply_pixels(target: Map, pixels: t.Iterable[MapPixel]) -> None:
    arr = target.data['colors']
    # NBT Arrays might be implemented by the NBT backend as read-only ndarray views
    # If so, set the pixels in a (writeable) copy, then write back preserving original type
    cls = None
    if isinstance(arr, np.ndarray) and not arr.flags.writeable:
        cls = arr.__class__
        arr = arr.copy()
    for pixel in pixels:
        arr[pixel[0]] = pixel[1]
    if cls:
        target.data['colors'] = cls(arr)


def get_duplicates(all_maps: t.Dict[int, Map]) -> t.Iterator[t.Tuple[MapKey, t.List[Map]]]:
    map_dupes = {}
    for mapitem in all_maps.values():
        map_dupes.setdefault(mapitem.key, []).append(mapitem)
    for key, dupes in map_dupes.items():
        if len(dupes) > 1:
            yield key, dupes


def defrag_maps(world: mc.World, maps=None, refs=None):
    """Move map files to missing IDs and update idcounts.dat, updating World references
        - Find all missing map files according to idcounts.dat
        - For each missing, move next (if any) and update its references (if any)
        - Update final idcounts.dat
    """
    maps = Map.load_all(world) if maps is None else maps
    shift_map = {m: i for i, m in enumerate(maps) if i < m}
    log.info("Maps to shift:\n\t%s",
             "\n\t".join(f"{k} -> {v}" for k, v in shift_map.items()))
    maxid = len(maps) - 1
    log.info("New ID in idcounts.dat: %s", maxid)

    if shift_map:
        refs, partial = get_map_refs(world) if refs is None else refs


    idcounts = mc.load_dat(pathlib.Path(world.path).joinpath('data/idcounts.dat'))
    maxid_path = mc.Path("data.map")
    old_maxid = idcounts[maxid_path]
    if old_maxid == maxid:
        log.info("No adjustments are needed in idcounts.dat")
    else:
        log.info("idcounts.dat: %s -> %s", old_maxid, maxid)


if __name__ == "__main__":
    log = logging.getLogger(pathlib.Path(__file__).stem)
    try:
        sys.exit(main())
    except mc.MCError as error:
        log.error(error)
    except Exception as error:
        log.critical(error, exc_info=True)
        sys.exit(1)
    except KeyboardInterrupt:
        pass
