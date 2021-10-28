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
from pprint import pprint
import sys
import typing as t

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

    return parser.parse_args(args)


def list_maps(world: str, _all_maps=None, **_kw):
    all_maps = get_all_maps(world) if _all_maps is None else _all_maps
    log.info("All maps:")
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
    map_refs = get_map_refs(world) if _map_refs is None else _map_refs
    log.info("Map references:")
    for mapitem in all_maps.values():
        print(mapitem)
        for fs, _, nbt in map_refs.get(mapitem.mapid, []):
            print(f"\t{fs}\t{nbt}")
        if mapitem.mapid in map_refs:
            print()


def lost_maps(world: str, _all_maps=None, _map_refs=None, **_kw):
    world = mc.load(world)
    all_maps = Map.load_all(world) if _all_maps is None else _all_maps
    map_refs = get_map_refs(world) if _map_refs is None else _map_refs
    map_lost = [all_maps[mapid] for mapid in all_maps if mapid not in map_refs]
    log.info("Lost maps:")
    pprint(map_lost)


def print_dupes(world: str, _dupes_map=None, **_kw):
    dupes_map = get_duplicates(get_all_maps(world)) if _dupes_map is None else _dupes_map
    log.info("Map Duplicates:")
    for key, dupes in dupes_map:
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


# -----------------------------------------------------------------------------
# Main classes

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
    def is_explorer(self) -> bool:
        return self.data['unlimitedTracking'] == 1

    @property
    def is_treasure(self) -> bool:
        return self.is_explorer and self.scale == 1

    @property
    def maptype(self) -> str:
        return ('Treasure' if self.is_treasure else
                'Explorer' if self.is_explorer else
                'Player')

    @property
    def scale(self) -> int:
        return int(self.data['scale'])

    @property
    def key(self) -> tuple:
        return (
            self.dimension.value,
            self.center,
            self.is_explorer,
            self.scale,
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

    def __lt__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.mapid < other.mapid

    def __repr__(self):
        sig = (
            f"{self.mapid:3}:"
            f" {self.maptype:8}"
            f" {self.dimension.name:10} {self.scale} {self.center}"
        )
        return f"<Map {sig}>"

    __str__ = __repr__


DiffValue: 't.TypeAlias' = t.Union[
    # Actual type depends on category
    mc.TagKey,  # missing
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


def get_map_refs(world: mc.World) -> t.Dict[int, t.Tuple['os.PathLike', mc.Root, mc.Path]]:
    # Theoretically, tag type is mc.AnyTag, but as we're filtering name == "map",
    # then we know it'll only be mc.Int, as tag == mapid
    log.info("Searching Map references in %r, this might take a VERY long time...",
             world.name)
    refs = {}
    try:
        for fspath, _, root, nbt in world.walk(progress=True):
            if not nbt.key == 'map':
                continue
            refs.setdefault(int(nbt.tag), []).append((fspath, root, nbt.path[nbt.key]))
            log.debug("%s\t%s\t%s\t%r", fspath, nbt.path, nbt.key, nbt.tag)
    except KeyboardInterrupt:
        pass
    log.info("References found: %d",
             sum(len(_) for _ in refs.values()))
    return refs


def merge_map(source: Map, target: Map):
    i = 0
    changes: t.List[t.Tuple[int, mc.Byte]] = []
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

        if diff.source == 0:
            continue

        if not diff.target == 0:
            raise mc.MCError("Maps %s and %s can't be merged, conflicting values"
                             " for the same color index: %s",
                             source.mapid, target.mapid, diff)

        changes.append((diff.key, diff.source))

    if not i:
        log.info("Maps %s and %s are absolutely identical!",
                 source.mapid, target.mapid)
        assert source == target
        return

    if not changes:
        log.info("%s differences from %s, but no changes required in %s",
                 i, source.mapid, target.mapid)
        assert not any(source[mc.Path("data.colors")])
        return

    log.info("%s differences from %s, %s changes required in %s",
             i, len(changes), source.mapid, target.mapid)
    pprint(changes)
    raise NotImplementedError
    # apply changes


def get_map_diffs(source: Map, target: Map):
    def add_diff(category, source_value, target_value):
        return TagDiff(category=category, path=data.path, key=data.key,
                       source=source_value, target=target_value)
    for data in mc.deep_walk(source):
        src = data.tag  # source
        if data.path[data.key] not in target:
            # If container, should prune its whole subtree
            yield add_diff("missing", src, None)
            continue
        tag = target[data.path][data.key]  # target
        if not type(tag) == type(src):
            yield add_diff("type", type(src), type(tag))
            continue
        if data.is_container:
            if not len(tag) == len(src):
                yield add_diff("length", len(src), len(tag))
                continue
        else:
            if not tag == src:
                yield add_diff("value", src, tag)
                continue


def get_duplicates(all_maps: t.Dict[int, Map]) -> t.Iterator[t.Tuple[t.Tuple, t.List[Map]]]:
    map_dupes = {}
    for mapitem in all_maps.values():
        map_dupes.setdefault(mapitem.key, []).append(mapitem)
    for key, dupes in map_dupes.items():
        if len(dupes) > 1:
            yield key, dupes

# Plan:
# Merge 115 into 114, 113 in 112, 111 in 110, 109 in 108
# Delete 115, 113, 111, 109
# Move 110 to 109, 112 to 110, 114 to 111 - no ref
# move 116 to 112, 117 to 113
# update refs 116 to 112, 117 to 113
# update idcounts.dat to 114
#
# - Find dupes
# 	- Merge with highest DataValue, lowest ID
# - Find clones
# 	- Update references to lowest ID
# - Find lost with referenced clones
# 	- delete
# - get missing
# 	- move next -> missing
# 	- update refs

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
