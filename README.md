# 4-Way Joystick Filter 🕹️

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

## How?

I use this script on a [RetroPie](https://retropie.org.uk) setup, where I have a custom [EmulationStation](https://retropie.org.uk/docs/EmulationStation/) collection with the games that benefit from it, all of them emulated with [FinalBurn Neo](https://github.com/libretro/FBNeo).

When a game is launched, the `/opt/retropie/configs/all/runcommand-onlaunch.sh` shell script is executed, which (when needed) starts the `fourway-joystick-filter.py` script as a daemon for the first couple of joysticks/gamepads connected at the time.

For the virtual input device(s) to take effect, the [RetroArch](https://www.retroarch.com) controller configuration is overriden to have them take the place of the (inhibited) physical input device(s). This override happens in `/dev/shm/retroarch.cfg` and only lasts while the game is running, so there's no configuration to revert when it terminates. But we do need to stop the input filter daemon(s), which is done unconditionally from `/opt/retropie/configs/all/runcommand-onend.sh`.

These are the bits in `runcommand-onlaunch.sh` (assuming `fourway-joystick-filter.py` exists in `$PATH`):

```bash
# (...)

readonly PARAM_SCRIPT=$(basename "$0")
readonly PARAM_EMULATOR="$2"
readonly PARAM_ROM_PATH="$3"

readonly FOURWAY_GAMES="${HOME}/.emulationstation/collections/custom-4-Way Stick Games.cfg"
readonly FOURWAY_MAX_JOYSTICKS=2

# (...)

if [[ "$PARAM_EMULATOR" == "lr-fbneo" && -f "$FOURWAY_GAMES" ]] && grep -q "^${PARAM_ROM_PATH}$" "$FOURWAY_GAMES"; then
    pkill -x 'fourway-joy.*'  # ...in case "runcommand-onend.sh" failed to kill it.
    readonly num_sdl_joysticks=$(fourway-joystick-filter.py --list | wc -l)

    for ((sdl_index = 0; sdl_index < num_sdl_joysticks && sdl_index < FOURWAY_MAX_JOYSTICKS; sdl_index++)); do
        fourway_index=$(fourway-joystick-filter.py -v -d --joystick "$sdl_index" 2>&1 | \
                        gawk 'match($0, /filtered joystick \[#([0-9]+)\]/, m) {print m[1]}')

        if [[ -z "$fourway_index" ]]; then
            echo "${PARAM_SCRIPT}: error: failed to get virtual joystick index for physical joystick #${sdl_index} [giving up]" >&2
            break
        fi

        echo "${PARAM_SCRIPT}: binding retropad device #$((fourway_index + 1)) to player port $((sdl_index + 1)) [virtual joystick]" >&2
        echo "input_player$((sdl_index + 1))_joypad_index = \"${fourway_index}\"" >>/dev/shm/retroarch.cfg

        echo "${PARAM_SCRIPT}: binding retropad device #$((sdl_index + 1)) to player port $((fourway_index + 1)) [physical joystick, disabled]" >&2
        echo "input_player$((fourway_index + 1))_joypad_index = \"${sdl_index}\"" >>/dev/shm/retroarch.cfg
    done
fi

# (...)

```

And this is all that's needed in `runcommand-onend.sh`:

```bash
# (...)

pkill -x 'fourway-joy.*'

# (...)
```
