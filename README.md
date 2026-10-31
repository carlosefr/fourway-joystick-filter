# 4-Way Joystick Filter

The `fourway-joystick-filter.py` script takes any Linux input device that emits `ABS_HAT0X` and `ABS_HAT0Y` events and filters out diagonal movement (the last held direction wins).

Example:
```
fourway-joystick-filter.py --verbose --joystick 0
```

The filter is meant to be used with [FinalBurn Neo](https://github.com/libretro/FBNeo) under [RetroArch](https://www.retroarch.com), and for that reason the input device is referenced by its ID in [SDL](https://www.libsdl.org) joystick enumeration order, which can be obtained with:
```
fourway-joystick-filter.py --list
```

## Why?

Old arcade games like [Dig Dug](https://www.mobygames.com/game/139/dig-dug/) or [Mr. Do!](https://www.mobygames.com/game/9764/mr-do/) expect directional input from a joystick where diagonals aren't physically possible, and may not behave correctly with joysticks where two directions can be active simultaneously. This filter intends to fix that, working like a virtual joystick restrictor plate.

Other games, that also used a four-way joystick originally, might treat diagonals reasonably and not benefit from this filter at all. Your mileage may vary.
