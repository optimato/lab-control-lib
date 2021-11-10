# -*- coding: utf-8 -*-
"""
Sub-pixel translation matching based on cross-correlations.

Author: Pierre Thibault
Date: June 2018
"""

import numpy as np
from scipy.signal import fftconvolve


def match(Ib, It, Ifact=None, mb=None, mt=None, scale=True, max_shift=None):
    """
    Solve the generalized matching problem

    L(s) = 1/N(s) * sum_r mb[r-s] * mt[r] * (Ifact[r] * Ib[r - s] - It[r])**2

    with N(s) = sum_r mb[r-s] * mt[r]

    :param Ib: Base image on which to match template
    :param It: Template image
    :param Ifact: Multiplier
    :param mb: Base image mask
    :param mt: Template mask
    :param scale: True, False or 'phase"
    :param max_shift: maximum relative shift allowed. [TODO: might not need to be around 0]

    Return a dict containing:
      * 'r', the two-dimensional vector shift
      * 'scale', the optimal scaling factor
      * 'D', the value of the optimization function at the minimum
      * 'status', a code and message telling if everything went ok.
      * maybe something else in the future
    """

    # Check dimensions

    rsh = Ib.shape
    tsh = It.shape

    if (tsh[0] > rsh[0]) or (tsh[1] > rsh[1]):
        raise RuntimeError('The base image should be larger than the template.')

    ctr = (np.array(rsh) + np.array(tsh)) // 2

    if mt is None:
        mt = np.ones_like(It, dtype=float)

    # Compute elements of distance metric depending on existence of input arrays.
    if mb is None:
        N = mt.sum()
        T2 = (mt*abs(It)**2).sum()
        if Ifact is None:
            T1 = cc(abs(Ib)**2, mt)
            T3 = cc(Ib, mt*It.conj())
        else:
            T1 = cc(abs(Ib)**2, mt*abs(Ifact)**2)
            T3 = cc(Ib, mt*Ifact*It.conj())
    else:
        N = cc(mb, mt)
        T2 = cc(mb, mt*abs(It)**2)
        if Ifact is None:
            T1 = cc(mb*abs(Ib)**2, mt)
            T3 = cc(mb*Ib, mt*It.conj())
        else:
            T1 = cc(mb*abs(Ib)**2, mt*abs(Ifact)**2)
            T3 = cc(mb*Ib, mt*Ifact*It.conj())

    # Compute scaling factor if required
    c = 1.
    if scale is not False:
        c = T3/T2
        if scale == 'phase':
            c /= abs(c)

    # Construct distance map
    D = (T1 + T2*abs(c)**2 - 2*np.real(np.conj(c)*T3))/(N + 1e-8)

    if max_shift is not None:
        ii0, ii1 = np.ogrid[:D.shape[0], :D.shape[1]]
        c = (((ii0 - tsh[0] - 1)**2 + (ii1 - tsh[1] - 1)**2) > max_shift**2)
        D[c] = D.max()

    # Find subpixel optimum
    r, minD = sub_pix_min(D)
    if scale is not False:
        s = c[tuple((np.round(r).astype(int)))]
    else:
        s = 1.
    r -= tsh
    r += 1

    return {'r': r, 'scale': s, 'D': D, 'status': 'OK'}


def cc(A, B, mode='full'):
    """
    A fast cross-correlation based on scipy.signal.fftconvolve.

    :param A: The reference image
    :param B: The template image to match
    :param mode: one of 'same', 'full' (default) or 'valid' (see help for fftconvolve for more info)
    :return: The cross-correlation of A and B.
    """
    return fftconvolve(A, B[::-1, ::-1], mode=mode)

def pshift(a, ctr):
    """
    Shift a N-dimensional array with "N-linear" interpoloation so that ctr becomes the origin.
    """
    sh  = np.array(a.shape)
    out = np.zeros_like(a)

    ctri = np.floor(ctr).astype(int)
    ctrx = np.empty((2, a.ndim))
    ctrx[1,:] = ctr - ctri     # second weight factor
    ctrx[0,:] = 1 - ctrx[1,:]  # first  weight factor

    # walk through all combinations of 0 and 1 on a length of a.ndim:
    #   0 is the shift with shift index floor(ctr[d]) for a dimension d
    #   1 the one for floor(ctr[d]) + 1
    comb_num = 2**a.ndim
    for comb_i in range(comb_num):
        comb = np.asarray(tuple(("{0:0" + str(a.ndim) + "b}").format(comb_i)), dtype=int)

        # add the weighted contribution for the shift corresponding to this combination
        cc = ctri + comb
        out += np.roll( np.roll(a, -cc[1], axis=1), -cc[0], axis=0) * ctrx[comb,list(range(a.ndim))].prod()

    return out

# Polynomial coefficients for the autocorrelation of the triangular function
coeffs = np.array([[1., -3., 3., -1],
          [4., 0, -6., 3.],
          [1., 3., 3., -3.],
          [0., 0., 0., 1.]])
# Conversion matrix
M = np.array([np.multiply.outer(coeffs[j], coeffs[i]).ravel() for i in range(4) for j in range(4)]).T

# Exponent arrays for 0th, 1st and 2nd derivatives
e0 = np.array([0,1,2,3])
e1 = np.array([0,0,1,2])
e2 = np.array([0,0,0,1])

# Interpolant and derivatives at x0 
def allf(x0, c):
    x,y = x0
    return np.dot(np.array([np.multiply.outer(y**e0, x**e0).ravel(),
                            np.multiply.outer(y**e0, e0 * x**e1).ravel(),
                            np.multiply.outer(e0 * y**e1, x**e0).ravel(),
                            np.multiply.outer(y**e0, e1*e0 * x**e2).ravel(),
                            np.multiply.outer(e0 * y**e1, e0 * x**e1).ravel(),
                            np.multiply.outer(e0*e1 * y**e2, x**e0).ravel()]), c)


def sub_pix_min(a):
    """
    Find the position of the minimum in 2D array a with subpixel precision.
    """
    sh = a.shape
    
    # Find the global minimum
    cmin = np.array(np.unravel_index(a.argmin(), sh))

    # Move away from edges
    if cmin[0] < 2:
        cmin[0] = 2
    elif cmin[0]+2 >= sh[0]:
        cmin[0] = sh[0] - 3
    if cmin[1] < 2:
        cmin[1] = 2
    elif cmin[1]+2 >= sh[1]:
        cmin[1] = sh[1] - 3

    # Sub-pixel minimum position.
    a0 = a[(cmin[0]-2):(cmin[0]+3), (cmin[1]-2):(cmin[1]+3)]
  
    # Find which quandrant to refine
    jp = 1 if a0[2,3]<a0[2,1] else 0
    ip = 1 if a0[3,2]<a0[1,2] else 0
    af = a0[ip:ip+4, jp:jp+4]

    # Generate vector
    c = np.dot(M, af.ravel())

    # Newton-Raphson
    x0 = np.array([1.-ip, 1.-jp])
    tol = 1e-8
    for i in range(15):
        f, fx, fy, fxx, fxy, fyy = allf(x0, c)
        dx = -np.array([fyy*fx - fxy*fy, -fxy*fx + fxx*fy])/(fxx*fyy - fxy*fxy)
        x0 += dx
        if (dx*dx).sum() < tol:
            break
    r = x0 - 1 + np.array([ip, jp]) + cmin

    return r, f/36.


if __name__ == "__main__":
    import numpy as np
    from scipy import ndimage as ndi
    a = np.zeros((512, 512))
    a[4:7, 4:7] = 2
    b = np.zeros((10, 10))
    b[:3, :3] = 1
    result = match(a, b)






