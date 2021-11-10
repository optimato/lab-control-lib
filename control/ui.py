"""
User interface (CLI)
"""


import os
from matplotlib import pyplot as plt
import h5py
import numpy as np
import PIL
import time
import scipy.optimize
from scipy.signal import medfilt
import sys
import threading
import inspect
import datetime
import math
import random
import logging
import base64
import StringIO

from ..analysis import stitching, rebin
from . import mtffun_hans
from . import smaract
from . import mclennan
from . import aerotech
from . import labframe
from . import xpsfun_ronan
from . import microscope
from . import pco
from . import excillum
from . import spec_magics
from .. import io

from . import drivers, motors, config, conf_path
from .ui_utils import ask, ask_yes_no
from . import ui_utils

from glob import glob

# Re-enable this once code has been cleaned up
"""
UPDATE_ON = False  # set this flag to take a snap view after every command
OUTDIST = 0  # distance in mm to move OUTMOTOR for flatfields
OUTMOTOR = 'sx'  # motor to use to move sample out of beam
"""

# Container for scan context
SCAN_INFO = {'scan': None}

# Container for stored frames
FRAMES = {'flat': None, 'dark': None, 'snap': None, 'fsnap': None}

logger = logging.getLogger(__name__)

#Container for metadata taking
source_info = {}
motor_info = {}

def init_all(yes=None):
    """
    Initialize components of the setup.
    Syntax:
        init_all()
    is interactive
    """
    if yes:
        # Fake non-interactive to answer all questions automatically
        ui_utils.user_interactive = False

    if ask_yes_no('Initialise smaracts?', help="SmarAct are the 3-axis piezo translation stages for sample movement"):
        drivers['smaract'] = smaract.Smaract()
        motors['sx'] = smaract.Motor('sx', drivers['smaract'], axis=0)
        motors['sz'] = smaract.Motor('sz', drivers['smaract'], axis=1) #used to be sy in old coordinates - changed 8/1/19
        motors['sy'] = smaract.Motor('sy', drivers['smaract'], axis=2) #used to be sz

    if ask_yes_no('Initialise PCO camera?'):
        drivers['pco'] = pco.PCO()

    if ask_yes_no('Initialise microscope?'):
        drivers['microscope'] = microscope.Microscope()

    if ask_yes_no('Initialise bottom stages?'):
        # Instantiate drivers
        drivers['ssx'] = mclennan.McLennan(host='192.168.0.60', name='ssx')
        drivers['dsx'] = mclennan.McLennan(host='192.168.0.70', name='dsx')
        # Instantiate motors
        motors['ssx'] = mclennan.Motor('ssx', drivers['ssx'])
        motors['dsx'] = mclennan.Motor('dsx', drivers['dsx'])

    if ask_yes_no('Initialise rotate stage?'):
        drivers['rot'] = aerotech.AeroTech()
        motors['rot'] = aerotech.Motor('rot', drivers['rot'])

    if ask_yes_no('Initialise Newport XPS motors?'):
        drivers['XPS'] = xpsfun_ronan.XPS()
        motors['xpsx'] = xpsfun_ronan.Motor('X', drivers['XPS'], 'X')
        #motors['xpsy'] = xpsfun_ronan.Motor('Y', drivers['XPS'], 'Y')
        #motors['xpsz'] = xpsfun_ronan.Motor('Z', drivers['XPS'], 'Z')

    if ask_yes_no('Initialise stage pseudomotors?'):
        motors['sxl'] = labframe.Motor('sxl', motors['sx'], motors['sz'], motors['rot'], axis=0)
        motors['szl'] = labframe.Motor('szl', motors['sx'], motors['sz'], motors['rot'], axis=1)

    if ask_yes_no('Connect to LMJ?'):
        drivers['lmj'] = excillum.LMJ()

    if ask_yes_no('Dump all motor objects in global namespace?'):
        # This is a bit of black magic
        for s in inspect.stack():
            if 'init_all' in s[4][0]:
                s[0].f_globals.update(motors)
                break

    if ask_yes_no('Create a new experiment subfolder?', yes_is_default=False):
        new_experiment()
    print(('Experiment name: %s' % config['experiment_name']))
    print(('Experiment base path: %s' % config['experiment_path']))
    print(('Experiment scan number: %06d' % config['experiment_scan_number']))

    if yes:
        # Fake non-interactive to answer all questions automatically
        ui_utils.user_interactive = None


    try:
        FRAMES['flat'] = io.h5read(str(os.path.join(conf_path, config['flats_file'])))['flats']
        print('Loaded %d flats from file.' % len(FRAMES['flat']))
    except IOError:
        print('Error: could not load flats')
    try:
        FRAMES['dark'] = io.h5read(str(os.path.join(conf_path, config['darks_file'])))['darks']
        print('Loaded %d darks from file.' % len(FRAMES['dark']))
    except:
        print('Error: could not load darks')


def _exp_time_as_key(e):
    """
    Helper function to convert exposure time to key.
    """
    return '%dms' % int(1000 * e)


def snap(exp_time=None, vmin=None, vmax=None, save_name='snap', figno=100):
    """
    Take (and display) one frame
    Syntax:
       snap(exp_time=1, vmin=0, vmax=200, save_name='snap', figno=100)
    Used for taking a single image for testing
    capture() should be used for data acquisition

    save_name: str, the prefix for for saving filename.
    figno: matplotlib figure number. If None, do not show
    """
    # Use default exposure time if none is provided
    if exp_time is None:
        exp_time = drivers['pco'].settings()['exp_time']

    num_exposures = int(np.ceil(exp_time/10.))
    exp_time /= num_exposures

    drivers['pco'].settings(exp_time=exp_time,
                            drive='camserver',
                            prefix=save_name,
                            path='',
                            num_exposures=num_exposures,
                            increment=False,
                            file_number=0)
    filename = drivers['pco'].capture()

    with h5py.File(filename, 'r') as fid_snap:
        this_snap = np.squeeze(fid_snap['/entry/data'])
        this_snap = np.asarray(this_snap, dtype=float)
        FRAMES['snap'] = this_snap

    fig = _show(this_snap, title='Snap', vmin=vmin, vmax=vmax, figno=figno)

    # MQTT stuff
    s = StringIO.StringIO()
    if fig:
        fig.savefig(s, format='png', dpi='figure')
        drivers['pco'].mqtt_pub({'xnig/drivers/pco/last_snap': base64.b64encode(s.getvalue())})

    return this_snap


