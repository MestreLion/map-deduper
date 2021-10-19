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
import os.path as osp
import pathlib
from pprint import pprint
import re
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


def walk_nbt(tag, path=None):
    """Yield 3-tuples of dot-separated tag paths, tag leaf names and corresponding values"""
    # Tag List
    if isinstance(tag, list):
        for i, item in enumerate(tag):
            yield from walk_nbt(item, f"{path}.{i}")
    # Tag Compound
    elif isinstance(tag, dict):
        for k, item in tag.items():
            yield from walk_nbt(item, f"{path}.{k}" if path else k)
    # Leaf values
    elif isinstance(tag, (str, int, float)):
        path, _, name = path.rpartition('.')
        yield path, name, tag
    elif isinstance(tag, (mc.nbt.ByteArray, mc.nbt.IntArray, mc.nbt.LongArray)):
        pass  # They're HUGE!
    else:
        log.warning("Unexpected tag type in %s=%r: %s", path, tag, type(tag))


def walk_world(world: mc.World, progress=False):
    for data in walk_nbt(world.level):
        yield ("level.dat", *data)

    for dimension, category, chunk in world.get_all_chunks(progress=progress):
        for data in walk_nbt(chunk):
            yield ("/".join((dimension.subfolder(), category, str(chunk.world_pos))), *data)
        # log.info("%s %s R%s, C%s %s: %r",
        #         dimension.name.title(), category.title(),
        #         chunk.region.pos, chunk.pos, data)


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
            self.center,
            self.is_explorer,
            self.scale,
            self.dimension.value,
        )

    @classmethod
    def load(cls, *args, **kwargs) -> 'Map':
        self: 'Map' = super().load(*args, **kwargs)
        self.filename = pathlib.Path(self.filename)
        assert self.data['trackingPosition'] == 1
        return self

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
    all_maps: t.Dict[int, Map] = {}
    for path in pathlib.Path(world.path, 'data').glob("map_*.dat"):
        mapo = Map.load(path)
        all_maps[mapo.mapid] = mapo
    # Sort it once so we don't have to anymore
    # noinspection PyTypeChecker
    # https://youtrack.jetbrains.com/issue/PY-27707
    all_maps = dict(sorted(all_maps.items()))
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

    message("\nMap Usage:")
    # for dim, cat, chunk in world.get_all_chunks(): ...




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
