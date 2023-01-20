"""
Custom Magic commands for experimental setup

CURRENT FUNCTIONS---------------------------------------------------------------
%init -- run init all
%stat -- get status of compontent w/ syntax %stat <component>
%magiclist -- display list of components and commands
%mva -- move component by absolute value w/ syntax %amv <component> <parameter>
%mvr -- move component by relative value w/ syntax %rmv <component> <parameter>


FUNCTIONS STILL TO IMPLEMENT---------------------------------------------------
maybe init + component to just initilize one component
snap
flat
tilt
focus series
setting soft limits(?)
query soft limits(?)
smaract speeds set/get

COMPONENTS STILL TO IMPLEMENT--------------------------------------------------
piezo

OTHER TO DO
think about more inputs
actually implement
"""

from . import smaract
from . import mclennan
from . import aerotech
from . import labframe
from . import motors, drivers
from IPython.core.magic import register_line_magic


magic_list = {}


def collect_magic_info(f):
    magic_list[f.__name__] = f.__doc__
    return f


@register_line_magic
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


@register_line_magic
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


@register_line_magic
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


@register_line_magic
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


@register_line_magic
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


@register_line_magic
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


@register_line_magic
@collect_magic_info
def init(line):
    """
    Initlize components
    """
    dict_init={}
    mnames = line.split()
    for mname in mnames:
        if mname == 'sx':
            if 'smaract' not in drivers: drivers['smaract'] = smaract.Smaract()
            if 'sx' not in motors: motors['sx'] = smaract.Motor('sx', drivers['smaract'], axis=0)

        elif mname == 'sy':
            if 'smaract' not in drivers: drivers['smaract'] = smaract.Smaract()
            if 'sy' not in motors: motors['sy'] = smaract.Motor('sy', drivers['smaract'], axis=1)

        elif mname == 'sz':
            if 'smaract' not in drivers: drivers['smaract'] = smaract.Smaract()
            if 'sz' not in motors: motors['sz'] = smaract.Motor('sz', drivers['smaract'], axis=2)

        elif mname == 'rot':
            if 'rot' not in drivers: drivers['rot'] = aerotech.AeroTech()
            if 'rot' not in motors: motors['rot'] = aerotech.Motor('rot', drivers['rot'])

        elif mname == 'ssx':
            if 'ssx' not in drivers: drivers['ssx'] = mclennan.McLennan(host='192.168.0.60')
            if 'ssx' not in motors: motors['ssx'] = mclennan.Motor('ssx', drivers['ssx'])

        elif mname == 'dsx':
            if 'dsx' not in dsx: drivers['dsx'] = mclennan.McLennan(host='192.168.0.70')
            if 'dsx' not in dsx: motors['dsx'] = mclennan.Motor('dsx', drivers['dsx'])

        elif mname == 'sxl':
            if 'sxl' not in sxl: motors['sxl'] = labframe.Motor('sxl', motors['sx'], motors['sy'], motors['rot'], axis=0)


        elif mname == 'syl':
            if 'syl' not in syl: motors['syl'] = labframe.Motor('syl', motors['sx'], motors['sy'], motors['rot'], axis=1)

        else:
            print((mname, "cannot currently be initlized using spec_magics"))


    return


@register_line_magic
@collect_magic_info
def magiclist(line):
    """
    List all labcontrol magics
    """
    for name, doc in magic_list.items():
        print(f' * {name}:')
        print(f'{doc}')


# @register_line_magic
# def stat(line):
#     """Querey Status of component. Syntax: amv <component>"""
#     print("Running status")
#     line = shlex.split(line)  #Breaks input line into list of the individual words
#
#     if len(line) != 1: #Check input correct length
#         print("error: incorrect input")
#         print("Syntax: stat <component>")
#         return
#
#     if line[0] in dict_rmv: #if component exists in dictionary
#         dict_rmv[line[0]]() #run move relative function
#         return
#     else:
#         print("Unknown component", line[0] ,"for list of components type %magiclist" )
#         return
#
# @register_line_magic
# def init(line):
#     """Command that runs init_all in user_defined_functions..."""
#     print("Initilizing all things")
#
# @register_line_magic
# def magiclist(line):
#     line = shlex.split(line)
#     print("List of magic commands")
#     print("-----------------------------------------")
#     print("COMMAND LIST")
#     print("%init -- init all")
#     print("%amv -- move component to absolute value w/ syntax: %amv <component> <parameter>")
#     print("%rmv -- move component by a relative value w/ syntax: %rmv <component> <parameter>")
#     print("%stat -- find status of component w/ syntax: %stat <component>")
#     print("-----------------------------------------")
#     print("COMPONENT LIST")
#     print("th -- rotation stage")
#     print("sb -- sample bay")
#     print("mb -- microscope bay")
#     print("sc -- scintillator wheel")
#     print("pz -- piezo")
#     print("-----------------------------------------")
#     return
#
# del hello
# del magiclist
# del mva
# del rmv
# del stat
# del init