def fsnap(exp_time=None, vmin=None, vmax=None, figno=100):
    """
    Take (and display) one frame, including dark and flat correction.
    Syntax:
       fsnap(exp_time=1, vmin=0, vmax=1)
    Used for taking a single image for testing
    capture() should be used for data acquisition
    """
    if exp_time is None:
        exp_time_ms = _exp_time_as_key(drivers['pco'].exp_time)
    else:
        exp_time_ms = _exp_time_as_key(exp_time)

    if FRAMES['dark'] is None or not exp_time_ms in FRAMES['dark']:
        raise RuntimeError('Please take darks first')
    if FRAMES['flat'] is None or not exp_time_ms in FRAMES['flat']:
        raise RuntimeError('Please take flats first')

    dark = FRAMES['dark'][exp_time_ms]
    flat = FRAMES['flat'][exp_time_ms]
    this_snap = snap(exp_time=exp_time, figno=None)
    corrected_snap = (this_snap - dark)/(flat - dark)
    FRAMES['fsnap'] = corrected_snap

    # Show
    if vmin is None: vmin = 0
    if vmax is None: vmax = 1.
    fig = _show(corrected_snap, title='Flat corrected snap', vmin=vmin, vmax=vmax, figno=figno)

    # MQTT stuff
    s = StringIO.StringIO()
    if fig:
        fig.savefig(s, format='png', dpi='figure')
        drivers['pco'].mqtt_pub({'xnig/drivers/pco/last_fsnap': base64.b64encode(s.getvalue())})

    return np.squeeze(corrected_snap)


def _show(data, title, origin=None, vmin=None, vmax=None, figno=None, cmap='bone'):
    """
    Plot a frame. If figno is None, do not plot.

    :param data: The image to plot
    :param title: The title of the image
    :param origin: The physical position of the (0,0) coordinate NOT IMPLEMENTED
    :param vmin, vmax: lower, upper limits of color scale
    :param figno: Figure number
    """
    if figno is None:
        return None

    # fig, ax = plt.subplots(num=figno, subplot_kw={'aspect': 'equal', 'adjustable': 'box'})
    fig, ax = plt.subplots(num=figno)
    fig.clf()
    plt.set_cmap(cmap)
    if vmin is None: vmin = np.percentile(data,  0.01)
    if vmax is None: vmax = np.percentile(data, 99.99)
    plt.imshow(data, vmin=vmin, vmax=vmax, interpolation='nearest', origin='lower')
    plt.colorbar()
    plt.title(title)
    """
    if origin is not None:
        ax1 = ax.twinx()
        ax1.set_ylim(origin[1], origin[1]+data.shape[1]*config['pixel_size'])
        ax1.set_ylabel('Position ($\mu m$)')
        ax2 = ax.twiny()
        ax2.set_xlim(origin[0], origin[0] + data.shape[0] * config['pixel_size'])
        ax2.set_xlabel('Position ($\mu m$)')
    """
    plt.draw()
    plt.show(block=False)
    return fig


def sequence(N=11, exp_time=None, prefix='seq'):
    """
    Take a sequence of frames (outside of scan context)
    N: number of repeats
    """
    # Use default exposure time if none is provided
    if exp_time is None:
        exp_time = drivers['pco'].settings()['exp_time']

    num_exposures = int(np.ceil(exp_time/10.))
    exp_time /= num_exposures

    drivers['pco'].settings(exp_time=exp_time,
                            drive='camserver',
                            prefix=prefix,
                            path='',
                            num_exposures=num_exposures,
                            increment=True,
                            file_number=0)
    filenames = []
    print('Taking %d frames of type %s.' % (N, prefix))
    for k in range(N):
        filenames.append(drivers['pco'].capture())
        print('%d/%d' % (k+1, N))

    frames = []
    for filename in filenames:
        with h5py.File(filename, 'r') as f:
            frames.append(np.squeeze(f['/entry/data']).astype(float))

    return frames


def darks(N=11, exp_time=None):
    """
    Take and store dark frames.
    N: number of repeats
    """
    darks = sequence(N=N, exp_time=exp_time, prefix='dark')
    dark = np.mean(darks, axis=0)

    if exp_time is None:
        exp_time = drivers['pco'].exp_time
    exp_time_ms = _exp_time_as_key(exp_time)

    if FRAMES['dark'] is None:
        FRAMES['dark'] = {}

    FRAMES['dark'][exp_time_ms] = dark

    io.h5write(os.path.join(conf_path, config['darks_file']), darks=FRAMES['dark'])

    return dark


def flats(N=11, exp_time=None):
    """
    Take and store flat frames.
    N: number of repeats
    """
    flats = sequence(N=N, exp_time=exp_time, prefix='flat')
    flat = np.mean(flats, axis=0)

    if exp_time is None:
        exp_time = drivers['pco'].exp_time
    exp_time_ms = _exp_time_as_key(exp_time)

    if FRAMES['flat'] is None:
        FRAMES['flat'] = {}

    FRAMES['flat'][exp_time_ms] = flat

    io.h5write(os.path.join(conf_path, config['flats_file']), flats=FRAMES['flat'])

    return flat

