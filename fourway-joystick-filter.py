#!/usr/bin/env python3
#
# Copyright (c) 2026, Carlos Rodrigues
#


import os
import sys
import time
import errno
import signal
import syslog
import logging
import logging.handlers
import functools

from argparse import ArgumentParser, ArgumentTypeError
from evdev import InputDevice, UInput, list_devices, ecodes
from setproctitle import setproctitle

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame  # noqa: E402


DEVICE_NAME = "4-way joystick (virtual)"
DEVICE_VENDOR_ID = 0x1234
DEVICE_PRODUCT_ID = 0x0004

SCRIPT_FILENAME = os.path.basename(__file__)

#
# Replace the process name with the script file name instead of the default "python3".
#
# Caveat: Trying to kill the process with "pkill -x <SCRIPT_FILENAME>", won't work.
#         That's because it matches against "/proc/<pid>/comm", which only contains
#         the first 15 characters of the process' name.
#
setproctitle(" ".join([SCRIPT_FILENAME] + sys.argv[1:]))

log = logging.getLogger(os.path.splitext(SCRIPT_FILENAME)[0])

pygame.init()
pygame.joystick.init()


def _non_negative_integer(value):
    try:
        number = int(value)
    except ValueError:
        raise ArgumentTypeError("invalid value (must be a non-negative integer)")

    if number < 0:
        raise ArgumentTypeError("integer out-of-range (must be non-negative)")

    return number


def daemonize():
    """Run the process in the background as a daemon."""

    try:
        # First fork to return control to the shell...
        pid = os.fork()
    except OSError as e:
        raise Exception("%s [%d]" % (e.strerror, e.errno))

    if pid:
        # Quickly terminate the parent process...
        os._exit(0)

    os.setsid()

    try:
        # Second fork to prevent zombies...
        pid = os.fork()
    except OSError as e:
        raise Exception("%s [%d]" % (e.strerror, e.errno))

    if pid:
        # Quickly terminate the parent process...
        os._exit(0)

    # To make sure we don't block an unmount in the future, in case
    # the current directory resides on a mounted filesystem...
    os.chdir("/")

    # Sanitize permissions...
    os.umask(0o022)

    # Redirect the standard file descriptors to "/dev/null"...
    f = open(os.devnull, "r")
    os.dup2(f.fileno(), sys.stdin.fileno())
    assert sys.stdin.fileno() == 0

    f = open(os.devnull, "r")
    os.dup2(f.fileno(), sys.stdout.fileno())
    assert sys.stdout.fileno() == 1

    f = open(os.devnull, "r")
    os.dup2(f.fileno(), sys.stderr.fileno())
    assert sys.stderr.fileno() == 2


def _clean_exit_handler(message, signum, frame):
    if message:
        log.info(message)

    os._exit(0)


def parse_args():
    parser = ArgumentParser(add_help=False, description="Filters D-pad events from a real joystick device "
                                                        "into a virtual 4-way (last input wins) joystick.")

    parser.add_argument("-h", "--help", action="help",
                              help="Show the available options and exit.")

    parser.add_argument("-d", "--daemon", action="store_true",
                              help="Run the joystick filter in the background.")
    parser.add_argument("-v", "--verbose", action="store_true",
                              help="Produce extra output for debugging purposes.")
    parser.add_argument("--log", action="store", metavar="<logname>",
                              help="Log messages into 'syslog' or the specified log file.")

    parser.add_argument("--joystick", dest="joynum", action="store", metavar="<index>",
                              help="The joystick device to filter, in SDL enumeration order (defaults to 0).",
                              type=_non_negative_integer, default=0)

    return parser.parse_args()


def get_input_device_path_by_id(vendor, product, occurrence=0):
    matches = []

    for path in list_devices():
        device = None

        try:
            device = InputDevice(path)
            if not (device.info.vendor == vendor and device.info.product == product):
                continue  # ...not the physical device we're looking for.

            caps = device.capabilities()
            if not (ecodes.EV_ABS in caps and ecodes.EV_KEY in caps):
                continue  # ...not the logical device we're looking for.

            matches.append((device.phys, path))
        except (OSError, PermissionError):
            pass
        finally:
            if device:
                device.close()

    matches.sort(key=lambda m: m[0])  # ...assumes identical devices will be in physical order.
    return matches[occurrence][1] if occurrence < len(matches) else None


def get_vendor_and_product_from_guid(guid):
    vendor = int(guid[10:12] + guid[8:10], 16)
    product = int(guid[18:20] + guid[16:18], 16)

    return (vendor, product)


def get_identical_device_occurrence(vendor, product, joynum):
    occurrence = 0

    for i in range(joynum):
        joystick = pygame.joystick.Joystick(i)
        guid = joystick.get_guid()

        if get_vendor_and_product_from_guid(guid) == (vendor, product):
            occurrence += 1

    return occurrence


def get_input_device_path_by_num(joynum):
    if pygame.joystick.get_count() < joynum + 1:
        return None

    joystick = pygame.joystick.Joystick(joynum)
    joystick.init()

    vendor, product = get_vendor_and_product_from_guid(joystick.get_guid())
    occurrence = get_identical_device_occurrence(vendor, product, joynum)

    return get_input_device_path_by_id(vendor, product, occurrence)


class FourWayHatFilterError(Exception):
    pass


