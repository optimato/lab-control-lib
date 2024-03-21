"""
Custom "spec"-inspired Magic commands for interactive use in ipython

%magiclist: display list of commands
%mva: move motor by absolute value (%amv motor position)
%mvr: move motor by relative value (%mvr motor displacement)
%wm: print (possibly all) motor positions (%wm [motor1] [motor2] [...])
%pset: set motor position (%pset motor1 position1 [motor2 position2] [...])
%lm: show soft motor limits
%set_lm: Set soft motor limits

TODO (among others)
general status
save / goto positions
snap
flat

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
import os.path

import IPython
import time
import re
import traceback

from ..util import Future
from .. import motors, drivers

ipython = IPython.get_ipython()

magic_list = {}

def collect_magic_info(f):
    magic_list[f.__name__] = f
    return f

def activate():
    """
    Activate spec magics
    """
    if not ipython:
        raise RuntimeError('Spec magics can be activated only within an IPython session.')

    for name, f in magic_list.items():
        ipython.register_magic_function(f)


@collect_magic_info
def lcrun(line):
    """
    Run a script and copy this script into the created scan directories.

    Syntax: lcrun script [eventually other run parameters like -i]
    """

    if not line:
        print("Syntax: lcrun script [eventually other run parameters like -i]")
        return

    man = drivers.get('manager', None)
    if man is None:
        raise RuntimeError('No access to manager.')

    # Extract file name, store in memory
    matches = re.findall(r"\b([^ .]+\.py)\b", line)
    if not matches:
        print(f"No file of the form *.py in '{line}'??")
        return
    if len(matches):
        print(f"{len(matches)} file(s) of the form *.py in '{line}'??")
    script_name = matches[0]
    code = open(script_name, 'rt').read()

    script_name = os.path.split(script_name)[-1]

    kill_thread = False
    def check_new_scans():
        """
        Periodically check if a new scan has appeared
        """
        scans = []
        try:
            while True:
                scan_path = man.scan_path
                if scan_path and scan_path not in scans:
                    scans.append(scan_path)
                    script_path = os.path.join(scan_path, script_name)
                    open(script_path, 'wt').write(code)
                    print(f'Script code added at {script_path}')
                for i in range(10):
                    if kill_thread:
                        return
                    time.sleep(.1)

        except BaseException:
            print(traceback.format_exc())
            return

    # Start check_new_scans on a thread
    f = Future(check_new_scans)

    # Run script
    ipython.run_line_magic("run", line)

    # Kill thread
    kill_thread = True
    f.join()

@collect_magic_info
def mva(line):
    """
    Move command (absolute). use mvr for move relative
    Syntax: mva <component> <parameter>"""

    if not line:
        print('Syntax: mva motor1 position1 [motor2 position2] [...]')
        return

    args = line.split()

    pairlist = []
    try:
        while args:
            pairlist.append((args.pop(0), float(args.pop(0))))
    except:
        print('mva: Syntax error.')
        return

    # Move all motors simultaneously (block=False)
    tlist = [motors[m].mv(p, block=False) for m, p in pairlist]

    # tlist contains a list of threads responsible for all movements.
    for t in tlist:
        t.join()


@collect_magic_info
def mvr(line):
    """
    Move command (relative). Use mva for absolute move
    Syntax: mvr <component> <parameter>"""

    if not line:
        print('Syntax: mvr motor1 position1 [motor2 position2] [...]')
        return

    args = line.split()

    pairlist = []
    try:
        while args:
            pairlist.append((args.pop(0), float(args.pop(0))))
    except:
        print('mvr: Syntax error.')
        return

    # Move all motors simultaneously (block=False)
    tlist = [motors[m].mvr(x, block=False) for m, x in pairlist]

    # tlist contains a list of threads responsible for all movements.
    for t in tlist:
        t.join()

@collect_magic_info
def wm(line):
    """
    Where motors: print the current positions of selected (or all) motors.
    """
    mnames = line.split()
    if not mnames:
        mlist = motors
    else:
        mlist = {}
        for m in mnames:
            try:
                mlist[m] = motors[m]
            except KeyError:
                print(('Unknown motor: "%s"' % m))
                return

    str_out = '                user          dial    \n'
    str_out += '--------------------------------------\n'
    for mname, mot in list(mlist.items()):
        dial, user = mot.where()
        str_out += '{:^10}  {:^12.4f}  {:^12.4f}  \n'.format(mname, user, dial)

    print(str_out)


@collect_magic_info
def pset(line):
    """
    Set motor position
    """
    if not line:
        print('Syntax: set motor1 position1 [motor2 position2] [...]')
        return

    args = line.split()

    pairlist = []
    try:
        while args:
            mname = args.pop(0)
            x = float(args.pop(0))
            if not mname in motors:
                print(('set: unknown motor "%s"' % mname))
                return
            pairlist.append((motors[mname], x))
    except:
        print('set: Syntax error')
        return

    # Move all motors simultaneously (block=False)
    for motor, x in pairlist:
        motor.set(x)
    if not line:
        print('Syntax: mvr motor1 position1 [motor2 position2] [...]')
        return

    args = line.split()

    pairlist = []
    try:
        while args:
            pairlist.append((args.pop(0), float(args.pop(0))))
    except:
        print('mvr: Syntax error.')
        return


@collect_magic_info
def lm(line):
    """
    Show soft motor limits.
    """
    mnames = line.split()
    if not mnames:
        mlist = motors
    else:
        mlist = {}
        for m in mnames:
            try:
                mlist[m] = motors[m]
            except KeyError:
                print(('Unknown motor: "%s"' % m))
                return

    str_out = '               lower         higher    \n'
    str_out += '---------------------------------------\n'
    for mname, mot in list(mlist.items()):
        lower, upper = mot.lm()
        str_out += '{:^10}  {:^12.4f}  {:^12.4f}  \n'.format(mname, lower, upper)

    print(str_out)


@collect_magic_info
def set_lm(line):
    """
    Set soft motor limits.
    """

    if not line:
        print('Syntax: set_lm motor1 lowerlim1 upperlim1 [motor2 lowerlim2 upperlim2] [...]')
        return

    args = line.split()

    tripletlist = []
    try:
        while args:
            tripletlist.append((args.pop(0), float(args.pop(0)), float(args.pop(0))))
    except:
        print('set_lm: Syntax error.')
        return

    # Set limits
    for motor, lowerlim, upperlim in tripletlist:
        motors[motor].set_lm(lowerlim, upperlim)

@collect_magic_info
def magiclist(line):
    """
    List all labcontrol magics
    """
    for name, f in magic_list.items():
        print(f' * {name}:')
        print(f'{f.__doc__}')




# status -> general summary investigation, experiment, scan number, motor positions, source parameters
# snap

# @register_line_magic
# @collect_magic_info
# def sp(line):
#     """
#     Save current position of the listed motors (see gp to go to these positions)
#     Syntax: sp <number> <component> [<component> ...]
#     """
#
#     if not line:
#         print('Syntax: sp number motor1 [motor2] [...]')
#         return
#
#     args = line.split()
#
#     try:
#         position_number = int(args.pop(0))
#         motor_list = args
#     except:
#         print('sp: Syntax error.')
#         return
#
#     # Save (dial) positions of the given motors
#     positions = {mname : motors[mname]._get_pos() for mname in args}