def _acquire_metadata():
    '''
    A function for saving the source and positioner information to dictionaries, so it can be saved at the correct time.
    '''

    #saving source info

    try:
        source_info[u'power_W'] = drivers['lmj'].generator_emission_power_w
    except:
        source_info[u'power_W'] = 'Error Getting Value'

    try:
        source_info[u'voltage_V'] = drivers['lmj'].generator_high_voltage
    except:
        source_info[u'voltage_V'] = 'Error Getting Value'

    try:
        source_info[u'current_A'] = drivers['lmj'].generator_emission_current_a
    except:
        source_info[u'current_A'] = 'Error Getting Value'

    try:
        source_info[u'spot_size_x_um'] = drivers['lmj'].spotsize_x_um
    except:
        source_info[u'spot_size_x_um'] = 'Error Getting Value'

    try:
        source_info[u'spot_size_y_um'] = drivers['lmj'].spotsize_y_um
    except:
        source_info[u'spot_size_y_um'] = 'Error Getting Value'

    try:
        source_info[u'spot_position_x_um'] = drivers['lmj'].spot_position_x_um
    except:
        source_info[u'spot_position_x_um'] = 'Error Getting Value'

    try:
        source_info[u'spot_position_y_um'] = drivers['lmj'].spot_position_y_um
    except:
        source_info[u'spot_position_y_um'] = 'Error Getting Value'

    try:
        source_info[u'jet_pressure_pa'] = drivers['lmj'].jet_pressure_pa
    except:
        source_info[u'jet_pressure_pa'] = 'Error Getting Value'

    # motor info

    try:
        motor_info[u'rotation_angle'] = motors['rot'].pos
    except:
        motor_info[u'rotation_angle'] = 'Error Getting Value'

    try:
        motor_info[u'sample_x_absolute'] = motors['sx'].pos
    except:
        motor_info[u'sample_x_absolute'] = 'Error Getting Value'

    try:
        motor_info[u'sample_y_absolute'] = motors['sy'].pos
    except:
        motor_info[u'sample_y_absolute'] = 'Error Getting Value'

    try:
        motor_info[u'sample_z_absolute'] = motors['sz'].pos
    except:
        motor_info[u'sample_z_absolute'] = 'Error Getting Value'

    try:
        motor_info[u'sample_x_labframe'] = motors['sxl'].pos
    except:
        motor_info[u'sample_x_labframe'] = 'Error Getting Value'

    try:
        motor_info[u'sample_z_labframe'] = motors['szl'].pos
    except:
        motor_info[u'sample_z_labframe'] = 'Error Getting Value'

    try:
        motor_info[u'coarse_x_sample'] = motors['ssx'].pos
    except:
        motor_info[u'coarse_x_sample'] = 'Error Getting Value'

    try:
        motor_info[u'coarse_x_microscope'] = motors['dsx'].pos
    except:
        motor_info[u'coarse_x_microscope'] = 'Error Getting Value'

    try:
        motor_info[u'diffuser_x'] = motors['xpsx'].pos
    except:
        motor_info[u'diffuser_x'] = 'Error Getting Value'

    try:
        motor_info[u'diffuser_y'] = motors['xpsy'].pos
    except:
        motor_info[u'diffuser_y'] = 'Error Getting Value'

    return source_info, motor_info


def _add_metadata(filename, exp_time):
    """
    Adds metadata to hdf5 file
    :param filename: complete path of the file to access and edit.
    """
    timeout = 15.
    t0 = time.time()
    while True:
        try:
            f = h5py.File(filename, 'r+')
            break
        except IOError:
            if time.time() - t0 > timeout:
                raise
            time.sleep(.5)
            continue

    f.attrs[u'save_version'] = u'1'

    # ALL STRINGS IN UNICODE

    # Creating the 'entry' group (for multiple experiments have 'entry1' etc)
    nxentry = f['entry']
    nxentry.attrs['NX_class'] = 'NXentry'

    # getting time from re-writing time from where the PCO saved it into a user readable format. The PCO seems to
    # save the time based on a 1990 epoch so is 20 years out, so a correction is needed
    nxentry.attrs['end_time'] = str(time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(np.array(f['entry/NDAttributes/timestamp'])[0][2]+631152000)))

    # DATA storage subgroup#######################################
    # Very messy code that involves creating hard links and deleting the old ones to move things into the NEXUS format

    nxentry['data2']=nxentry['data']
    del nxentry['data']
    nxdata = nxentry.create_group('data')
    nxdata['image'] = nxentry['data2']
    del nxentry['data2']
    nxdata.attrs['NX_class'] = 'NXdata'
    nxdata.attrs['signal'] = 'image'  # need this bit to point the reader at the correct data to plot

    # INSTRUMENT information subgroup#############################
    nxinstrument = nxentry.create_group('instrument')
    nxinstrument.attrs['NX_class'] = 'NXinstrument'
    nxinstrument.attrs['name'] = 'X-ray McX-rayFace'


    # source sub-subgroup inside instrument
    nxins_source = nxinstrument.create_group('source')
    nxins_source.attrs['NX_class'] = 'NXsource'

    nxins_source.attrs['name'] = 'Excillum Metaljet-D2'
    nxins_source.attrs['type'] = 'Liquid Metal Jet X-ray'  # Not a NEXUS standard source type, they only have rotating anode and fixed tube
    nxins_source.attrs['probe'] = 'x-ray'

    for a in source_info:
        nxins_source.attrs[a] = source_info[a]

    # detector sub-subgroup
    nxins_detector = nxinstrument.create_group('detector')
    nxins_detector.attrs['NX_class'] = 'NXinstrument'
    nxins_detector.attrs['description'] = 'PCO edge'
    nxins_detector.attrs['exposure_time'] = exp_time

    try:
        nxins_detector.attrs['chip_temperature(c)'] = nxentry['NDAttributes/Temperature'] #not an official NEXUS entry
    except:
        nxins_detector.attrs['chip_temperature(c)'] = 'Error Getting Value'

    try:
        nxins_detector.attrs['lens_magnification'] = config['lens']
    except:
        nxins_detector.attrs['lens_magnification'] = 'Error Getting Value'

    try:
        nxins_detector.attrs['pixel_size'] = config['pixel_size']
    except:
        nxins_detector.attrs['pixel_size'] = 'Error Getting Value'

    try:
        nxins_detector.attrs['Scintillator'] = config['scintillator']
    except:
        nxins_detector.attrs['Scintillator'] = 'Error Getting Value'

    try:
        nxins_detector.attrs['lens_focus_position_mm'] = drivers['microscope'].get_pos_focus()
    except:
        nxins_detector.attrs['lens_focus_position_mm'] = 'Error Getting Value'

        # positioner sub group
    # none of this complies with the NEXUS standard


    nxpos = nxinstrument.create_group('positioner')
    nxpos.attrs['NXclass'] = 'positioner'

    for a in motor_info:
        nxpos.attrs[a] = motor_info[a]

    try:
        nxpos.attrs['source_sample_stage_distance(mm)'] = config['source_to_rotation_stage_distance(mm)']
    except:
        print('failed to read config dictionary')
        nxpos.attrs['source_sample_stage_distance(mm)'] = 'Error Getting Value'

    try:
        nxpos.attrs['sample_stage_detector_distance(mm)'] = config['rotation_stage_to_detector_distance(mm)']
    except:
        print('failed to read config dictionary')
        nxpos.attrs['sample_stage_detector_distance(mm)'] = 'Error Getting Value'



    # SAMPLE information subgroup################################
    # this needs to be populated by the user - could add as an option on startup?
    nxsample = nxentry.create_group('sample')
    nxsample.attrs['NXclass'] = 'NXsample'
    try:
        nxsample.attrs['Sample'] = config['sample']
    except:
        nxsample.attrs['Sample'] = 'Error Getting Value'

    # closing file
    f.close()


