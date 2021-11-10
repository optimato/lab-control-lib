################################################################################
# some functions to run the Newport linear stages absolute and relative,
# AFTER initialization and homing was performed via web interface.
# Supports relative and absolute movement
# hard motor limits are at 0 and 25 mm
# Supports user-defined origin/coord. system
# the motors as out of the box do not operate with a backlash movement, this is
# implemented here. Turn on by setting the variable "backlash" to 1
# range of backlash movement is set with "backlash_dist""
# version 0 17.07.2017, Hans
# FUNCTION LIST:
# for all functions wiht "x" this can be replaced by "y" and "z"
# - xps_uorig_x_set(uorigx): sets the user-defined x origin, in mm
# - xps_ulim_get(): Print the user defined limits
# - xps_ulim_x_lo_set(x): Sets the user low limit for motor x, in mm; Hard limits are 0 and 25
# - xps_ulim_x_hi_set(x): see above
# - xps_x_move_abs(x): Move x-motor to absolute position, in mm
# - xps_x_move_rel(deltax): Move x-motor relative, in mm
# - xps_x_move_uabs(x): Move x-motor to absolute position in user-defined coord system, in mm
################################################################################
# TO DO:
# - user defined backlash, what is a good value?
################################################################################
# EPICS uses an abolute reference system
# After homing the low limit is set in EPICS as 0
# high limit is 25!!!!

import epics as ep

# create some variables for setting soft (user) limits
ulim_x_lo = 0
ulim_x_hi = 24.5 # ATTENTION real limit is 25, but need to set lower to account for backlash movement
ulim_y_lo = 0
ulim_y_hi = 24.5
ulim_z_lo = 0
ulim_z_hi = 24.5
# create a variable for origin of user coord system
uorig_x = 0
uorig_y = 0
uorig_z = 0
# set backlash on/off
backlash = 1
backlash_dist = 0.1 # 100 um?

################################################################################
# set user-defined origin x
def xps_uorig_x_set(uorigx):
    '''sets the user-defined x origin, in mm'''
    global uorig_x
    uorig_x = uorigx


################################################################################
# set user-defined origin y
def xps_uorig_y_set(uorigy):
    '''sets the user-defined y origin, in mm'''
    global uorig_y
    uorig_y = uorigyuorig_z


################################################################################
# set user-defined origin z
def xps_uorig_z_set(uorigz):
    '''sets the user-defined z origin, in mm'''
    global uorig_z
    uorig_z = uorigz


################################################################################
# read out limits
def xps_ulim_get():
    '''Print the user defined limits'''
    # get the global vars
    global ulim_x_lo
    global ulim_x_hi
    global ulim_y_lo
    global ulim_y_hi
    global ulim_z_lo
    global ulim_z_hi
    # get user origin
    global uorig_coord
    # print limits
    print('        abs      user ')
    print('x_lo  %02.4f    %02.4f' % (ulim_x_lo,ulim_x_lo-uorig_x))
    print('x_hi  %02.4f    %02.4f' % (ulim_x_hi,ulim_x_hi-uorig_x))
    print('y_lo  %02.4f    %02.4f' % (ulim_y_lo,ulim_y_lo-uorig_y))
    print('y_hi  %02.4f    %02.4f' % (ulim_y_hi,ulim_y_hi-uorig_y))
    print('z_lo  %02.4f    %02.4f' % (ulim_z_lo,ulim_z_lo-uorig_z))
    print('z_hi  %02.4f    %02.4f' % (ulim_z_hi,ulim_z_hi-uorig_z))


################################################################################
# read out current position
def xps_pos_get():
    # print positions
    print('     abs      user      uorig')
    print('x  %02.4f    %02.4f     %02.4f' % (ep.caget('xps-ls:P1'),ep.caget('xps-ls:P1')-uorig_x,uorig_x))
    print('y  %02.4f    %02.4f     %02.4f' % (ep.caget('xps-ls:P2'),ep.caget('xps-ls:P2')-uorig_y,uorig_y))
    print('z  %02.4f    %02.4f     %02.4f' % (ep.caget('xps-ls:P3'),ep.caget('xps-ls:P3')-uorig_z,uorig_z))



