# map-deduper
Minecraft Map Item De-duplicator and related tools

---

```
$ ./map-deduper.py --help
usage: map-deduper.py [-h] [--quiet | --verbose] [--world WORLD]
                      [--player PLAYER] [--save]
                      {list,show,dupes,refs,lost,merge} ...

De-duplicate Map items and recover lost ones
https://minecraft.fandom.com/wiki/Map_item_format

positional arguments:
  {list,show,dupes,refs,lost,merge}
    list                List all maps
    show                Print map data
    dupes               List map duplicates
    refs                Find all references in World
    lost                Find maps with no reference
    merge               Merge data from maps

optional arguments:
  -h, --help            show this help message and exit
  --quiet, -q           Suppress informative messages.
  --verbose, -v         Verbose mode, output extra info.
  --world WORLD, -w WORLD
                        Minecraft world, either its 'level.dat' file or a name
                        under '~/.minecraft/saves' folder. [Default: 'New
                        World']
  --player PLAYER, -p PLAYER
                        Player name. [Default: 'Player']
  --save, -S            Apply changes and save the world.

```

```sh
$ ./map-deduper.py -w MestreLion list
INFO: Loading World 'MestreLion': /home/rodrigo/.minecraft/saves/MestreLion
INFO: All maps:
[<Map   0: Player   OVERWORLD  0 (  384,    0)>,
 <Map   1: Player   OVERWORLD  1 (  320,   64)>,
 <Map   2: Player   OVERWORLD  2 (  192,  192)>,
 <Map   3: Player   OVERWORLD  3 (  448,  448)>,
 <Map   4: Player   OVERWORLD  4 (  960,  960)>,
 <Map   5: Treasure OVERWORLD  1 (  832,  320)>,
 <Map   6: Treasure OVERWORLD  1 (  832,  320)>,
...
 <Map  97: Player   THE_NETHER 0 ( -128, -128)>,
 <Map  98: Player   THE_NETHER 1 ( -192, -192)>,
 <Map  99: Player   THE_NETHER 2 ( -320, -320)>,
 <Map 100: Player   THE_NETHER 3 ( -576, -576)>,
 <Map 101: Player   THE_NETHER 4 (-1088,-1088)>,
 <Map 102: Treasure OVERWORLD  1 (-1216,-1216)>,
 <Map 103: Treasure OVERWORLD  1 (-1216,-1216)>,
 <Map 104: Explorer OVERWORLD  2 ( 3264, 3264)>,
 <Map 105: Explorer OVERWORLD  2 (  704,-20288)>,
...
 <Map 115: Player   OVERWORLD  4 (  960, 3008)>,
 <Map 116: Treasure OVERWORLD  1 (   64, 2112)>,
 <Map 117: Explorer OVERWORLD  2 ( 20672, 6848)>]

```