class Scan(object):
    """Scan context manager"""

    def __init__(self, exp_time=None):
        self.exp_time = exp_time

    def __enter__(self):
        """
        Prepare for scan
        """

        pcodrv = drivers['pco']

        # Update scan info (this really flags the scan context)
        self.scan_number = config['experiment_scan_number']
        SCAN_INFO['scan'] = self

        if self.exp_time is None:
            self.exp_time = pcodrv.conf['exp_time']

        # Deal with exposures longer than 10 s.
        num_exposures = int(np.ceil(self.exp_time / 10.))
        exp_time = self.exp_time/num_exposures

        # Edit pco settings.
        pcodrv.settings(exp_time=exp_time,
                     drive=config['experiment_drive'],
                     path=os.path.join(config['experiment_path'], '%06d' % self.scan_number),
                     prefix='frame',
                     file_number=0,
                     increment=True,
                     frame_count=1,
                     num_exposures=num_exposures)

        # Arm the camera
        pcodrv.arm()
        logger.info('Starting scan %06d.' % self.scan_number)

        # Store file path
        config['experiment_last_scan_path'] = os.path.join(pco.local_drives[config['experiment_drive']], config['experiment_path'], '%06d' % self.scan_number)

    def __exit__(self, exception_type, exception_value, traceback):
        """
        Exit scan context
        """
        drivers['pco'].disarm()
        SCAN_INFO['scan'] = None
        config['experiment_scan_number'] = self.scan_number + 1
        for trynumber in range(10):
            if config['experiment_scan_number'] == self.scan_number + 1:
                break
            logger.error('Experiment scan number did not increment!')
            config['experiment_scan_number'] = self.scan_number + 1
            time.sleep(1)

        logger.info('Scan %06d complete.' % self.scan_number)


def capture():
    """
    Capture a frame during a Scan

    Example:
    with xc.Scan(exp_time=2.):
        for i in range(10):
            [ move motors ]
            xc.capture()
    """
    if SCAN_INFO['scan'] is None:
        raise RuntimeError("'capture' must be executed in a Scan context.")

    # get the metadata on positioners at the start of acquisition so they are correct
    thread1 = threading.Thread(target = _acquire_metadata)
    thread1.start()

    # Grab frame
    file_path = drivers['pco'].capture()

    # ensuring metadata has been acquired before writing it
    thread1.join()

    # now writing metadata to file
    threading.Thread(target=_add_metadata, args=(file_path, SCAN_INFO['scan'].exp_time)).start()

    return file_path


def moving_image_stack(n_moves=5, total_movement=[0.2, 0.2], exp_time=10, vmax=1000, show_result=False, mode='sample'):
    ''' moves randomly n_moves times within an area of size total_movement about it current position, returing the images
    and the movements made'''

    #if type(save_folder)!= str:
    #    print("Save folder must be string. Use '' for no save folder")

    d_h = total_movement[0]  # total horizontal moveable distance
    d_v = total_movement[1]  # total vertical moveable distance
    loc = np.zeros(2)
    move_array = []
    for i in range(n_moves - 1):
        mov = np.array([random.uniform(-d_h / 2 - loc[0], d_h / 2 - loc[0]), random.uniform(-d_v / 2 - loc[1], d_v / 2 - loc[1])])
        print(loc)
        print(type(loc))
        print(mov)
        print(type(mov))
        loc = np.add(loc, mov, casting = "unsafe")
        move_array.append(mov)
        print(loc)
    move_array.append(-loc)
    move_array = np.array(move_array)

    with Scan(exp_time=exp_time):
        for i in range(np.shape(move_array)[0]):
            print('Taking frame %d of %d' % (i+1, n_moves))
            capture()
            if mode == 'sample':
                motors['sxl'].mvr(move_array[i, 0])
                motors['sy'].mvr(move_array[i, 1])

            elif mode == 'diffuser':
                motors['xpsx'].mvr(move_array[i, 0])
                motors['xpsy'].mvr(move_array[i, 1])

    # Return the location of files
    return config['experiment_last_scan_path']


def move_and_combine(exp_time=None, flat=None, dark=None, n_moves=5, total_movement=[0.2, 0.2], mode='sample',
                     max_iter=5, remove_hits = False):

    if exp_time is None:
        exp_time = drivers['pco'].exp_time

    scan_path = moving_image_stack(n_moves=n_moves, total_movement=total_movement, exp_time=exp_time, mode=mode)

    if flat is None:
        flat = FRAMES['flat'].get(_exp_time_as_key(exp_time), None)

    if dark is None:
        dark = FRAMES['dark'].get(_exp_time_as_key(exp_time), None)

    files_to_stitch = sorted(glob(os.path.join(scan_path, '*.h5')))

    img = stitching.stack_files(files_to_stitch=files_to_stitch,
                                save_folder=scan_path,
                                flat_location=flat,
                                dark_location=dark,
                                mode=mode,
                                psize=config['pixel_size'],
                                max_iter=max_iter,
                                remove_hits=remove_hits)
    return img