################################################################################
# set user low limit x
def xps_ulim_x_lo_set(x):
    '''Sets the user low limit for motor x, in mm
       Hard limits are 0 and 25'''
    global ulim_x_hi # retrieve the user high limit
    global ulim_x_lo # retrieve the user low limit
    # check if user limit is within the hard limit
    if x < 0 or x > 25:
        print('Error: specified limit outside hard limits')
        print('Aborting...')
        return
    # check if user low limit is below user high limit
    if x >= ulim_x_hi:
        print('Error: specified low limit is above user specified high limit')
        print('Aborting...')
        return
    # set the limit
    ulim_x_lo = x


################################################################################
# set user low limit x
def xps_ulim_x_hi_set(x):
    '''Sets the user low limit for motor x, in mm
       Hard limits are 0 and 25'''
    global ulim_x_hi # retrieve the user high limit
    global ulim_x_lo # retrieve the user low limit
    # check if user limit is within the hard limit
    if x < 0 or x > 25:
        print('Error: specified limit outside hard limits')
        print('Aborting...')
        return
    # check if user low limit is below user high limit
    if x <= ulim_x_lo:
        print('Error: specified high limit is above user specified low limit')
        print('Aborting...')
        return
    # set the limit
    ulim_x_hi = x


################################################################################
# move x-motor (1-motor) absolute
def xps_x_move_abs(x):
    '''Move x-motor to absolute position, in mm
       xps_x_move_abs(1)'''
    # get low and high limits
    global ulim_x_hi # retrieve the user high limit
    global ulim_x_lo # retrieve the user low limit
    global backlash # check if backlash is on
    global backlash_dist # distance for backlash movement
    # check if new position is within limits
    if x < ulim_x_lo or x > ulim_x_hi:
        print('Error: position out of limit')
        print('Aborting...')
        return
    # if backlash movement is on make it here
    if backlash:
        # make backlash only when moving positive
        if x > ep.caget('xps-ls:P1'):
            # move to position + backlash distance
            ep.caput('xps-ls:P1',x+backlash_dist)
            # move back
            ep.caput('xps-ls:P1',x)
        else:
            ep.caput('xps-ls:P1',x)




################################################################################
# move x-motor (1-motor) relative
def xps_x_move_rel(deltax):
    '''Move x-motor relative, in mm
       xps_x_move_rel(1)'''
    # get low and high limits
    global ulim_x_hi # retrieve the user high limit
    global ulim_x_lo # retrieve the user low limit
    global backlash # check if backlash is on
    global backlash_dist # distance for backlash movement
    # get current absolute position
    pos_x_curr = ep.caget('xps-ls:P1')
    # new position
    pos_x_new = pos_x_curr + deltax
    # check if out of limits
    if pos_x_new < ulim_x_lo or pos_x_new > ulim_x_hi:
        print('Error: position out of limit')
        print('Aborting...')
        return
    # if backlash movement is on make it here
    if backlash:
        # make backlash only when moving positive
        if pos_x_new > pos_x_curr:
            # move to position + backlash distance
            ep.caput('xps-ls:P1',pos_x_new+backlash_dist)
            # move back
            ep.caput('xps-ls:P1',pos_x_new)
        else:
            ep.caput('xps-ls:P1',pos_x_new)


################################################################################
# move x-motor (1-motor) absolute in user-defined coord system
def xps_x_move_uabs(x):
    '''Move x-motor to absolute position in user-defined coord system, in mm
       xps_x_move_abs(1)'''
    # get low and high limits
    global ulim_x_hi # retrieve the user high limit
    global ulim_x_lo # retrieve the user low limit
    global uorig_x # get user-defined origin
    global backlash # check if backlash is on
    global backlash_dist # distance for backlash movement
    # check if new position is within limits
    if x + uorig_x < ulim_x_lo or x + uorig_x > ulim_x_hi:
        print('Error: position out of limit')
        print('Aborting...')
        return
    # if not put position
    # if backlash movement is on make it here
    pos_x_new = x + uorig_x
    pos_x_curr = ep.caget('xps-ls:P1')
    if backlash:
        # make backlash only when moving positive
        if pos_x_new > pos_x_curr:
            # move to position + backlash distance
            ep.caput('xps-ls:P1',pos_x_new+backlash_dist)
            # move back
            ep.caput('xps-ls:P1',pos_x_new)
        else:
            ep.caput('xps-ls:P1',pos_x_new)



