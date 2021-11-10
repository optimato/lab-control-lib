import numpy as np
from . import ccshift
from scipy.ndimage import median_filter
from scipy.ndimage import gaussian_filter
import h5py
import os
import sys
import ast
from scipy.signal import convolve
from glob import glob

"""
Example:

from xnig import io

psize = np.array([2.979e-6])

# Load data
a = io.h5read('ronan_test.h5')
frames = a['data'][:, :, :2048] - 99.
flat = a['flat'][:, :2048] - 99.
fsh = frames[0].shape

# These positions seem quite off...
pos = a['pos']  # actually an array of the relative movements made
positions = np.empty(np.shape(pos))
for i in range(np.shape(positions)[0]):
    positions[i, :] = np.sum(pos[:i, :], axis=0)
print (positions)
positions *= 330  # some scaling stuff
positions = np.round(positions).astype(int)

exp_time = 10.

### Additional parameters ###
mask_threshold = 50  # For 1 s exposure time
mask_medfilt_size = 20

# Good enough to define a single mask based on the flat
mf = median_filter(flat, mask_medfilt_size)
mask = np.abs(flat-mf) < mask_threshold*exp_time
masks = [mask for i in range(len(positions))]


img, f, positions = merge_image_stack(frames, positions=None, flat=flat, mask=masks)

# Save initial and final positions so we can understand how to improve alignment
init_pos = (positions - positions.min(axis=0))/psize
new_pos = np.array([v.coord/psize for v in vl])

# Dump png of the radiography
from matplotlib import pyplot
pyplot.imsave('stitched_radiograph_LR.png', np.log(img_s.data[0])[::2, ::2], vmin=-2.3, vmax=.1, cmap='bone')

# Save relevant results
io.h5write('./result.h5', img=img_s.data, flat=f, init_pos=init_pos, final_pos=new_pos)
"""


def stack_files(files_to_stitch, save_folder, flat_location=None, dark_location=None, crop_to_original=False,
                mode='sample', psize = 2.5e-6, max_iter=50, remove_hits=False, save_str=''):
    """

    :param files_to_stitch:
    :param save_folder:
    :param flat_location:
    :param dark_location:
    :param crop_to_original:
    :param mode:
    :param psize:
    :param max_iter:
    :param remove_hits:
    :return:
    """

    darkvalue = 99

    psize = psize* 1000

    print("Loading Files")

    # import data
    images = []
    positions = []
    for i in range(len(files_to_stitch)):
        print('loading file number %i' % i)
        F = h5py.File(files_to_stitch[i])
        image = np.array(F['entry']['data']['image'])[0]
        if remove_hits:
            image = remove_direct_hits(image, 800)
        if mode == 'sample':
            x_pos = F['entry']['instrument']['positioner'].attrs['sample_x_labframe']
            y_pos = F['entry']['instrument']['positioner'].attrs['sample_y_absolute']
        elif mode == 'diffuser':
            x_pos = F['entry']['instrument']['positioner'].attrs['diffuser_x']
            y_pos = F['entry']['instrument']['positioner'].attrs['diffuser_y']
        exp_time = F['entry']['instrument']['detector'].attrs['exposure_time']
        images.append(image)
        F.close()
        positions.append([-y_pos, x_pos])

    images = np.array(images, dtype=float)
    positions = np.array(positions)
    positions[:, 0] -= positions[0, 0]  # taking away postion of first image to make all movements relative
    positions[:, 1] -= positions[0, 1]
    positions /= psize  # needs updating once pixel size is stored in metadata
    positions_from_motors = positions
    positions = np.round(positions).astype(int)

    flat = None
    if flat_location is not None:
        if type(flat_location) is str:
            with h5py.File(flat_location) as F:
                flat = np.array(F['entry']['data']['image'])[0].astype(float)
        else:
            flat = flat_location

    # Dark Correcting
    if dark_location is not None:
        if type(dark_location) is str:
            with h5py.File(dark_location) as F:
                dark = np.array(F['entry']['data']['image'])[0]
        else:
            dark = dark_location
        images = images[:, :, :2048] - dark[:, :2048]
        if flat is not None:
            flat = flat[:, :2048] - dark[:, :2048]
    else:
        images = images[:, :, :2048] - darkvalue
        if flat is not None:
            flat = flat[:, :2048] - darkvalue

    # copying code from above - probably not the best way to generate a mask
    mask_threshold = 50
    mask_medfilt_size = 20
    # generating a mask
    if flat_location is None:
        flat_for_mask = images.mean(axis=0)
    else:
        flat_for_mask = flat
    mf = median_filter(flat_for_mask, mask_medfilt_size)
    # mask = np.abs(flat_for_mask - mf) < mask_threshold * exp_time
    mask = np.abs(flat_for_mask - mf) < mask_threshold
    masks = [mask for i in range(positions.shape[1])]

    # error = 1./0.

    print('Stitching')
    positions_old = np.copy(positions)
    img, f, positions = merge_image_stack(images, positions=positions, flat=flat, mask=mask, max_iter=max_iter)
    print('Done stitching')
    # Dump png of the radiography
    from matplotlib import pyplot
    pyplot.imsave(os.path.join(save_folder, 'stitched_radiograph_LR.png'), np.log(img)[::2, ::2], vmin=-2.3, vmax=.1, cmap='bone')

    print()
    print("positions_old")
    print(positions_old)
    print("positions_new")
    print(positions)

    if crop_to_original:
        pos2 = positions - positions[0, :]
        if np.min(pos2[:, 0]) < 0:
            crop = img[abs(np.min(pos2[:, 0])): 2048 + abs(np.min(pos2[:, 0])), :]
        else:
            crop = img[:2048, :]
        if np.min(pos2[:, 1]) < 0:
            crop = crop[:, abs(np.min(pos2[:, 1])):2048 + abs(np.min(pos2[:, 1]))]
        else:
            crop = crop[:, :2048]
        img = crop

    # saving results
    save_file = os.path.join(save_folder, 'stitch'+save_str+'.h5')
    print('saving to %s.' % save_file)
    if os.path.exists(save_file):
        old = save_file + ".old"
        open(old, 'w').write(open(save_file, 'r').read())
        os.remove(save_file)
    F = h5py.File(files_to_stitch[0])
    G = h5py.File(save_file)
    G.copy(F['entry'], 'entry')  # direct copy to preserve structure and metadata
    del G['entry']['data']['image']
    G.create_dataset('/entry/data/image', data=img)
    G['entry'].create_dataset('positions_from_stitch', data=positions)
    G['entry'].create_dataset('positions_from_motors', data=positions_from_motors)
    G['entry'].attrs['n_images'] = len(files_to_stitch)
    F.close()
    G.close()

    return img, positions, positions_from_motors