def _copy_to_backup(file_path, copy_folder):
    """Copies the image located at :file_path onto the fileserver in folder :copy_folder, preserving
    the folder structure
    Ensure copy_folder ends with a /"""
    split = file_path.split('/')
    semi_path = '/'.join(split[2:-1])
    new_path = copy_folder + semi_path + '/'
    x = os.system('rsync -a '+file_path+ ' ' + new_path)
    if x == 0:
        print('Successfully copied to %s' %new_path)
    else:
        print('Something has gone wrong and the file at %s has not been backed up' %file_path)


def new_experiment(experiment_name=None, drive=None):
    """
    Setup a new experiment
    :param experiment_name: Name of the experiment
    :param drive: either 'fileserver' or 'camserver'.
    :return:
    """

    if experiment_name is None:
        while True:
            r = input('Please enter experiment name: ').lower()
            if not r:
                continue
            experiment_name = r.replace(' ', '_')
            experiment_name = datetime.date.today().strftime("20%y_%m_%d_") + experiment_name
            if ask_yes_no("Is this okay: " + str(experiment_name)):
                break
    else:
        experiment_name = datetime.date.today().strftime("20%y_%m_%d_") + experiment_name

    if drive is None:
        drive = ask(question='Saving location:',
                    choices=['camserver', 'fileserver'],
                    help="'camserver' is appropriate for fast acquisition. Otherwise 'fileserver' is better suited.",
                    default='fileserver')
    elif drive not in ['camserver', 'fileserver']:
        raise RuntimeError("'drive' should be 'camserver' or 'fileserver'.")

    path = os.path.join('science_data', experiment_name)
    full_path = os.path.join(pco.local_drives[drive], path)
    scan_number = 0
    if not os.path.exists(full_path):
        print('Creating path %s.' % full_path)
        os.makedirs(full_path)
    else:
        print('Path %s already exists.' % full_path)
        # Attempt at extracting scan number
        for x in os.listdir(full_path):
            try:
                i = int(x)
                scan_number = max(scan_number, i+1)
            except ValueError:
                pass

    print('Next scan number set to %d.' % scan_number)

    config['experiment_drive'] = drive
    config['experiment_name'] = experiment_name
    config['experiment_path'] = path
    config['experiment_scan_number'] = scan_number

    return


# live view that runs in a separate thread, test to see how epics handles this
# need to suppress console output
def _live_view_helper():
    """
    Helper function for live view.
    continuously acquire snap images and display helper function
    """
    # need to disable printing output
    sys.stdout = open(os.devnull, 'w')

    c = 0
    while c < 100:
        c += 1
        snap()
        time.sleep(1)
        if liveview_abort:
            sys.stdout = sys.__stdout__
            return


def live_view_start():
    """
    Continuously acquire snap images and display
    """
    t = threading.Thread(name='live_view', target=_live_view_helper)
    # t.setDaemon(True)
    t.start()
    # t = multiprocessing.Process(name='live_view',target=_live_view_helper)
    # t.start()


def live_view_stop():
    global liveview_abort
    liveview_abort = True


def tilt_series(focus_step_mm=0.05, step_no=11):
    """
    Acquire a series of images at different focus positions.
    Calculate scintillator tilt from these.
    A uniform high contrast object should be in the FOV for this
    Syntax:
        tilt_series(focus_step_mm=0.05, step_no=11)

    The complete procedure involves moving the focus in steps and taking
    an image each step, then calculating the standard deviation in local
    patches for each step from the defocusing, and finally calculating the
    scintillator tilt.
    """

    px_sz_mm = config['pixel_size'] * 1000

    # if no_steps is even, make it odd by adding 1
    if not step_no % 2:
        step_no += 1

    focus_pos = drivers['microscope'].get_pos_focus()

    drivers['microscope'].move_abs_focus(focus_pos - ((step_no - 1) * focus_step_mm / 2))

    with Scan(exp_time=5):
        for ind_step in range(step_no):
            # move focus to position
            try:
                drivers['microscope'].move_rel_focus(focus_step_mm)
            except KeyError:
                print ('It looks like you havent initialised the microscope')
            capture()

    # move back to initial position
    try:
        drivers['microscope'].move_abs_focus(focus_pos)
    except KeyError:
        print ('It looks like you havent initialised the microscope')

    # calculate tilt angles
    thetax, thetay, s = tilt_calc(step_no, focus_step_mm)
    print('tilt angles are %f mrad in x and %f mrad in y' % (thetax, thetay))
    return thetax, thetay, s


def tilt_calc(step_no, focus_step_mm):
    """
    Calculate the scintillator tilt from a series of images acquired by tilt_series()
    used in tilt_series()
    Syntax:
        tilt_calc(step_no, focus_step_mm)
    returns tiltx and tilty in mrad. Also returns s, the matrix of standard deviations of the regions
    """
    px_sz_mm = config['pixel_size'] * 1000
    files = sorted(glob(os.path.join(config['experiment_last_scan_path'], '*.h5')))
    vol = np.zeros((step_no, 2048, 2048))
    for i in range(len(files)):
        F = h5py.File(files[i])
        image = np.array(F['entry']['data']['image'])[0]
        vol[i, :, :] = image[:, :2048]
        F.close()

    # process each frame in sequence
    # tile it into 16 X 16 squares
    s = np.zeros((vol.shape[0], 16, 16))  # store standard deviation of each tile here
    coords_max = np.zeros((vol.shape[0], 3))  # z,x and y where z is the focus position and x,y position within frame
    for ind_frame in range(vol.shape[0]):
        frame = vol[ind_frame]
        # tile
        for i in range(16):
            for j in range(16):
                s[ind_frame, i, j] = np.std(frame[i * 128:(i + 1) * 128, j * 128:(j + 1) * 128])
        # get the coords of the maximum std for each frame
        coords_max[ind_frame, 0] = ind_frame * focus_step_mm
        coords_max[ind_frame, 1] = np.unravel_index(s[ind_frame].argmax(), s[ind_frame].shape)[0] * px_sz_mm
        coords_max[ind_frame, 2] = np.unravel_index(s[ind_frame].argmax(), s[ind_frame].shape)[1] * px_sz_mm

    # center the coords_max
    coords_max -= coords_max.mean(axis=0)

    # calculate the covariance matrix of coords_max (?)
    R = np.cov(coords_max, rowvar=False)
    evals, evecs = np.linalg.eigh(R)  # compute eigenvectors

    # get index of largest eigenvalue and corresponding eigenvector
    ind_max = np.argmax(evals)
    v = evecs[:, ind_max]
    # get the tilt angles
    thetax = np.arctan(v[1] / v[0]) * 1e3  # 0 component is z, in mrad
    thetay = np.arctan(v[2] / v[0]) * 1e3
    return thetax, thetay, s  # , v #seems to somewhat work...