################################################################################
# set user low limit y
def xps_ulim_y_lo_set(y):
    '''Sets the user low limit for motor y, in mm
       Hard limits are 0 and 25'''
    global ulim_y_hi # retrieve the user high limit
    global ulim_y_lo # retrieve the user low limit
    # check if user limit is within the hard limit
    if y < 0 or y > 25:
        print('Error: specified limit outside hard limits')
        print('Aborting...')
        return
    # check if user low limit is below user high limit
    if y >= ulim_y_hi:
        print('Error: specified low limit is above user specified high limit')
        print('Aborting...')
        return
    # set the limit
    ulim_y_lo = y


################################################################################
# set user low limit y
def xps_ulim_y_hi_set(y):
    '''Sets the user low limit for motor y, in mm
       Hard limits are 0 and 25'''
    global ulim_y_hi # retrieve the user high limit
    global ulim_y_lo # retrieve the user low limit
    # check if user limit is within the hard limit
    if y < 0 or y > 25:
        print('Error: specified limit outside hard limits')
        print('Aborting...')
        return
    # check if user low limit is below user high limit
    if y <= ulim_y_lo:
        print('Error: specified high limit is above user specified low limit')
        print('Aborting...')
        return
    # set the limit
    ulim_y_hi = y


################################################################################
# move y-motor (2-motor) absolute
def xps_y_move_abs(y):
    '''Move y-motor to absolute position, in mm
       xps_y_move_abs(1)'''
    # get low and high limits
    global ulim_y_hi # retrieve the user high limit
    global ulim_y_lo # retrieve the user low limit
    global backlash # check if backlash is on
    global backlash_dist # distance for backlash movemen
    # check if new position is within limits
    if pos_y_new < ulim_y_lo or pos_y_new > ulim_y_hi:
        print('Error: position out of limit')
        print('Aborting...')
        return
    # if not put position
    # if backlash movement is on make it here
    if backlash:
        # make backlash only when moving positive
        if y > ep.caget('xps-ls:P2'):
            # move to position + backlash distance
            ep.caput('xps-ls:P2',y+backlash_dist)
            # move back
            ep.caput('xps-ls:P2',y)
        else:
            ep.caput('xps-ls:P2',y)


################################################################################
# move x-motor (2-motor) relative
def xps_y_move_rel(deltay):
    '''Move y-motor relative, in mm
       xps_y_move_rel(1)'''
    # get low and high limits
    global ulim_y_hi # retrieve the user high limit
    global ulim_y_lo # retrieve the user low limit
    global backlash # check if backlash is on
    global backlash_dist # distance for backlash movement
    # get current absolute position
    pos_y_curr = ep.caget('xps-ls:P2')
    # new position
    pos_y_new = pos_y_curr + deltay
    # check if out of limits
    if pos_y_new < ulim_y_lo or pos_y_new > ulim_y_hi:
        print('Error: position out of limit')
        print('Aborting...')
        return
    # if backlash movement is on make it here
    if backlash:
        # make backlash only when moving positive
        if pos_y_new > pos_y_curr:
            # move to position + backlash distance
            ep.caput('xps-ls:P2',pos_y_new+backlash_dist)
            # move back
            ep.caput('xps-ls:P2',pos_y_new)
        else:
            ep.caput('xps-ls:P2',pos_y_new)


################################################################################
# move x-motor (1-motor) absolute in user-defined coord system
def xps_y_move_uabs(y):
    '''Move y-motor to absolute position in user-defined coord system, in mm
       xps_y_move_abs(1)'''
    # get low and high limits
    global ulim_y_hi # retrieve the user high limit
    global ulim_y_lo # retrieve the user low limit
    global uorig_y # get user-defined origin
    global backlash # check if backlash is on
    global backlash_dist # distance for backlash movement
    # check if new position is within limits
    if y + uorig_y < ulim_y_lo or y + uorig_y > ulim_y_hi:
        print('Error: position out of limit')
        print('Aborting...')
        return
    # if not put position
    # if backlash movement is on make it here
    pos_y_new = y + uorig_y
    pos_y_curr = ep.caget('xps-ls:P2')
    if backlash:
        # make backlash only when moving positive
        if pos_y_new > pos_y_curr:
            # move to position + backlash distance
            ep.caput('xps-ls:P2',pos_y_new+backlash_dist)
            # move back
            ep.caput('xps-ls:P2',pos_y_new)
        else:
            ep.caput('xps-ls:P2',pos_y_new)


