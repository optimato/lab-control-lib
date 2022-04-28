"""
Scanning routines.
"""

import numpy as np
import h5py
import os

from .ui import FRAMES, Scan, capture, _exp_time_as_key, _show
from . import drivers, motors, config
from ..analysis import stitching

STITCH_MOTOR_X = 'sxl'
STITCH_MOTOR_Y = 'sy'


def stitch_scan(N=5, pixel_range=50, exp_time=None, max_iter=5, crop_to_original=False):
    """
    Take N images randomly shifted within given range and stitch them to reduce
    scintillator artifacts. The random displacements are only positive, so the (0,0)
    coordinate of the final image is at the current motor position.

    :param N:
    :param pixel_range:
    :param exp_time:
    :return:
    """
    # Sort out exposure time
    pcodrv = drivers['pco']
    if exp_time is None:
        exp_time = _exp_time_as_key(pcodrv.exp_time)

    # Check for existence of flat and dark
    exp_key = _exp_time_as_key(exp_time)
    if exp_key not in FRAMES['flat']:
        raise RuntimeError('Could not find a flat for exposure time %f' % exp_time)
    if exp_key not in FRAMES['dark']:
        raise RuntimeError('Could not find a dark for exposure time %f' % exp_time)

    # Get scanning motors
    mx, my = motors[STITCH_MOTOR_X], motors[STITCH_MOTOR_Y]

    # Generate random relative displacements (in pixel units)
    positions = np.random.randint(1, pixel_range+1, size=(N, 2))
    dx, dy = positions.T

    # One of them is no displacement
    dx[0] = 0
    dy[0] = 0

    # Create absolute motor positions
    # TODO: Find a good explanation for the need to multiply y by -1 but not x
    px = dx * config['pixel_size'] + mx.pos
    py = -1 * dy * config['pixel_size'] + my.pos

    # Take scan
    filenames = []
    with Scan(exp_time=exp_time):
        for i in range(N):
            mx.mv(px[i], block=False)
            my.mv(py[i])
            print('Taking frame %d of %d' % (i+1, N))
            f = capture()
            filenames.append(f)

    img, f, new_positions = stitch(scan_or_path=filenames,
                                   flat=FRAMES['flat'][exp_key],
                                   dark=FRAMES['dark'][exp_key],
                                   positions=positions,
                                   max_iter=max_iter,
                                   max_shift=2 * pixel_range)

    # Load frames
    images = []
    for filename in filenames:
        with h5py.File(filename) as f:
            images.append(np.array(f[u'entry'][u'data'][u'image'])[0])

    sh = images[0].shape
    # Stitch
    img, f, new_positions = stitching.merge_image_stack(frames=images,
                                positions=positions,
                                flat=FRAMES['flat'][exp_key],
                                max_iter=max_iter,
                                max_shift=2*pixel_range)

    # Optionally crop down image
    if crop_to_original:
        img = img[:sh[0], :sh[1]]

    # Save resulting image
    save_path = config['experiment_last_scan_path']
    save_file = os.path.join(save_path, 'stitch.h5')

    print('Saving to %s.' % save_file)

    if os.path.exists(save_file):
        old = save_file + ".old"
        open(old, 'w').write(open(save_file, 'r').read())
        os.remove(save_file)

    with h5py.File(save_file) as g:
        with h5py.File(filenames[0]) as f:
            g.copy(f[u'entry'], u'entry')  # direct copy to preserve structure and metadata
        del g[u'entry'][u'data'][u'image']
        g.create_dataset(u'/entry/data/image', data=img)
        g[u'entry'].create_dataset(u'positions_from_stitch', data=new_positions)
        g[u'entry'].create_dataset(u'positions_from_motors', data=positions)
        g[u'entry'].attrs[u'n_images'] = N

    _show(img, figno=150)
    return img


def stitch(path_or_list, flat=None):
    """

    :param scan_or_path:
    :param flat:
    :return:
    """
    if type(path_or_list) is str:
        from glob import glob
        filenames = glob.glob(os.path.join(path_or_list, '*_0*.h5'))
    else:
        filenames = path_or_list

    # Load frames
    images = []
    for filename in filenames:
        with h5py.File(filename) as f:
            images.append(np.array(f[u'entry'][u'data'][u'image'])[0])

    sh = images[0].shape
    # Stitch
    img, f, new_positions = stitching.merge_image_stack(frames=images,
                                positions=positions,
                                flat=FRAMES['flat'][exp_key],
                                max_iter=max_iter,
                                max_shift=2*pixel_range)

    # Optionally crop down image
    if crop_to_original:
        img = img[:sh[0], :sh[1]]

    # Save resulting image
    save_path = config['experiment_last_scan_path']
    save_file = os.path.join(save_path, 'stitch.h5')

    print('Saving to %s.' % save_file)

    if os.path.exists(save_file):
        old = save_file + ".old"
        open(old, 'w').write(open(save_file, 'r').read())
        os.remove(save_file)

    with h5py.File(save_file) as g:
        with h5py.File(filenames[0]) as f:
            g.copy(f[u'entry'], u'entry')  # direct copy to preserve structure and metadata
        del g[u'entry'][u'data'][u'image']
        g.create_dataset(u'/entry/data/image', data=img)
        g[u'entry'].create_dataset(u'positions_from_stitch', data=new_positions)
        g[u'entry'].create_dataset(u'positions_from_motors', data=positions)
        g[u'entry'].attrs[u'n_images'] = N
