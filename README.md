# 4-Way Joystick Filter

The `fourway-joystick-filter.py` script takes any Linux input device that emits `ABS_HAT0X` and `ABS_HAT0Y` events and creates a virtual input device that filters out diagonal movement (the last held direction wins):
```
$ fourway-joystick-filter.py --verbose --joystick 1

DEBUG: physical joystick [#1]: "Logitech Gamepad F310" @ /dev/input/event11
DEBUG: filtered joystick [#2]: "4-way joystick (virtual)" @ /dev/input/event14
DEBUG: listening for events...
```

The filter is meant to be used with [FinalBurn Neo](https://github.com/libretro/FBNeo) under [RetroArch](https://www.retroarch.com) and, for that reason, the input device is referenced by its ID in [SDL](https://www.libsdl.org) joystick enumeration order, which can be obtained with:
```
$ fourway-joystick-filter.py --list

0: "Generic X-Box pad" [03000000790000007c18000001010000]
1: "Logitech Gamepad F310" [030000006d0400001dc2000014400000]
```

## Why?

Old arcade games like [Dig Dug](https://en.wikipedia.org/wiki/Dig_Dug) or [Mr. Do!](https://en.wikipedia.org/wiki/Mr._Do!) expect directional input from a joystick where diagonals aren't physically possible, and may not behave correctly with joysticks where two directions can be active simultaneously. This filter intends to fix that, working like a virtual joystick restrictor plate.

Other games, that also used a four-way joystick originally, might treat diagonals reasonably and not benefit from this filter at all. Your mileage may vary.

## Dependencies

The `fourway-joystick-filter.py` script needs the libraries listed in `requirements.txt` to run, but all of them should also be available from your Linux distribution's repositories. No need to fiddle around with Python virtual environments, etc.
