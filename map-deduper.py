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
import sys
import typing as t

import mcworldlib as mc

if __name__ == '__main__':
    myname = osp.basename(osp.splitext(__file__)[0])
else:
    myname = __name__

log = logging.getLogger(myname)
AllMaps: 't.TypeAlias' = t.Dict[int, 'Map']


def message(*args, **kwargs):
    print(*args, **kwargs)


def parse_args(args=None):
    parser = mc.basic_parser(description=__doc__)
    commands = parser.add_subparsers(dest='cmd')
    commands.add_parser('dupes', help="List Map duplicates").set_defaults(f=duplicates)
    commands.add_parser('refs', help="Find all map references in World").set_defaults(f=map_usage)
    commands.add_parser('lost', help="Find maps with no reference in World").set_defaults(f=lost_and_found)
    return parser.parse_args(args)


def map_usage(world, _all_maps):
    message("\nMap References: (this might take a VERY long time...)")
    map_uses = {}
    try:
        for fspath, _, _, (nbtpath, name, tag) in world.walk(progress=True):
            if not name == 'map':
                continue
            map_uses.setdefault(tag, []).append((fspath, nbtpath))
            value = (f"{tag.__class__.__name__}({len(tag)})"
                     if isinstance(tag, (mc.Compound, mc.List, mc.Array)) else repr(tag))
            print("\t".join((str(fspath), str(nbtpath), name, value)))
    except KeyboardInterrupt:
        pass
    return map_uses


def lost_and_found(world, all_maps: AllMaps, map_uses=None):
    if map_uses is None:
        map_uses = map_usage(world, all_maps)

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
    return map_uses, map_lost


def duplicates(_world, all_maps: AllMaps):
    message("\nMap Duplicates:")
    map_dupes = {}
    for mapo in sorted(all_maps.values()):
        map_dupes.setdefault(mapo.key, []).append(mapo)
    for key, dupes in map_dupes.items():
        if len(dupes) > 1:
            message(key)
            for dupe in sorted(dupes):
                message(f"\t{dupe}")


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

    if args.cmd:
        args.f(world, all_maps)
        return


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