# acquire and store a series of images at different focus positions
# this moves the focus +- step_no/2 by distance focus_step and takes an image at
# each position. Stores images a folder for focussing

def focus_series(focus_step_mm=0.05, exp_time=10, step_no=11, MTF=False):
    """
    Acquire a series of images at different focus positions
    Calculate optimum focus position from these based on standard deviation
    A uniform high contrast object should be in the FOV for this
    Syntax:
       focus_series(focus_step_mm=0.05,step_no=11)
    """

    # store focus positions in here
    xpos = []
    # store images in here
    imgs = []

    # if no_steps is even, make it odd by adding 1
    if not step_no % 2:
        step_no += 1

    # get the current focus position
    try:
        pos_start = drivers['microscope'].get_pos_focus()
    except KeyError:
        print ('It looks like you havent initialised the microscope')

    for ind_step in range(step_no):
        # move focus to position
        drivers['microscope'].move_abs_focus(
            pos_start - focus_step_mm * (step_no - 1) / 2 + ind_step * focus_step_mm)
        xpos.append(drivers['microscope'].get_pos_focus())
        a = snap(exp_time=exp_time)
        imgs.append(a[500:1500, 250:750])
        plt.figure(figsize=(10, 10))
    plt.imshow(a[500:1000, 400:500])
    plt.colorbar()
    print drivers['microscope'].get_pos_focus()

    imgs = np.asarray(imgs)
    # move back to initial position
    drivers['microscope'].move_rel_focus(-focus_step_mm * (step_no - 1) / 2)

    # calculate focus position and move there
    if MTF is True:
        MTF_calc(xpos, pos_start, focus_step_mm, step_no)
    else:
        focus_calc(imgs, xpos, pos_start, focus_step_mm, step_no)
    snap(exp_time=exp_time)

    return imgs


def focus_calc(imgs, x, pos_start, focus_step_mm=0.05, step_no=11):
    """
    Calculate the focus position from a series of images acquired by focus_series()
    and move there.
    Used in focus_series()
    Syntax:
        focus_calc(pos_start,focus_step_mm=0.05,step_no=11)
    returns nothing
    """
    vol = imgs[:, :, :]
    s = np.zeros(vol.shape[0])

    for ind_frame in range(vol.shape[0]):
        s[ind_frame] = np.std(vol[ind_frame])

    # ideally, this should give a nice curve with one maximum somewhere
    # put x as input as python sometimes seems to have trouble making an array of the correct length (rounding error?)
    y = s
    # approximate with gaussian
    mu = sum(x * y) / sum(y)  # estimate of starting positions
    sigma = sum((mu - x) ** 2 * y) / sum(x)
    print('len x: ' + str(len(x)))
    print('len y: ' + str(len(y)))
    plt.figure()
    plt.plot(x, y, 'ro')
    plt.show()
    p, c = scipy.optimize.curve_fit(gauss_curve, x, y, p0=[max(y) - min(y), mu, sigma, min(y)])  # fit
    # plot results
    x_plot = np.arange(pos_start - (step_no + 1) / 2 * focus_step_mm, pos_start + (step_no + 3) / 2 * focus_step_mm,
                       focus_step_mm / 10)
    y_plot = gauss_curve(x_plot, p[0], p[1], p[2], p[3])
    max_pos = p[1]

    # plot results
    fh = plt.figure(101)
    fh.clf()
    plt.plot(x_plot, y_plot, 'b-')
    plt.plot(x, y, 'ro')
    plt.axvline(x=max_pos)
    plt.show(block=False)

    # if maximum outside the search area abort
    if max_pos <= pos_start - (step_no - 1) / 2 * focus_step_mm or max_pos >= pos_start + (
        step_no - 1) / 2 * focus_step_mm:
        print('maximum found outside search area, aborting...')
        return

    # else move to maximum position
    toggle_move = input('optimal position found at %f, move there ([y]/n)?' % max_pos)
    if toggle_move == '':
        toggle_move = 'y'
    while toggle_move != 'y' and toggle_move != 'n':
        toggle_move = input('wrong input, please answer y or n:')
    if toggle_move == 'y':
        drivers['microscope'].move_abs_focus(float(max_pos))

    return


def getAreatoFocus(img1):
    """"" This function gets called during focus_calc. It allows the user to select the area of the image
    to peform the focus_calc on, so that they can crop out unwanted features."""

    check = False
    vmin = 0
    vmax = 1000
    print("The following section is for selecting the area in which to peform focus")
    print("To begin, please adjust the colour map's mininum and maximum values until sample is visible")
    while check == False:
        plt.imshow(img1, vmin=vmin, vmax=vmax)
        plt.colorbar()
        plt.show(block=False)
        vmin = float(input('Please enter cmap mininum: '))
        vmax = float(input('Please enter cmap maximum: '))
        try:
            plt.imshow(img1, vmin=vmin, vmax=vmax)
            plt.colorbar()
            plt.show(block=False)
            check2 = input('Sample visible? y/n')
            if check2 == 'y':
                check = True
        except:
            print("Invalid input, try again")
            vmin = -1
            vmax = 1

    check = False
    print("Now, when prompted, please give the start and end x and x values")
    while check == False:
        plt.imshow(img1, vmin=vmin, vmax=vmax)
        plt.xlabel('x')
        plt.ylabel('z')
        plt.colorbar()
        plt.show(block=False)
        x1 = int(input('Please enter x start:'))
        x2 = int(input('Please enter x end:'))
        z1 = int(input('Please enter z start:'))
        z2 = int(input('Please enter z end:'))

        try:
            plt.imshow(img1[z1:z2, x1:x2], vmin=vmin, vmax=vmax)
            plt.xlabel('x')
            plt.ylabel('z')
            plt.colorbar()
            plt.show(block=False)
            check2 = input('Is this okay? y/n')
            if check2 == 'y':
                check = True
        except:
            x1 = 0
            z1 = 0
            x2 = len(img1[0])
            z2 = len(img1)

    return x1, x2, z1, z2