################################################################################
# set user low limit z
def xps_ulim_z_lo_set(z):
    '''Sets the user low limit for motor z, in mm
       Hard limits are 0 and 25'''
    global ulim_z_hi # retrieve the user high limit
    global ulim_z_lo # retrieve the user low limit
    # check if user limit is within the hard limit
    if z < 0 or z > 25:
        print('Error: specified limit outside hard limits')
        print('Aborting...')
        return
    # check if user low limit is below user high limit
    if z >= ulim_z_hi:
        print('Error: specified low limit is above user specified high limit')
        print('Aborting...')
        return
    # set the limit
    ulim_z_lo = z


################################################################################
# set user low limit z
def xps_ulim_z_hi_set(z):
    '''Sets the user low limit for motor z, in mm
       Hard limits are 0 and 25'''
    global ulim_z_hi # retrieve the user high limit
    global ulim_z_lo # retrieve the user low limit
    # check if user limit is within the hard limit
    if z < 0 or z > 25:
        print('Error: specified limit outside hard limits')
        print('Aborting...')
        return
    # check if user low limit is below user high limit
    if z <= ulim_z_lo:
        print('Error: specified high limit is above user specified low limit')
        print('Aborting...')
        return
    # set the limit
    ulim_z_hi = z


################################################################################
# move z-motor (1-motor) absolute
def xps_z_move_abs(z):
    '''Move z-motor to absolute position, in mm
       xps_z_move_abs(1)'''
    # get low and high limits
    global ulim_z_hi # retrieve the user high limit
    global ulim_z_lo # retrieve the user low limit
    global backlash # check if backlash is on
    global backlash_dist # distance for backlash movemen
    # check if new position is within limits
    if pos_z_new < ulim_z_lo or pos_z_new > ulim_z_hi:
        print('Error: position out of limit')
        print('Aborting...')
        return
    # if not put position
    # if not put position
    # if backlash movement is on make it here
    if backlash:
        # make backlash only when moving positive
        if z > ep.caget('xps-ls:P3'):
            # move to position + backlash distance
            ep.caput('xps-ls:P3',z+backlash_dist)
            # move back
            ep.caput('xps-ls:P3',z)
        else:
            ep.caput('xps-ls:P3',z)


################################################################################
# move z-motor (1-motor) relative
def xps_z_move_rel(deltaz):
    '''Move z-motor relative, in mm
       xps_z_move_rel(1)'''
    # get low and high limits
    global ulim_z_hi # retrieve the user high limit
    global ulim_z_lo # retrieve the user low limit
    global backlash # check if backlash is on
    global backlash_dist # distance for backlash movemen
    # get current absolute position
    pos_z_curr = ep.caget('xps-ls:P3')
    # new position
    pos_z_new = pos_z_curr + deltaz
    # check if out of limits
    if pos_z_new < ulim_z_lo or pos_z_new > ulim_z_hi:
        print('Error: position out of limit')
        print('Aborting...')
        return
    # if backlash movement is on make it here
    if backlash:
        # make backlash only when moving positive
        if pos_z_new > pos_z_curr:
            # move to position + backlash distance
            ep.caput('xps-ls:P3',pos_z_new+backlash_dist)
            # move back
            ep.caput('xps-ls:P3',pos_z_new)
        else:
            ep.caput('xps-ls:P3',pos_z_new)


################################################################################
# move z-motor (3-motor) absolute in user-defined coord system
def xps_z_move_uabs(z):
    '''Move z-motor to absolute position in user-defined coord system, in mm
       xps_z_move_abs(1)'''
    # get low and high limits
    global ulim_z_hi # retrieve the user high limit
    global ulim_z_lo # retrieve the user low limit
    global uorig_z # get user-defined origin
    global backlash # check if backlash is on
    global backlash_dist # distance for backlash movemen
    # check if new position is within limits
    if z + uorig_z < ulim_z_lo or z + uorig_z > ulim_z_hi:
        print('Error: position out of limit')
        print('Aborting...')
        return
    # if not put position
    # if backlash movement is on make it here
    pos_z_new = y + uorig_z
    pos_z_curr = ep.caget('xps-ls:P3')
    if backlash:
        # make backlash only when moving positive
        if pos_z_new > pos_z_curr:
            # move to position + backlash distance
            ep.caput('xps-ls:P3',pos_z_new+backlash_dist)
            # move back
            ep.caput('xps-ls:P3',pos_z_new)
        else:
            ep.caput('xps-ls:P3',pos_z_new)