class FourWayHatFilter:
    @classmethod
    def is_input_device_supported(_, in_device):
        caps = in_device.capabilities(absinfo=True)
        abs_codes = {ecode for ecode, _ in caps.get(ecodes.EV_ABS, [])}

        return ecodes.ABS_HAT0X in abs_codes and ecodes.ABS_HAT0Y in abs_codes

    @classmethod
    def is_input_device_busy(_, in_device):
        try:
            with in_device.grab_context():
                return False
        except OSError as e:
            if e.errno == errno.EBUSY:
                return True

    def __init__(self, in_device, out_device):
        self._in_device = in_device
        self._out_device = out_device

        if not self.is_input_device_supported(in_device):
            raise FourWayHatFilterError("input device does not support hat direction axes")

        if self.is_input_device_busy(in_device):
            raise FourWayHatFilterError("input device is already grabbed")

        self._HAT_AXIS_MAPPING = {
            ecodes.ABS_HAT0X: {-1: "L", 1: "R"},
            ecodes.ABS_HAT0Y: {-1: "U", 1: "D"},
        }

        self._HAT_DIRECTION_MAPPING = {
            self._HAT_AXIS_MAPPING[ecodes.ABS_HAT0X][-1]: (-1, 0),  # left
            self._HAT_AXIS_MAPPING[ecodes.ABS_HAT0X][1]: (1, 0),    # right
            self._HAT_AXIS_MAPPING[ecodes.ABS_HAT0Y][-1]: (0, -1),  # up
            self._HAT_AXIS_MAPPING[ecodes.ABS_HAT0Y][1]: (0, 1),    # down
            None: (0, 0),
        }

        self._last_axis_value = {ecodes.ABS_HAT0X: None, ecodes.ABS_HAT0Y: None}
        self._direction_last_held_ts = {}

    def _update_axis(self, axis_code, value):
        old_direction = self._HAT_AXIS_MAPPING[axis_code].get(self._last_axis_value[axis_code])
        new_direction = self._HAT_AXIS_MAPPING[axis_code].get(value)

        if old_direction == new_direction:
            return

        if old_direction and old_direction in self._direction_last_held_ts:
            del self._direction_last_held_ts[old_direction]

        if new_direction:
            self._direction_last_held_ts[new_direction] = time.time_ns()

        self._last_axis_value[axis_code] = value

    def _emit_dpad(self):
        active = None

        #
        # TODO: In real 4-way restricted joysticks, short-lived switches in
        #       direction aren't physically possible. We should ignore them.
        #
        if self._direction_last_held_ts:
            active = max(self._direction_last_held_ts, key=self._direction_last_held_ts.get)

        x, y = self._HAT_DIRECTION_MAPPING.get(active)

        self._out_device.write(ecodes.EV_ABS, ecodes.ABS_HAT0X, x)
        self._out_device.write(ecodes.EV_ABS, ecodes.ABS_HAT0Y, y)
        self._out_device.syn()

    def run(self):
        with self._in_device.grab_context():
            log.debug("listening for events...")

            for event in self._in_device.read_loop():
                if event.type == ecodes.EV_ABS and event.code in self._HAT_AXIS_MAPPING:
                    self._update_axis(event.code, event.value)

                elif event.type == ecodes.EV_SYN:
                    if event.code == ecodes.SYN_REPORT:
                        self._emit_dpad()
                    else:
                        continue

                else:
                    self._out_device.write_event(event)


def main():
    args = parse_args()

    if not args.log:
        handler = logging.StreamHandler(sys.stderr)
        format_string = "%(levelname)s: %(message)s"
    elif args.log.lower() in ("syslog", "/dev/log"):
        facility = syslog.LOG_DAEMON if args.daemon else syslog.LOG_USER
        handler = logging.handlers.SysLogHandler(address="/dev/log", facility=facility)
        format_string = os.path.basename(sys.argv[0]) + "[%(process)d]: %(levelname)s: %(message)s"
    else:
        handler = logging.handlers.WatchedFileHandler(os.path.realpath(os.path.abspath(args.log)))
        format_string = "%(asctime)s: %(levelname)s [%(process)d]: %(message)s"

    handler.setFormatter(logging.Formatter(format_string))
    logging.getLogger().addHandler(handler)

    # Leaving the root logger with the default level, and setting it in our own logging hierarchy
    # instead, prevents accidental triggering of third-party logging, just like $DEITY intended...
    log.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGQUIT):
        signal.signal(s, functools.partial(_clean_exit_handler, "terminated" if args.log else None))

    if not (in_device_path := get_input_device_path_by_num(args.joynum)):
        log.error("joystick device #%d: no such device", args.joynum)
        sys.exit(1)

    in_device = InputDevice(in_device_path)
    log.debug("physical joystick [#%d]: \"%s\" @ %s", args.joynum, in_device.name, in_device_path)

    if not FourWayHatFilter.is_input_device_supported(in_device):
        log.error("joystick device #%d: missing hat direction axes", args.joynum)
        sys.exit(2)

    if FourWayHatFilter.is_input_device_busy(in_device):
        log.error("joystick device #%d: already grabbed by another process", args.joynum)
        sys.exit(3)

    out_device = UInput.from_device(in_device, name=DEVICE_NAME, vendor=DEVICE_VENDOR_ID, product=DEVICE_PRODUCT_ID)
    out_device_path = get_input_device_path_by_id(DEVICE_VENDOR_ID, DEVICE_PRODUCT_ID)

    out_joynum = pygame.joystick.get_count()
    log.debug("filtered joystick [#%d]: \"%s\" @ %s", out_joynum, out_device.name, out_device_path)

    if args.daemon:
        daemonize()

    try:
        FourWayHatFilter(in_device, out_device).run()
    finally:
        out_device.close()
        in_device.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass


# EOF