def MTF_calc(x, pos_start, focus_step_mm=0.05, step_no=11):
    """
    Calculate MTF from a series of edge images acquired
    with focus_series()
    """
    # get a list of the existing files
    file_list = os.listdir('/camserver/live_view/focus')

    # get file extension
    fext = file_list[0].split('.')[1]

    # load all files
    vol = np.zeros((step_no, 2048, 2048))
    if fext == 'h5':
        for ind_file, file_name in enumerate(file_list):
            fid = h5py.File('/camserver/live_view/focus/' + file_name,'r')
            frame = np.squeeze(fid['/entry/data'])
            frame = np.asarray(frame)
            vol[ind_file] = frame[:, :2048] # get rid of the last few columns as they might be broken
            fid.close()
    elif fext == 'tif':
        for ind_file, file_name in enumerate(file_list):
            frame = np.asarray(PIL.Image.open('/camserver/live_view/focus/' + file_name))
            vol[ind_file] = frame[:, :2048] # get rid of the last few columns as they might be broken
    else:
        print('wrong files?')
        return

    # calculate MTF for each frame
    MTFs = np.zeros((step_no, vol.shape[1]/2-100))
    MTF50s = np.zeros((step_no,))
    for ind_frame in range(step_no):
        v, m = mtffun_hans.calc_MTF(vol[ind_frame, :, :])
        MTFs[ind_frame, :] = v
        MTF50s[ind_frame] = m

    # fit with gaussian
    y = MTF50s
    mu = sum(x*y)/sum(y) # estimate of starting positions
    sigma = sum((mu-x)**2*y)/sum(x)
    p, c = scipy.optimize.curve_fit(gauss_curve, x, y, p0=[max(y)-min(y), mu, sigma, min(y)], maxfev=50000)  # fit

    # plot results
    x_plot = np.arange(pos_start-(step_no+1)/2*focus_step_mm, pos_start+(step_no+3)/2*focus_step_mm, focus_step_mm/10)
    y_plot = gauss_curve(x_plot, p[0], p[1], p[2], p[3])

    # display results
    plt.figure(300)
    for i in range(MTFs.shape[0]):
        plt.plot(MTFs[i, :])
    plt.axhline(y=0.5)
    plt.figure(301)
    plt.plot(x, MTF50s, 'ro')
    plt.plot(x_plot, y_plot, 'b-')
    max_pos = p[1]
    plt.axvline(x=p[1])

    # if maximum outside the search area abort
    if max_pos <= pos_start-(step_no-1)/2*focus_step_mm or max_pos >= pos_start+(step_no-1)/2*focus_step_mm:
        print('maximum found outside search area, aborting...')
        return

    # else move to maximum position
    toggle_move = input('optimal position found at %f, move there ([y]/n)?' % max_pos)
    if toggle_move == '':
        toggle_move = 'y'
    while toggle_move != 'y' and toggle_move != 'n':
        toggle_move = input('wrong input, please answer y or n:')
    if toggle_move == 'y':
        drivers['microscope'].move_abs_focus(float(max_pos))


def gauss_curve(x, a, mu, sigma, c):
    """
    Gaussian model used by focus_calc to find optimal focus position
    """
    return a*np.exp(-(mu-x)**2/(2*sigma**2)) + c


def big_scan(start_x, start_y, end_x, end_y, zoom=2, exp_time=1, vmax=200, binning=True, move_combine = False):
    """A tool for scanning a large area for either creating a mosaic of a large sample or finding a smaller one.
    Takes images starting from start position and ending at the next convenient place after end position.

    The images are stitched using the effective pixel size and assuming motor positions are correct, not through
    cross correlations. This is something that should be implemented in future.
    This code will also need to be changed once the Smaracts are back for use.

    Also consider binning each image before putting it into the big array to save RAM.

    Inputs-
    -> start_x, start_z - Motor start positions
    -> end_x, end_z - Approx end positions, it will overshoot these if they are not exactly an integer
    number of frames away
    -> zoom -  the magnification that you are using (default 2)
    -> exp_time - the exposure time to pass to snap (default 1)
    -> vmax - to pass to snap (default 200)
    -> binning - if True (default True) the result is binned so the z is 1 frame wide and correct aspect ration

    Written by Ronan"""

    # defining how far to move
    if zoom == 2:  # 2 is a special case as we can see the side of the scintillator mount
        step_size = 3
        n_pix = 1787
    else:
        n_pix = 2048
        step_size = n_pix * (config['pixel_size']) *1000
    moves_x = int(math.ceil((end_x - start_x) / step_size)) + 1
    moves_y = int(math.ceil((end_y - start_y) / step_size)) + 1
    print('moving ' + str(moves_x) + ' in x and ' +str(moves_y) + ' in z')
    z = motors['sy'].mv(start_y)
    motors['sxl'].mv(start_x)
    big_list = []
    all_the_stuff = np.zeros([(moves_y) * n_pix, (moves_x) * n_pix])
    for i in range(moves_y):
        x = motors['sxl'].mv(start_x)
        for j in range(moves_x):
            if move_combine:
                im = move_and_combine(exp_time=exp_time)[0]
            else:
                im = snap(exp_time=exp_time, vmax=vmax)
            im = np.flipud(im)
            l = [x, z, im]
            print('x= ' + str(x) + ' z= ' + str(z))
            big_list.append(l)
            if zoom == 2:
                all_the_stuff[1787 * i:1787 * (i + 1), 1787 * j:1787 * (j + 1)] = im[200:1987, 200:1987]#, axis = 1)
            else:
                all_the_stuff[n_pix * i:n_pix * (i + 1), n_pix * j:n_pix * (j + 1)] = im[:, :2048]#, axis = 1)
            plt.imshow(all_the_stuff, vmax = vmax , origin = 'upper')
            plt.pause(0.01) #to update screen
            j += 1
            x = motors['sxl'].mvr(step_size)
        if i < moves_y -1:
            z = motors['sy'].mvr(step_size)
        i += 1
    if binning:
        all_the_stuff = rebin(all_the_stuff, [2048, int(2048*moves_y/moves_x)])
        plt.imshow(all_the_stuff, vmin=0, vmax=200, origin= 'upper')
    return all_the_stuff


