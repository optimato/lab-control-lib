"""
Image correction tools
"""

import numpy as np
import scipy.ndimage as ndi

__all__ = ['rl_deconvolution', 'example_mtf', 'guided_filter']

def rl_deconvolution(data, mtf, numit):
    """
    Richardson-Lucy deconvolution of input MTF on 2d array data.

    Old docstring (still need to figure out what this means):
    Assumes up to now that mtf is syymmetric and that data is real and positive
    mtf is non fft shifted that means that the dc component is on mtf[0,0]
    Todo:
    non symmetric mtf: mtf.conj()[-q] somewhere
    optimisation: FFTW? scipy fft? error metric cancel iter?
    code by marco
    """

    myConv = lambda x: np.abs(np.fft.ifft2(np.fft.fft2(x)*mtf)).astype(x.dtype)

    u = data.copy()
    for n in range(numit):
        u *= myConv(data/(myConv(u)+1e-6))
    return u


def example_mtf(asize):
    """
    MTF model for the scintillator-coupled frelon camera at ID16A ESRF.
    """
    p = [0.654273, 0.590343, 1.658131, 0.209558, 3.900136, 0.093059, 10.102529, 0.073378, 30.158980]
    p.append(1.-(p[1]+p[3]+p[5]))
    mtf = np.zeros(asize)
    q2 = U.fvec2(asize, (1./asize[0], 1./asize[1]))

    for n in range(4):
        mtf += p[2*n+1]*np.exp(-(np.pi*p[2*n])**2*q2)

    return mtf


def guided_filter(im, flt='box', r=2., eps=.01, g=None):
    """
    Guided filter implementation based on
    https://github.com/lisabug/guided-filter, itself from
    K.He, J.Sun, and X.Tang. Guided Image Filtering. TPAMI'12.
    """

    if flt == 'box':
        flt = ndi.uniform_filter
    elif flt == 'gauss':
        flt = ndi.gaussian_filter

    if g is None:
        im1 = flt(im, r)
        var_g = flt(im*im, r) - im1**2
        a = var_g / (var_g + eps)
        del var_g
        b = im1*(1 - a)
        del im1
        a1 = flt(a, r)
        del a
        b1 = flt(b, r)
        return a1*im + b1
    else:
        im1 = flt(im, r)
        g1 = flt(g, r)
        var_g = flt(g*g, r) - g1**2
        cov_im_g = flt(im * g, r) - im1*g1
        a = cov_im_g / (var_g + eps)
        b = im1 - a*g1
        a1 = flt(a, r)
        b1 = flt(b, r)
        return a1*g + b1