def reshape_array(a, shifts, sh):
    """
    Change the dimensions of 2d array 'a' to fit tightly the total viewport given by
    the list of shifts and view shape.
    Return a_new, shifts_new
    where a_new is the cropped and/or padded array, and shifts_new are the new equivalent shifts
    """
    shifts = np.asarray(shifts)
    min0, min1 = shifts.min(axis=0)
    max0, max1 = shifts.max(axis=0) + sh

    shifts_new = shifts - (min0, min1)

    ash = a.shape
    nash = (max0 - min0, max1 - min1)

    if ash == nash:
        return a.copy(), shifts_new, np.array([min0, min1])

    a_new = np.zeros(nash, dtype=a.dtype)
    s0 = max(min0, 0)
    new_s0 = max(-min0, 0)
    e0 = min(ash[0], nash[0] + min0)
    new_e0 = min(nash[0], ash[0] - min0)

    s1 = max(min1, 0)
    new_s1 = max(-min1, 0)
    e1 = min(ash[1], nash[1] + min1)
    new_e1 = min(nash[1], ash[1] - min1)

    a_new[new_s0:new_e0, new_s1:new_e1] = a[s0:e0, s1:e1]

    return a_new, shifts_new, np.array([min0, min1])


def merge_image_stack(frames, positions=None, flat=None, mask=None, refine_flat=True, max_iter=50, max_shift=300):
    """
    Merge a stack of image that have been collected by moving the samples at various positions

    :param frames: The stack of images
    :param positions: the list of pixel shifts. If None, will be extracted from frames
    :param flat: flat field (frame without the sample in)
    :param mask: binary mask of valid image pixels
    :param refine_flat: if True, flat will be recovered from the data. If False, provided flat is used.
    :return:
    """
    N = len(frames)
    fsh = frames[0].shape

    offset = np.array([0, 0])

    # Crop out 10% of the edges - this could be removed or parametrised.
    mask_crop = min(fsh) // 10

    if mask is None:
        raise RuntimeError('Not yet implemented (need a lot of guesswork to generate it from the data')
        mask_threshold = 50  # For 1 s exposure time
        mask_medfilt_size = 20
        # Generate mask from flat
        if flat is None:
            # Generate mask from frame stack
            f = frames.mean(axis=0)
        else:
            f = flat
        mf = median_filter(f, mask_medfilt_size)
        mask = np.abs(f - mf) < mask_threshold * exp_time
        masks = N * [mask]

    # Check if mask is a stack of masks or a single one to be used for all
    mask = np.asarray(mask)
    if mask.ndim == 3:
        assert len(mask) == N
        masks = mask
    else:
        masks = N * [mask]

    # Create frame mask
    m0 = np.zeros_like(masks[0])
    m0[mask_crop:-mask_crop, mask_crop:-mask_crop] = 1.

    if positions is None:
        if flat is None:
            raise RuntimeError('No clever way of aligning the images without a flat has been found yet')
        # Initial alignment based on one frame as a reference
        img = frames[0] / flat
        positions = np.empty((N, 2), dtype=int)
        for i in range(N):
            result = ccshift.match(img, frames[i], flat, mtmp=m0 * masks[i], scale=False, mref=m0*masks[0], max_shift=max_shift)
            positions[i] = np.round(result['r']).astype(int)

    if not refine_flat:
        if flat is None:
            raise RuntimeError('flat must be refined if no flat is provided')

    # Initial estimate for img
    img, positions, new_offset = reshape_array(np.zeros((10, 10)), positions, fsh)
    offset += new_offset
    img_renorm = img.copy()
    for i in range(N):
        i0, i1 = positions[i]
        img[i0:i0 + fsh[0], i1:i1 + fsh[1]] += masks[i] * frames[i] * flat
        img_renorm[i0:i0 + fsh[0], i1:i1 + fsh[1]] += masks[i] * flat ** 2
    # Identify possible regions that were masked for all positions
    img_mask = (img_renorm != 0)
    # Normalise image
    img /= img_renorm + ~img_mask

    # Iteratively refine img and f
    alpha = 1.
    if flat is None:
        f = frames.mean(axis=0)
    else:
        f = flat.copy()
    f_renorm = np.zeros_like(f)

    # TODO: maybe provide a mask for flat as well
    fmask = np.ones_like(masks[0])
    for m in masks:
        fmask &= m

    # TODO: This is an assumption that needs to be documented:
    # The allowed maximum shift in cross-correlation fitting is twice the current shifts
    max_shift = 2 * (positions.max(axis=0) - positions.min(axis=0)).max()

    refine_pos = True
    for ii in range(max_iter):

        # Find f
        if refine_flat:
            fbefore = f.copy()
            f *= 1e-6
            f_renorm.fill(1e-6)
            if flat is not None:
                f += fmask * alpha * flat
                f_renorm += alpha * fmask
            for i in range(N):
                i0, i1 = positions[i]
                f += mask[i] * frames[i] * img[i0:i0 + fsh[0], i1:i1 + fsh[1]]
                f_renorm += mask[i] * img[i0:i0 + fsh[0], i1:i1 + fsh[1]] ** 2
            f /= f_renorm
            # print ii, (np.abs(f-fbefore)**2).sum()
            # Here implement some breaking criterion

        # Find img
        img *= 1e-6
        img_renorm.fill(1e-6)
        for i in range(N):
            i0, i1 = positions[i]
            img[i0:i0 + fsh[0], i1:i1 + fsh[1]] += masks[i] * frames[i] * f
            img_renorm[i0:i0 + fsh[0], i1:i1 + fsh[1]] += masks[i] * f ** 2
        img /= img_renorm
        img_mask = img_renorm > 1e-5

        # Refine positions
        if refine_pos:
            # This filter is needed to avoid matching noise.
            # Not clear yet what is the optimal sigma.
            img = gaussian_filter(img, 10.)

            old_positions = positions.copy()
            for i in range(N):
                i0, i1 = positions[i]
                result = ccshift.match(img[i0:i0 + fsh[0], i1:i1 + fsh[1]], frames[i], f, mt=m0 * masks[i],
                                       scale=False, mb=img_mask[i0:i0 + fsh[0], i1:i1 + fsh[1]], max_shift=max_shift)
                positions[i] += np.round(result['r']).astype(int)
                # print '%d: %s -> %s' % (i, str([i0, i1]), str(positions[i].tolist()))
            if np.all(old_positions == positions):
                # Convergence
                refine_pos = False
            else:
                img, positions, new_offset = reshape_array(img, positions, fsh)
                offset += new_offset
                img_renorm = reshape_array(img_renorm, positions, fsh)[0]
                img_mask = reshape_array(img_mask, positions, fsh)[0]
    return img, f, positions + offset


