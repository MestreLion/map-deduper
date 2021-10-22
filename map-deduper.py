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
import logging
import os
import os.path as osp
import pathlib
from pprint import pprint
import sys
import typing as t

import mcworldlib as mc

if __name__ == '__main__':
    myname = osp.basename(osp.splitext(__file__)[0])
else:
    myname = __name__

log = logging.getLogger(myname)


def message(*args, **kwargs):
    print(*args, **kwargs)


def parse_args(args=None):
    parser = mc.basic_parser(description=__doc__)
    return parser.parse_args(args)


def walk_nbt(root: mc.AnyTag, sort=False, _path: mc.Path = mc.Path()
             ) -> t.Tuple[mc.Path, t.Union[str, int], mc.AnyTag]:
    """Yield (path, name/index, tag) for each child of a root tag, recursively.

    The root tag itself is not yielded, and it is only considered a container
    if it is a Compound, a List of Compounds, or a List of Lists. Any other tag,
    including Arrays and Lists of other types, are considered leaf tags and not
    recurred into.

    name is the tag key (or index) location in its (immediate) parent tag, so:
        parent[name] == tag

    path is the parent tag location in the root tag, compatible with the format
    described at https://minecraft.fandom.com/wiki/NBT_path_format. So:
        root[path][name] == root[path[name]] == tag
    That holds true even when path is empty, i.e., when the parent tag is root.
    """
    # TODO: NBTExplorer-like sorting mode:
    # - Case insensitive sorting on key names
    # - Compounds first, then Lists (of all types), then leaf values
    # - For Compounds, Lists and Arrays, include item count
    items: t.Union[t.Iterable[t.Tuple[str, mc.Compound]],
                   t.Iterable[t.Tuple[int, mc.List]]]

    if isinstance(root, mc.Compound):
        items = root.items()
        if sort:
            items = sorted(items)
    elif isinstance(root, mc.List) and root.subtype in (mc.Compound, mc.List):
        items = enumerate(root)  # always sorted
    else:
        return

    for name, item in items:
        yield _path, name, item
        yield from walk_nbt(item, sort=sort, _path=_path[name])


def walk_world(world: mc.World, progress=False
               ) -> t.Tuple[t.Tuple, os.PathLike,
                            t.Tuple[mc.Path, t.Union[str, int], mc.AnyTag]]:
    for data in walk_nbt(world.level):
        yield (world.level,), pathlib.Path("level.dat"), data

    for dimension, category, chunk in world.get_all_chunks(progress=progress):
        pos = f"c.{chunk.pos.filepart}@{chunk.world_pos.filepart}"
        fspath = pathlib.Path(chunk.region.filename, pos).relative_to(world.path)
        for data in walk_nbt(chunk):
            yield (dimension, category, chunk), fspath, data


def map_usage(world):
    map_uses = {}
    try:
        for source, fspath, (nbtpath, name, tag) in walk_world(world):
            if not name == 'map':
                continue
            map_uses.setdefault(tag, []).append((fspath, nbtpath))
            value = (f"{tag.__class__.__name__}({len(tag)})"
                     if isinstance(tag, (mc.Compound, mc.List, mc.Array)) else repr(tag))
            print("\t".join((str(fspath), str(nbtpath), name, value)))
    except KeyboardInterrupt:
        pass
    return map_uses


class Map(mc.File):
    dim_map = {
        'minecraft:overworld' : mc.Dimension.OVERWORLD,
        'minecraft:the_nether': mc.Dimension.THE_NETHER,
        'minecraft:the_end'   : mc.Dimension.THE_END,
                             0: mc.Dimension.OVERWORLD,
                            -1: mc.Dimension.THE_NETHER,
                             1: mc.Dimension.THE_END,
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
    def load_all(cls, world: mc.World) -> t.Dict[int, 'Map']:
        maps = [cls.load(path) for path in
                pathlib.Path(world.path, 'data').glob("map_*.dat")]
        # Glob doesn't sort properly, so make sure insertion order by Map ID
        return {item.mapid: item for item in sorted(maps)}

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.key == other.key

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


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=args.loglevel, format='%(levelname)s: %(message)s')
    log.debug(args)

    world = mc.load(args.world)

    message("\nAll maps:")
    all_maps = Map.load_all(world=world)
    pprint(list(all_maps.values()))

    message("\nMap Duplicates:")
    map_dupes = {}
    for mapo in sorted(all_maps.values()):
        map_dupes.setdefault(mapo.key, []).append(mapo)
    for key, dupes in map_dupes.items():
        if len(dupes) > 1:
            message(key)
            for dupe in sorted(dupes):
                message(f"\t{dupe}")
    versions = {}

    message("\nMap References: (this might take a VERY long time...)")
    map_uses = map_usage(world)

    message("\nMaps Found:")
    map_lost = []
    for mapo in all_maps.values():
        print(mapo)
        for use in map_uses.get(mapo.mapid, []):
            text = '\t'.join(map(str, use))
            print(f"\t{text}")
        if mapo.mapid in map_uses:
            print()
        else:
            map_lost.append(mapo)
    message("\nUnreferenced Maps:")
    pprint(map_lost)




if __name__ == "__main__":
    try:
        sys.exit(main())
    except mc.MCError as error:
        log.error(error)
    except Exception as error:
        log.critical(error, exc_info=True)
        sys.exit(1)
    except KeyboardInterrupt:
        pass