def pixel_size_finder(images, distance_moved, show=True, update=True):
    """
    :param images: list containing images
    :param distance_moved: the distance moved in the x direction between each image in mm
    :param show: plots result of True
    :param update: upates pixel size in dictionary if True
    :return:
    This is a function for finding the pixel size from a set of images where a hard object is moved in regular intervals.
    It works by averaging vertically and finding the maximum and minimum gradient changes in this, and fitting them lineraly
    inputs:
    images - a list of images
    distance moved - the distance moved between each image in mm
    show - if True plots graphs for error checking, these should be two diagonal lines
    """

    mins = []
    maxs = []
    for image in images:
        diff = np.diff(np.mean(medfilt(image[:, :2048],5)[5:-5,5:-5], axis=0))
        mins.append(np.argmin(diff))
        maxs.append(np.argmax(diff))

    if show:
        plt.plot(mins)
        plt.plot(maxs)
        plt.show()

    min_calc = np.polyfit(np.arange(len(mins)), mins, 1)[0]
    max_calc = np.polyfit(np.arange(len(mins)), maxs, 1)[0]

    if abs(min_calc - max_calc > 10):
        print('The gradients of the two lines are different, this may mean the results are incorrect')
    npix = (min_calc + max_calc) / 2

    psize = abs(distance_moved / (npix * 1000))

    if update:
        config['pixel_size'] = psize

    return psize


def move_and_combine_large(exp_time, start_x, start_y, end_x, end_y, flat = None, mode='sample',
                           max_iter=3,  remove_hits=False):

    if exp_time is None:
        exp_time = drivers['pco'].exp_time

    if flat is None:
        flat = FRAMES['flat'].get(_exp_time_as_key(exp_time), None)

    scan_path = moving_image_stack_large(start_x, start_y, end_x, end_y, exp_time=exp_time, mode=mode)

    files_to_stitch = sorted(glob(os.path.join(scan_path, '*.h5')))
    print files_to_stitch
    img = stitching.stack_files(files_to_stitch=files_to_stitch,
                                save_folder=scan_path,
                                flat_location=flat,
                                mode=mode,
                                psize=config['pixel_size'],
                                max_iter=max_iter,
                                remove_hits=remove_hits)

    return img


def moving_image_stack_large(start_x, start_y, end_x, end_y, exp_time=10, mode='sample'):
    """

    :param start_x: start position of ROI in X - the first image will be taken 512 pixels before this for stitching
    :param start_y: start y - the first image will be taken 512 pixels before this for stitching
    :param end_x: end of ROI - images will be taken at least 512 pixels past this, potentially more
    :param end_y: end of ROI - images will be taken at least 512 pixels past this, potentially more
    :param exp_time:
    :param mode: 'sample' for sample motors, diffuser for diffuser motors
    :return:
    """

    dist_mov = 1024 * config['pixel_size'] * 1000
    twenty_pix = 20 * config['pixel_size'] * 1000
    x_pos = start_x - twenty_pix
    y_pos = start_y - twenty_pix
    move_array = []  # start at -20,-20 from start
    move_array.append([x_pos, y_pos])
    x_pos += twenty_pix  # add 20 to x
    move_array.append([x_pos, y_pos])
    while x_pos <= end_x:
        x_pos += dist_mov  # keep increasing x by set distance
        move_array.append([x_pos, y_pos])
    x_pos += twenty_pix  # add 20 to x for final move
    move_array.append([x_pos, y_pos])

    y_pos += twenty_pix
    x_pos = start_x - twenty_pix  # reset x, y now at zero, repeat
    move_array.append([x_pos, y_pos])
    x_pos += twenty_pix
    move_array.append([x_pos, y_pos])
    while x_pos <= end_x:
        x_pos += dist_mov
        move_array.append([x_pos, y_pos])
    x_pos += twenty_pix
    move_array.append([x_pos, y_pos])

    while y_pos <= end_y:  # loop for y too now
        y_pos += dist_mov
        x_pos = start_x - twenty_pix
        move_array.append([x_pos, y_pos])
        x_pos += twenty_pix
        move_array.append([x_pos, y_pos])
        while x_pos <= end_x:
            x_pos += dist_mov
            move_array.append([x_pos, y_pos])
        x_pos += twenty_pix
        move_array.append([x_pos, y_pos])

    y_pos += twenty_pix  # final run with y moved by another twenty
    x_pos = start_x - twenty_pix
    move_array.append([x_pos, y_pos])
    x_pos += twenty_pix
    move_array.append([x_pos, y_pos])
    while x_pos <= end_x:
        x_pos += dist_mov
        move_array.append([x_pos, y_pos])
    x_pos += twenty_pix
    move_array.append([x_pos, y_pos])

    move_array = np.array(move_array)

    with Scan(exp_time=exp_time):
        for i in range(np.shape(move_array)[0]):
            print('Taking frame %d of %d' % (i+1, np.shape(move_array)[0]))
            if mode == 'sample':
                motors['sxl'].mv(move_array[i, 0])
                motors['sy'].mv(move_array[i, 1])

            elif mode == 'diffuser':
                motors['xpsx'].mv(move_array[i, 0])
                motors['xpsy'].mv(move_array[i, 1])
            capture()
    # Return the location of files
    return config['experiment_last_scan_path']