def remove_direct_hits(image, threshold, conv_threshold=1):
    """
    Removes direct hits by finding spots where the difference between the image and a 25*25 median fileter > threshold
    This mask is then convolved with a 3*3 as direct hits impact the surrounding pixels - conv_threshold controls
    how many pixels surrounding it need to be hot for the new mask.

    Returns the median_filtered image in areas where a hit is detected
    """

    mf = median_filter(image, (25, 25))
    diff = image - mf
    mask = diff > threshold
    kernel = np.ones((3, 3))
    c = convolve(mask, kernel, mode='same')
    mask2 = c > conv_threshold
    filtered = ((1 - mask2) * image) + (mask2 * mf)
    return filtered


def trawl_and_stitch(folder, save_folder, expected_images, psize, flat_location=None, dark_location=None, max_iter=3):
    '''Goes through the folder where data is stored and finds all folders with the right name
    If a folder has the fight number of files it stitches that folder'''
    useful_list = [folder+'/'+s+'/' for s in os.listdir(folder)]
    print useful_list
    for i in range(len(useful_list)):
        print len(os.listdir(useful_list[i]))
        if len(os.listdir(useful_list[i])) == expected_images:
            marker_file = open(useful_list[i]+ '/marker.txt', 'w')
            print 'now stiching in' + '/CTData_incoming/science_data/' + useful_list[i]
            files_to_stitch = sorted(glob(os.path.join(useful_list[i], '*.h5')))
            stack_files(files_to_stitch, save_folder=save_folder, flat_location=flat_location,
                        dark_location=dark_location, psize=psize, max_iter=max_iter, save_str=useful_list[i][-7:-1])
            # os.remove('/CTData_incoming/science_data/'+useful_list[i] + '/marker.txt')


