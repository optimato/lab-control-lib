"""\
Array utilities. Copied from the pyE17 package.

:Author:
    Pierre Thibault - original author.
    additional contributions by past and current members of the Bio
:Date:
    June 25th 2010
    
.. note::
    August 11 2011: ``np.fft`` replaced with ``scipy.fftpack.fft`` as both
    implementation are not exactly equivalent, and scipy's is quite 
    faster for large arrays (GP).

"""
import numpy as np
import warnings
import scipy.fftpack as fft
import matplotlib as mpl
from .plot_utils import Multiclicks
from scipy import ndimage
from scipy.optimize import curve_fit

__all__ = ['rmphaseramp', 'rmphaseramp2', 'fgrid', 'fvec2', 'shift_dist', 
           'shift_best', 'shift_vector_nD', 'fgrid_2d', 'fvec2_2d', 'lin_fit', 
           'lin_sub', 'quad_fit', 'quad_max', 'norm2', 'norm', 'abs2', 'pshift', 
           'delxf', 'delxb', 'delxc', 'delxrc', 'delxrc3D', 'del2', 'delxpf', 
           'delxpb', 'delxpc', 'del2p', 'rebin', 'img_poly_fit', 
           'radial_power_spectrum', 'nrmse', 'errorFienup', 'fienupPhase',
           'roll_anypad','roll_onepad', 'roll_zeropad', 'invert', 'normalize', 
           'logpolar', 'fill_holes', 'selective_gauss_filter',
           'selective_gauss_filter_3D', 'reverse_axis', 'mirror_boundaries', 
           'gaussian_distance_weights', 'find_extrema', 'edge_profile', 'merge']


def rmphaseramp(a, weight=None, return_phaseramp=False):
    """\
    Attempts to remove the phase ramp in a two-dimensional complex array ``a``.
    
    Parameters
    ----------
    a : complex 2D-array
        Input image as complex 2D-array.
        
    weight : {'abs', None}, Defualt=None, optional
        Use 'abs' for weighted phaseramp.
    
    return_phaseramp : {Ture, False}, Defualt=False, optional
        Use Ture to get also the phaseramp array ``p``.
        
        
    Returns
    --------
    a*p : 2D-array
        Modified 2D-array.
    (a*p, p) : tuple
        Modified 2D-array and phaseramp if ``return_phaseramp`` = True.
        
        
    Examples
    --------
    >>> b = rmphaseramp(image)
    >>> b, p = rmphaseramp(image , return_phaseramp=True)
    """

    useweight = True
    if weight is None:
        useweight = False
    elif weight=='abs':
        weight = np.abs(a)

    ph = np.exp(1j*np.angle(a))
    [gx, gy] = np.gradient(ph)
    gx = -np.real(1j*gx/ph)
    gy = -np.real(1j*gy/ph)

    if useweight:
        nrm = weight.sum()
        agx = (gx*weight).sum() / nrm
        agy = (gy*weight).sum() / nrm
    else:
        agx = gx.mean()
        agy = gy.mean()


    (xx,yy) = np.indices(a.shape)
    p = np.exp(-1j*(agx*xx + agy*yy))

    if return_phaseramp:
        return a*p, p
    else:
        return a*p


def _compute_phase_fit(a,pts):
    pts = np.round(np.array(pts)).astype(int)
    x = pts[:,1]
    y = pts[:,0]
    A = np.vstack([np.ones_like(x), x, y]).T
    acf = a[x,y]
    meanphase = np.mean(acf)
    phi = np.angle(acf / meanphase)
    r = np.linalg.lstsq(A, phi)
    ii,jj = np.indices(a.shape)
    phaseramp = r[0][0] + r[0][1]*ii + r[0][2]*jj
    return np.exp(-1j*(phaseramp + np.angle(meanphase)))

def rmphaseramp2(a, pts=None, weight=None, return_phaseramp=False, estimate=False, return_pts=False):
    """\
    Phase ramp removal in a two-dimensional complex array a using a linear fit on
    selected points.
    
    Parameters
    ----------
    a : complex 2D-array
        Input image as complex 2D-array.
    
    pts : ndarray [N,2], optional
        N points with [x,y] coordinates for fit.
        
    weight : {'abs', None}, Defualt=None, optional
        Use 'abs' for weighted phaseramp.
    
    return_phaseramp : {Ture, False}, Defualt=False, optional
        Use Ture to get also the phaseramp array ``p`` back.
        
    estimate : bool, {Ture, False}, optional
        Apply a first rough phaseramp removal with :py:func:`rmphaseramp`
    
    return_pts : bool, {True, False},Defualt=False, optional
        Use True to get also ``pts`` back.
        
    Returns
    --------
    out : tuple
        (out [, finalcorrection, pts])
        
    Examples
    --------
    >>> b = rmphaseramp2(a, pts)
    
    Uses the list of pixel coordinates to fit a linear ramp through the phase part of a.
        
    >>> b = rmphaseramp2(a)
    
    Lets the user select the points on the figure.
    
    >>> b, p = rmphaseramp2(a, ..., return_phaseramp=True)
    
    Also returns the phase ramp array such that b = a*p.
        
    >>> b,pts = rmphaseramp2(a, ..., return_pts=True)
    
    Also returns the points used for the fit.
    """

    if estimate:
        # First apply rough phase ramp removal
        a1, firstcorrection = rmphaseramp(a, weight=weight, return_phaseramp=True)
    else:
        a1 = a
        firstcorrection = np.ones_like(a)

    # Select points interactively if not specified
    if pts is None:
        R = RmphaserampIter(a1)
        R.wait_until_closed()
        pts = R.pts
        corr = R.corr
    else:
        corr = _compute_phase_fit(a1,pts)
        
    finalcorrection = firstcorrection * corr
    
    if not (return_phaseramp or return_pts): return a*finalcorrection
    out = (a*finalcorrection,)
    if return_phaseramp: out = out + (finalcorrection,)
    if return_pts: out = out + (pts,)
    return out
    
class RmphaserampIter(Multiclicks):
    def __init__(self,a):
        self.a = a
        self.corr = np.ones_like(a)
        self.acorr = a * self.corr
        self.ii,self.jj = np.indices(self.a.shape)
        f = mpl.pyplot.figure()
        g = f.add_subplot(1,1,1)
        im = g.imshow(np.angle(a))
        g.set_title('Select points for phase flattening (hit return to finish)')
        Multiclicks.__init__(self, g, True)
        self.im = im
        mpl.pyplot.show()

    def compute_phase_fit(self):
        icorr = _compute_phase_fit(self.acorr,self.pts)
        self.corr *= icorr
        self.acorr *= icorr

    def click(self):
        if len(self.pts) < 2:
            return
        self.compute_phase_fit()
        self.im.set_data(np.angle(self.acorr))


def fgrid(sh,psize=None):
    """\
    Returns Fourier-space coordinates for a N-dimensional array of shape ``sh`` (pixel units).
    
    Parameters
    ----------
    sh : nd-array
        Shape of array.
    
    psize : int, Defualt=None, optional
        Pixel size in each dimensions.
    
    Returns
    --------
    nd-array
        Returns Fourier-space coordinates.
    
    Examples
    --------
    Returns Fourier-space coordinates for a N-dimensional array of shape sh (pixel units)
        >>> import pyE17
        >>> sh = [5,5]
        >>> q0,q1 =  pyE17.utils.fgrid(sh)
        >>> q0
        array([[ 0.,  0.,  0.,  0.,  0.],
               [ 2.,  2.,  2.,  2.,  2.],
               [ 4.,  4.,  4.,  4.,  4.],
               [-4., -4., -4., -4., -4.],
               [-2., -2., -2., -2., -2.]])
        >>> q1
        array([[ 0.,  2.,  4., -4., -2.],
               [ 0.,  2.,  4., -4., -2.],
               [ 0.,  2.,  4., -4., -2.],
               [ 0.,  2.,  4., -4., -2.],
               [ 0.,  2.,  4., -4., -2.]])
    
    Gives the coordinates according to the given pixel size psize.
        >>> q0,q1 =  pyE17.utils.fgrid([3,3],psize=5)
        >>> q0
        array([[ 0.,  0.,  0.],
               [ 5.,  5.,  5.],
               [-5., -5., -5.]])
        >>> q1
        array([[ 0.,  5., -5.],
               [ 0.,  5., -5.],
               [ 0.,  5., -5.]])
    """
    if psize is None:
        return fft.ifftshift(np.indices(sh).astype(float) - np.reshape(np.array(sh)//2,(len(sh),) + len(sh)*(1,)), list(range(1,len(sh)+1)))
    else:
        psize = np.asarray(psize)
        if psize.size == 1:
            psize = psize * np.ones((len(sh),))
        psize = np.asarray(psize).reshape( (len(sh),) + len(sh)*(1,))
        return fft.ifftshift(np.indices(sh).astype(float) - np.reshape(np.array(sh)//2,(len(sh),) + len(sh)*(1,)), list(range(1,len(sh)+1))) * psize

def fvec2(sh, psize=None):
    """\
    Squared norm of reciprocal space coordinates, with pixel size ``psize``.
    
    Parameters
    ----------
    sh : nd-array
        Shape of array.
    
    psize : int, Defualt=None, optional
        Pixel size in each dimensions.
    
    Returns
    --------
    ndarray
        Squared norm of reciprocal space coordinates.
    
    Examples
    --------
    >>> q2 = fvec2(sh, psize):
    
    .. note::
        Uses function :py:func:`fgrid`
    """
    return np.sum(fgrid(sh,psize)**2, axis=0)

def fgrid_2d(sh,psize=None):
    """\
    Old function. Kept for backward compatibility.
    
    .. note::
        Use :py:func:`fgrid` instead.
    """
    return fgrid(sh, psize)

def fvec2_2d(sh, psize=None):
    """\
    Old function. Kept for backward compatibility.
    
    .. note::
        Use :py:func:`fvec2` instead.
    """
    return fvec2(sh, psize)

def lin_fit(a, mask=None,return_error=False):
    #TODO: generalize this routine to N-dimensions (or at least implement 3D)
    """\
    Fits a line (or a plane) to ``a``.
    
    .. note::
        1D fit model: y = a0 + b*x\n
        2D fit model: y = a0 + b[0]*x + b[1]*y\n
        where x is in pixel units. 
    
    Parameters
    ----------
    a : 1D or 2D-numpy-array
        Array with values for fitting.
    
    mask : bool-array, Defualt=None, optional
        Uses in the fit only the elements of ``a`` that have a True mask value (None means use all array). Same shape as ``a``.
    
    return_error : bool, Defualt=None, optional
        If Ture, return also the errors.        
    
    Returns
    --------
    a0 : float
        y-intercept.
    
    b : float
        Slope.
    
    da0 : float, optional
        y-intercept error.
    
    db : float, optional
        Slope error.
    
    Examples
    --------
    >>> import numpy as np
    >>> import pyE17
    >>> a = np.array([2,4,6,5,7,8,9])
    >>> pyE17.utils.lin_fit(a)
    (2.6428571428571423, 1.0714285714285716)
    >>> pyE17.utils.lin_fit(a, return_error=True)
    (2.6428571428571423,
     1.0714285714285716,
     0.79378967038903148,
     0.22015764296317775)        
    >>> b = np.random.rand(6,8)
    >>> pyE17.utils.lin_fit(b, return_error=True)
    (0.55202826345197897,               #random
     array([ 0.02086547, -0.02918989]), #random
     0.45423811569508327,               #random
     array([ 0.11365823,  0.08471585])) #random
    """

    sh = a.shape

    if a.ndim == 1:
        # 1D fit 
        x = np.arange(len(a))
        if mask is not None:
            x = x[mask]
            a = a[mask]

        # Model: y = p(1) + p(2) x
        A = np.vstack([np.ones_like(x), x]).T
        r = np.linalg.lstsq(A, a)
        p = r[0]
        a0 = p[0]
        b = p[1]
        if not return_error:
            return (a0,b)

        mA = np.matrix(A)
        dp = np.sqrt(np.diag(np.linalg.pinv(mA.T*mA) * r[1][0]/2))
        dp2 = dp**2
        da0 = dp[0]
        db = dp[1]

    elif a.ndim == 2:

        # 2D fit
        i0, i1 = np.indices(sh)
        i0f = i0.ravel()
        i1f = i1.ravel()
        af = a.ravel()

        if mask is not None:
            mf = mask.ravel()
            i0f = i0f[mf]
            i1f = i1f[mf]
            af = af[mf]

        # Model = p(1) + p(2) x + p(3) y
        A = np.vstack([np.ones_like(i0f), i0f, i1f]).T
        r = np.linalg.lstsq(A, af)
        p = r[0]
        a0 = p[0]
        b = np.array(p[1:])
        if not return_error:
            return (a0, b)

        mA = np.matrix(A)
        mse = .5*r[1][0]
        dp = np.sqrt(np.diag(np.linalg.pinv(mA.T*mA) * mse))

        da0 = dp[0]
        db = np.array(dp[1:])

    else:
        raise RuntimeError('lin_fit not implemented for higher than 2 dimensions!')

    return (a0, b, da0, db)

def lin_sub(a,mask=None):
    """\
    Fits a line (or a plane) to ``a`` and returns ``a`` minus this fit.
    
    Parameters
    ----------
    a : 1D or 2D-numpy-array
        Array with values for fitting.
    
    mask : bool, Defualt=None, optional
        Uses in the fit only the elements of ``a`` that have a True mask value (None means use all array). Same shape as ``a``.
    
    Returns
    --------
    numpy-array
        ``a`` minus fit.
    
    Examples
    --------
    >>> import numpy as np
    >>> import pyE17
    >>> a = np.array([2,4,6,5,7,8,9])
    >>> pyE17.utils.lin_sub(a)
    array([-0.64285714,  0.28571429,  1.21428571, -0.85714286,  0.07142857,
            0.        , -0.07142857])
    """

    if a.ndim == 1:
        x = np.arange(len(a))
        a0,b = lin_fit(a,mask)
        return a - a0 - b*x
    elif a.ndim == 2:
        i0, i1 = np.indices(a.shape)
        a0, b = lin_fit(a,mask)
        return a - a0 - b[0]*i0 - b[1]*i1               
    else:
        raise RuntimeError('lin_sub not implemented for higher than 2 dimensions!')


def quad_fit(a, mask=None,return_error=False):
    #FIXME: uncertainties calculation is probably not too good - it needs to take into account the whole covariance matrix. 
    #TODO: generalize this routine to N-dimensions (or at least implement 3D)
    """\
    Fits a parabola (or paraboloid) to ``a``.
    
    .. note::
        Fit model: y = c + (x-x0)' * H * (x-x0)\n
        where x is in pixel units. 
    
    Parameters
    ----------
    a : 1D or 2D-numpy-array
        Array with values for fitting.
    
    mask : bool, Defualt=None, optional
        Uses in the fit only the elements of ``a`` that have a True mask value (None means use all array). Same shape as ``a``.
        
    return_error : bool, Defualt=False, optional
        If Ture, return also the errors.
    
    Returns
    --------
    c : float
        The value at the fitted optimum. f(x0)
        
    x0 : float
        The position of the optimum.
        
    h : nd-array
        The hessian matrix (curvature in 1D)
        
    dc : float, optional
        Value error.
        
    dx0 : float, optional
        Position error.
        
    dh : nd-array, optional
        Hessian matrix error.
    
    Examples
    --------
    >>> import numpy as np
    >>> import pyE17
    >>> m = np.array([[4,2,3],[2,0,1],[4,2,3]])
    >>> (c,x0,H) = pyE17.utils.quad_fit(m)
    >>> c
    -0.041666666666672736
    >>> x0
    array([ 1.        ,  1.16666667])
    >>> H
    matrix([[  2.00000000e+00,   2.22044605e-16],
            [  2.22044605e-16,   1.50000000e+00]])
    >>> (c, x0, H, dc, dx0, dH) = pyE17.utils.quad_fit(m, return_error=True)
    """

    sh = a.shape

    if a.ndim == 1:
        # 1D fit 
        x = np.arange(len(a))
        if mask is not None:
            x = x[mask]
            a = a[mask]
    
        # Model: y = p(1) + p(2) x + p(3) x^2
        #          = c + h (x - x0)^2
        A = np.vstack([np.ones_like(x), x, x**2]).T
        r = np.linalg.lstsq(A, a)
        p = r[0]
        c = p[0] - .25*p[1]**2/p[2]
        x0 = -.5*p[1]/p[2]
        h = p[2]
        if not return_error:
            return (c,x0,h)

        mA = np.matrix(A)
        dp = np.sqrt(np.diag(np.linalg.pinv(mA.T*mA) * r[1][0]/2))
        dp2 = dp**2
        dc = np.sqrt( dp2[0] + dp2[1] * .25 * (p[1]/p[2])**2 + dp2[2] * .0625 * (p[1]/p[2])**4 )
        dx0 = np.sqrt( dp2[1] * .25 * (1/p[2])**2 + dp2[2] * .25 * p[1]/p[2]**2 )
        dh = dp[2]
    
    elif a.ndim == 2:
    
        # 2D fit
        i0, i1 = np.indices(sh)
        i0f = i0.flatten()
        i1f = i1.flatten()
        af = a.flatten()
    
        if mask is not None:
            mf = mask.flatten()
            i0f = i0f[mf]
            i1f = i1f[mf]
            af = af[mf]
        
        # Model = p(1) + p(2) x + p(3) y + p(4) x^2 + p(5) y^2 + p(6) xy
        #       = c + (x-x0)' h (x-x0)
        A = np.vstack([np.ones_like(i0f), i0f, i1f, i0f**2, i1f**2, i0f*i1f]).T
        r = np.linalg.lstsq(A, af)
        p = r[0]
        x0 = - (np.matrix([[2*p[3], p[5]],[p[5], 2*p[4]]]).I * np.matrix([p[1],p[2]]).T ).A1
        c = p[0] + .5*(p[1]*x0[0] + p[2]*x0[1])
        h = np.matrix([[p[3], .5*p[5]],[.5*p[5], p[4]]])
        if not return_error:
            return (c,x0,h)

        mA = np.matrix(A)
        mse = .5*r[1][0] 
        dp = np.sqrt(np.diag(np.linalg.pinv(mA.T*mA) * mse))
        
        h1 = p[3]
        h2 = .5*p[5]
        h3 = p[4]
        y1 = p[1]
        y2 = p[2]
        
        Dh1 = dp[3]**2
        Dh2 = .25*dp[5]**2
        Dh3 = dp[4]**2
        Dy1 = dp[1]**2
        Dy2 = dp[2]**2
        deth = h1*h3 - h2**2
        
        dx1dh1 = .5 * ((h3*y1 - h2*y2)*h3/deth) / deth
        dx1dh2 = .5 * (-2*(h3*y1 - h2*y2)*h2/deth + y2) / deth
        dx1dh3 = .5 * ((h3*y1 - h2*y2)*h1/deth - y1) / deth
        dx1dy1 = -.5*h3/deth
        dx1dy2 = .5*h2/deth
    
        dx2dh1 = .5 * ((h1*y2 - h2*y1)*h3/deth - y2) / deth
        dx2dh2 = .5 * (-2*(h1*y2 - h2*y1)*h2/deth + y1) / deth
        dx2dh3 = .5 * ((h1*y2 - h2*y1)*h1/deth) / deth
        dx2dy1 = .5 * h2/deth
        dx2dy2 = -.5 * h1/deth
    
        dcdh1 = .5 * (y1*dx1dh1 + y2*dx2dh1)
        dcdh2 = .5 * (y1*dx1dh2 + y2*dx2dh2)
        dcdh3 = .5 * (y1*dx1dh3 + y2*dx2dh3)
        dcdy1 = .5 * (x0[0] + y1*dx1dy1 + y2*dx2dy1)
        dcdy2 = .5 * (x0[1] + y1*dx1dy2 + y2*dx2dy2)
        
        dx0 = np.array([0, 0])
        dx0[0] = np.sqrt( Dy1*dx1dy1**2 + Dy2*dx1dy2**2 + Dh1*dx1dh1**2 + Dh2*dx1dh2**2 + Dh3*dx1dh3**2 )
        dx0[1] = np.sqrt( Dy1*dx2dy1**2 + Dy2*dx2dy2**2 + Dh1*dx2dh1**2 + Dh2*dx2dh2**2 + Dh3*dx2dh3**2 )
        dc = np.sqrt( dp[0]**2 + Dy1*dcdy1**2 + Dy2*dcdy2**2 + Dh1*dcdh1**2 + Dh2*dcdh2**2 + Dh3*dcdh3**2 )
        dh = np.matrix([[dp[3], .5*dp[5]],[.5*dp[5], dp[4]]])
    
    else:
        raise RuntimeError('quad_fit not implemented for higher than 2 dimensions!')

    return (c, x0, h, dc, dx0, dh)

def img_poly_fit(a, order=1, mask=None):
    """\
    Returns a best fit of a to a 2D polynomial of given order, using only values in the mask.
    
    .. note::
        Pixel units.
    
    Parameters
    ----------
    a : 2D-numpy-array
        Array with values for fitting.
    
    order : int, Defualt=1, optional
        Order of fit polynomial.
    
    mask : bool, Defualt=None, optional
        Uses in the fit only the elements of ``a`` that have a True mask value (None means use all array). Same shape as ``a``.
        
    Returns
    --------
    2D-numpy-array
        Values of fitted polynomial.
    
    Examples
    --------
    >>> import numpy as np
    >>> import pyE17
    >>> m = np.array([[4,2,3],[2,0,1],[4,2,3]])
    >>> pyE17.utils.img_poly_fit(m,order=3)
    array([[  4.00000000e+00,   2.00000000e+00,   3.00000000e+00],
           [  2.00000000e+00,  -6.66133815e-16,   1.00000000e+00],
           [  4.00000000e+00,   2.00000000e+00,   3.00000000e+00]])
    """

    sh = a.shape

    # 2D fit
    i0, i1 = np.indices(sh)
    i0f = i0.ravel()
    i1f = i1.ravel()
    af = a.ravel()
    
    if mask is not None:
        mf = mask.ravel()
        i0f = i0f[mf]
        i1f = i1f[mf]
        af = af[mf]
    

    A = np.vstack([i0f**(i)*i1f**(n-i) for n in range(order+1) for i in range(n+1)]).T    
    r = np.linalg.lstsq(A, af)
    p = r[0]
    if mask is not None:
        i0f = i0.ravel()
        i1f = i1.ravel()
        A = np.vstack([i0f**(i)*i1f**(n-i) for n in range(order+1) for i in range(n+1)]).T    

    return np.dot(A, p).reshape(sh)

def quad_max(a, mask=None, return_hessian=False, warn=True):
    """\
    Fits a parabola (or paraboloid) to ``a``.
    
    .. note::
        Fit model: y = c + (x-x0)' * H * (x-x0)\n
        where x is in pixel units.
        
        All entries are None upon failure. Failure occurs if:
            * A has a positive curvature (it then has a minimum, not a maximum).
            * A has a saddle point
            * the hessian of the fit is singular, that is A is (nearly) flat.
    
    Parameters
    ----------
    a : 1D or 2D-numpy-array
        Array with values for fitting.
    
    mask : bool, Defualt=None, optional
        Uses in the fit only the elements of ``a`` that have a True mask value (None means use all array). Same shape as ``a``. 
        
    return_hessian : bool, Defualt=False, optional
        If Ture, return also the hessian matrix.
    
    warn : bool, Default=Ture, optional
        Print out warnings.
        
    Returns
    --------
    c : float
        The value at the fitted optimum. f(x0)
        
    x0 : float
        The position of the optimum.
        
    h : nd-array, optional
        The hessian matrix (curvature in 1D)
    
    Examples
    --------
    >>> import numpy as np
    >>> import pyE17
    >>> m = np.array([[-4,-2,-3],[-2,0,-1],[-4,-2,-3]])
    >>> (c,x0,H) = pyE17.utils.quad_max(m, return_hessian=True)
    >>> c
    0.041666666666672736
    >>> x0
    array([ 1.        ,  1.16666667])
    >>> H
    matrix([[ -2.00000000e+00,  -2.22044605e-16],
            [ -2.22044605e-16,  -1.50000000e+00]])
    
    See Also
    --------
        :py:func:`quad_fit` : Fits a parabola (or paraboloid) to ``a``.
    """        
    
    (c,x0,h) = quad_fit(a,mask)

    failed = False
    if a.ndim == 1:
        if h > 0:
            if warn: print('Warning: positive curvature!')
            failed = True
    else:
        if h[0,0] > 0:
            if warn: print('Warning: positive curvature along first axis!')
            failed = True
        elif h[1,1] > 0:
            if warn: print('Warning: positive curvature along second axis!')
            failed = True
        elif np.linalg.det(h) < 0:
            if warn: print('Warning: the provided data fits to a saddle!')
            failed = True

    if failed:
        c = None
    
    if return_hessian:
        return c,x0,h
    else:
        return c,x0

def shift_dist(a,b,w=None,return_coeff=True, scale_coeff=True):
    """\
    Computes a windowed distance between ``a`` and ``b`` for all relative
    shifts of ``a`` relative to ``b``. 
    
    More precisely, this relation returns
    
    .. math::
        D(r) = \\sum_{r'} w(r') (a(r') - \\alpha(r) b(r'-r))^2
        
    where :math:`\\alpha` is a complex coefficient that minimizes :math:`D(r)`.
    
    Parameters
    ----------
    a : 2D-numpy-array
        Array to compare with ``b``.
    
    b : 2D-numpy-array
        Array to compare with ``a``. 
        
    w : ndarray, Defualt=None, optional
        ``w`` can also be a tuple of two arrays (wa, wb) which are used to mask
        data from both ``a`` and ``b``.
        
    return_coeff : bool, Default=Ture, optional
        If True returns ``coeff`` :math:`\\alpha`.
    
    scale_coeff : bool, Default=Ture, optional
        Allows only for a phase factor.
        
    Returns
    --------
    cc : 2D-numpy-array
        Similar to a regular cross correlation.
        
    coeff : 2D-numpy-array
        Complex coefficient (:math:`\\alpha`) for minimizing.
        
    
    Examples
    --------
    >>> import pyE17 as e17
    >>> import numpy as np
    >>> import matplotlib.pyplot as pp
    >>> mask = e17.utils.fvec2([200,200])
    >>> mask = np.fft.fftshift(mask)
    >>> limit = 300    
    >>> mask = (mask < limit) * mask
    >>> mask2 = np.roll(mask, 20)       #create a second version of the picture, both shifted and scaled differently
    >>> mask2 = np.roll(mask2,30, axis=0)
    >>> mask2 *= 43
    >>> pp.figure(10)
    <matplotlib.figure.Figure at 0x7f86c2794650>
    >>> pp.imshow(mask)
    <matplotlib.image.AxesImage at 0x7f86c26fb2d0>
    >>> pp.figure(20)
    <matplotlib.figure.Figure at 0x7f86c26fb790>
    >>> pp.imshow(mask2)
    <matplotlib.image.AxesImage at 0x7f86b24d7410>
    >>> distances,alpha = e17.utils.shift_dist(mask, mask2, return_coeff = True)
    >>> pp.figure(30)
    <matplotlib.figure.Figure at 0x7f86b24d78d0>
    >>> pp.imshow(distances)	
    <matplotlib.image.AxesImage at 0x7f86c27373d0>
    >>> pp.figure(31)
    <matplotlib.figure.Figure at 0x7f86c272bd50>
    >>> pp.imshow(np.abs(alpha))
    <matplotlib.image.AxesImage at 0x7f86b23e1090>
    >>> pp.show()
    
    Evaluate:    
    
    >>> argmin = distances.argmin() # 1D index of the minimum distane
    >>> rmin = np.unravel_index(argmin, distances.shape) # The same in 2D coordinates
    >>> print 'The translation vector is ' + str(rmin)
    
    .. note::
        ``w=None`` is equivalent to ``w=1`` and shift_dist returns a result similar to a regular cross correlation.
        ``D = shift_dist(a,b,w,return_coeff=False)`` does not return the coefficient :math:`\\alpha`.
    
        ``w`` can also be a tuple of two arrays (wa, wb) which are used to mask
        data from both ``a`` and ``b``, and D is then given by
        
        .. math::
            D(r) = \\sum_{r'} wa(r') wb(r'-r) (a(r') - \\alpha(r) b(r'-r))^2
    
        ... = shift_dist(a,b,w,scale_coeff=False) allows only for a phase factor
        ( :math:`\\alpha = 1` ).
    
        :math:`D(r)` is non-negative everywhere. It is zero only if :math:`a(r') = b(r'-r)`
        up to a propotionality constant (:math:`\\alpha`) 

    See Also
    --------
        shift_best : also giving 'sub-pixel precision'
    """
    if w is None:
        a2 = norm2(a)
        b2 = norm2(b)
        cab = fft.ifftn(fft.fftn(a) * np.conj(fft.fftn(b)))
        if not scale_coeff:
            coeff = np.exp(1j * np.angle(cab))
            cc = a2 + b2 - 2*np.abs(cab)
        else:
            coeff = cab / b2
            cc = a2 - b2 * abs2(coeff)
        if return_coeff:
            return cc,coeff
        else:
            return cc
    else:
        if len(w) == 2:
            # We have a tuple : two masks
            w,wb = w
            first_term = np.real(fft.ifftn(fft.fftn(w*abs2(a)) * np.conj(fft.fftn(wb))))
            b *= wb
        else:
            first_term = np.sum(w*abs2(a))
        #w = w.astype(float)
        fw = fft.fftn(w)
        fwa = fft.fftn(w * a)
        fb2 = fft.fftn(abs(b)**2)
        fb = fft.fftn(b)
        epsilon = 1e-10
        if not scale_coeff:
            coeff = np.exp(1j * np.angle( fft.ifftn(fwa * np.conj(fb)) ))
            cc = first_term + np.real(fft.ifftn(fw * np.conj(fb2))) - 2*np.abs(fft.ifftn(fwa * np.conj(fb)))
        else:
            coeff = fft.ifftn(fwa * np.conj(fb)) / (fft.ifftn(fw * np.conj(fb2)) + epsilon)
            cc = first_term - abs2(fft.ifftn(fwa * np.conj(fb)))/(fft.ifftn(fw * np.conj(fb2)) + epsilon)
        if return_coeff:
            return cc,coeff
        else:
            return cc

def shift_best(a,b,w=None,max_shift=None,return_params=True, numiter=1, also_return_null_shift = False, scale_coeff=True, warn=False):
    """\
    Shifts and rescales ``b`` so that it best overlaps with ``a``.
    
    .. note::
        See :py:func:`shift_dist` for more documentation.

        If no improved minimum is found, a Null vector is return instead of ``b``.
    
    Parameters
    ----------
    a : 2D-numpy-array
        Array to compare with ``b``.
    
    b : 2D-numpy-array
        Array to compare with ``a``. 
        
    w : ndarray, Defualt=None, optional
        ``w`` can also be a tuple of two arrays (wa, wb) which are used to mask
        data from both ``a`` and ``b``.
    
    max_shift : int, Default=None, optional
        The maximum allowed shift distance (in pixel units). 
    
    return_params : bool, Default=True, optional
        If True, returns only the shifted version of b.
    
    numiter : int, Default=1, optional
        Number of used iterations.
    
    also_return_null_shift : 
        Will enforce that a vector is returned, even if no minimum was found.
        ``b`` is then unchanged.
    
    scale_coeff : bool, Default=Ture, optional
        Allows only for a phase factor.
        
    warn : bool, Default=False, optional
        If Ture, return warnings.
        
    Returns
    --------
    b : 2D-numpy-array
        Similar to a regular cross correlation.
        
    r0 : numpy-array, optional
        Translation vector.
        
    alpha0 : 2D-numpy-array
        Complex coefficient (:math:`\\alpha`) for minimizing.
    
    Examples
    --------
    >>> import pyE17 as e17
    >>> import numpy as np
    >>> import matplotlib.pyplot as pp
    >>> mask = e17.utils.fvec2([200,200])
    >>> mask = np.fft.fftshift(mask)
    >>> limit = 300    
    >>> mask = (mask < limit) * mask
    >>> mask2 = np.roll(mask, 20)       #create a second version of the picture, both shifted and scaled differently
    >>> mask2 = np.roll(mask2,30, axis=0)
    >>> mask2 *= 43
    >>> distances,r,alpha = e17.utils.shift_best(mask, mask2, return_params = True)
    >>> print 'The optimal translation vector is ' + str(r)
    >>> print "and the mutliplication factor is " + str(np.real(alpha))
    >>> print 'note the sign convention (170 = 200 - 30) and the scaling factor (0.0232558 = 1/43.)'
    """
    
    QUAD_MAX_HW = 1
    QUAD_MAX_W = 2*QUAD_MAX_HW + 1

    sh = a.shape
    assert b.shape == sh

    ismatrix = isinstance(b,np.matrix)
    if ismatrix:
        a = np.asarray(a)
        b = np.asarray(b)

    ndim = a.ndim
    fake_1D = False
    if ndim==2 and 1 in sh:
        fake_1D = True
        a = a.ravel()
        b = b.ravel()
        sh_1D = sh
        sh = a.shape
        ndim = 1

    r0 = np.zeros((ndim,))

    qmaxslice = tuple([slice(0,QUAD_MAX_W) for dummy in range(ndim)])

    alpha0 = 1.
    for ii in range(numiter):
        # Compute distance
        cc = shift_dist(a,b,w,scale_coeff=scale_coeff)[0]

        if max_shift is not None:
            # Find minimum
            cc1 = cc.copy()
            if np.isscalar(max_shift):
                too_far_mask = (fvec2(sh) > max_shift**2)
            else:
                fg = fgrid(sh)
                too_far_mask = np.zeros(sh,dtype=bool)
                for idim in ndim:
                    too_far_mask += (abs(fg[idim]) > max_shift[idim]/2.)
            cc1[too_far_mask] = np.inf
            cmax = np.array(np.unravel_index(cc1.argmin(),sh))
            # sub-pixel center
            #cc_part = pshift(-np.real(cc1), cmax - QUAD_MAX_HW)[0:QUAD_MAX_W,0:QUAD_MAX_W]
            cc_part = pshift(-np.real(cc1), cmax - QUAD_MAX_HW)[qmaxslice]
            if np.any(np.isinf(cc_part)):
                warnings.warn("Failed to find a local minimum in shift_best.", RuntimeWarning)
                if also_return_null_shift is False:
                    return None
        else:
            # Find minimum
            cmax = np.array(np.unravel_index(cc.argmin(),sh))

        # sub-pixel center
        ccloc = pshift(-np.real(cc), cmax - QUAD_MAX_HW)[qmaxslice]
        mindist, r = quad_max(ccloc, warn=warn)
        if mindist is None:
            # mindist is None if the quadratic fit did give a local minimum.
            # Poor man's solution: re-run in 1D.
            mindist_d0, r_d0 = quad_max(ccloc[:,1], warn=warn)
            mindist_d1, r_d1 = quad_max(ccloc[1,:], warn=warn)
            if (mindist_d0 is None) or (mindist_d1 is None):
                # This should never happen if we are minimizing on a 3x3 array.
                raise RuntimeError('Could not find a local minimum!')
            else:
                mindist = min(mindist_d0, mindist_d1)
                r = np.array([r_d0,r_d1])
        r -= (QUAD_MAX_HW - cmax)

        # shift the array
        bshift = pshift(b,-r)

        # evaluate the coefficient for sub-pixel shift
        alpha = (a*np.conj(bshift)).sum()/norm2(bshift)
        if not scale_coeff:
            alpha = np.exp(1j * np.angle(alpha))

        # New b
        b = alpha*bshift
        alpha0 *= alpha
        r0 += r

    if fake_1D:
        b.resize(sh_1D)
    if ismatrix:
        b = np.asmatrix(b)

    # Store the optimum as an attribute in case it is useful
    shift_best.mindist = -mindist if mindist is not None else np.real(cc).min()

    if return_params:
        return b, -r0, alpha0
    else:
        return b


def shift_vector_nD(a, b, is_subpx = True, fit_radius = 2, is_return_sigma = False):
    """\
Calculates the n-dimensional vector by which two n-dimensional images are shifted.

Parameters
----------
a : array_like
    Input image a, n-dimensional 

b : array_like
    Input image b, n-dimensional 

is_subpx : boolean, optional    
    If True, a Gauss Fit is applied to provide subpixel accuracy
    If False, non subpixel accuracy
    Default is True

fit_radius : int, optional
    Determines the radius of the Gauss fit
    Default is 2
    
is_return_sigma : boolean, optional
    If True, sigma is returned in addition to the shift
    Default is False


Returns
-------
shift : ndarray
    n-dimensional array with components of shift vector in each coordinate 
    
If is_return_sigma is True (not by default):
shift_sigma : ndarray
    n-dimensional array with corresponding fit errors


See Also
--------
shift_best
shift_dist


Notes
-----
Author / support: Andreas.Fehringer@ph.tum.de


Examples
--------
>>> import pyE17 as e17
>>> shift = e17.utils.shift_best_nD(a, b)
"""   
   
    
    if a.ndim != b.ndim:
        raise ValueError('a and b must have the same number of dimensions')
    ndim = a.ndim
    
    # calculate the cross-correlation of the images a and b
    ccorr = np.fft.fftshift(np.fft.ifftn(np.fft.fftn(a) * np.conj(np.fft.fftn(b)))).real
        # fftshift shifts odd shapes by floor(shape * .5)
        # that's the reason for the integer devision below
    
    # coordinate of the maximum cross-correlation relative to the origin
    max_index = np.unravel_index(ccorr.argmax(), ccorr.shape)
    
    if not is_subpx:
        return max_index - np.array(ccorr.shape, dtype=np.int) // 2
    

    # n-dimensional gauss function for fitting
    def gauss(x, a, t, *b_and_s_params):
        # a * exp(b * (x-s)**2) + t    
        ndim = len(b_and_s_params) / 2
        b = b_and_s_params[:ndim]
        s = b_and_s_params[ndim:]
        value = 0. #np.zeros([ np.array(x[d]).size for d in range(ndim) ])
        for d in range(ndim):
            value += (b[d] * (np.array(x[d])-s[d])**2) #.reshape([ 1 if i != d else -1  for i in range(ndim) ])
        return a * np.squeeze(np.exp(value)) + t
    
    # alternative function for fitting, not used at the moment
    def paraboloid(x, a, b, e, sx, sy):
        return a * (x[0]-sx)**2 + b * (x[1]-sy)**2 + e
    
    # alternative function for fitting, not used at the moment
    def paraboloid_simple(x, a, b, c, d, e, f):
        return a * x[0]**2 + b * x[1]**2 + c * x[0] * x[1] + d * x[0] + e * x[1] + f    
    

    # neighbourhood of max_index with size of fit_radius
    coordinates = [ np.arange(i - fit_radius, i + fit_radius + 1, dtype=float) for i in max_index ]
    
    # coordinate matrices from coordinates for evaluation of gauss fit
    mesh = np.array(np.meshgrid(*coordinates[::-1])).reshape((ndim, -1))[::-1].astype(np.float64)
    
    # cut fit area out of ccorr
    zdata = ccorr
    for i in range(ndim):
        # roll zdata so that max_index is in the very center
        # otherwise the fit radius can go outside the array borders
        zdata = np.roll(zdata, zdata.shape[i] / 2 - max_index[i], axis = i)
    zdata_slices = [
        slice(zdata.shape[i] / 2 - fit_radius, zdata.shape[i] / 2 + fit_radius + 1)
        for i in range(ndim)
    ]
    zdata = zdata[zdata_slices].astype(np.float64)
    z_max = zdata.max()
    zdata /= z_max
    
    # start values for curve_fit parameters
    # i.e. Gauss height, y offset, width for all dimensions, x offset for all dimensions
    pstart = [1., z_max] + [-1.] * ndim + np.array(max_index, dtype = np.float).tolist()
    
    # fit
    popt, pcov = curve_fit(gauss, mesh, zdata.reshape(-1), pstart)
    if not np.isfinite(pcov).all():
        raise RuntimeError('Subpixel fit did not converge. Maybe try different fit radius.')
    
    shift_sub = popt[-ndim:] - np.array(ccorr.shape, dtype=np.int) // 2
    
    if is_return_sigma: 
        sigma = np.sqrt(np.diag(pcov))
        return shift_sub, sigma
    
    return shift_sub




def norm2(a):
    """\
    Squared array norm.
    
    Parameters
    ----------
    a : nd-array
        Input array.     
    
    Returns
    -------
    float
        Squared norm of array ``a``. 
        
    See Also
    --------
    norm
    
    Examples
    --------
    >>> import pyE17
    >>> m=pyE17.utils.fvec2([5,5])
    >>> pyE17.utils.norm2(m)
    540.0
    """
    return float(np.real(np.vdot(a.ravel(),a.ravel())))

def norm(a):
    """\
    Array norm.
        
    Parameters
    ----------
    a : nd-array
        Input array.     
    
    Returns
    -------
    float
        Norm of array ``a``. 
        
    See Also
    --------
    norm2
    
    Examples
    --------
    >>> import pyE17
    >>> m=pyE17.utils.fvec2([5,5])
    >>> pyE17.utils.norm(m)
    23.2379000772445
    """
    return np.sqrt(norm2(a))

def abs2(a):
    """\
    Absolute squared.
        
    Parameters
    ----------
    a : nd-array
        Input array.     
    
    Returns
    -------
    nd-array
        Absolute squared of ``a``. 
          
    Examples
    --------
    >>> import pyE17
    >>> m = [2,-4,3]
    >>> pyE17.utils.abs2(m)
    array([ 4, 16,  9])
    """
    return np.abs(a)**2

#EVEN OLDER VERSION KEPT FOR NOW FOR DOCUMENTATION
#def pshift(a, ctr, tolerance=.01):
#    """\
#    Shift an array periodically so that ctr becomes the origin.
#    
#    sub-pixel shifts are done in Fourier space, possibly giving rise to aliasing
#    """
#    sh = np.array(a.shape)
#    ctr = np.array(ctr) % sh
#
#    ctri = np.round(ctr).astype(int)
#    ctrd = ctr-ctri
#
#    if np.all(np.abs(ctrd)<tolerance) and a.ndim < 4:  
#        # Non-Fourier method for ndim <= 3 and integral shifts.
#        out = np.empty_like(a)
#        c2 = sh - ctri
#        if out.ndim == 1:
#            out[0:c2[0]] = a[ctri[0]:]
#            out[c2[0]:] = a[0:ctri[0]]
#    
#        elif out.ndim == 2:
#            out[0:c2[0], 0:c2[1]] = a[ctri[0]:, ctri[1]:]
#            out[0:c2[0], c2[1]:] = a[ctri[0]:, 0:ctri[1]]
#            out[c2[0]:, 0:c2[1]] = a[0:ctri[0], ctri[1]:]
#            out[c2[0]:, c2[1]:] = a[0:ctri[0], 0:ctri[1]]
#        else:
#            out[0:c2[0], 0:c2[1], 0:c2[2]] = a[ctri[0]:, ctri[1]:, ctri[2]:]
#            out[c2[0]:, 0:c2[1], 0:c2[2]] = a[0:ctri[0], ctri[1]:, ctri[2]:]
#            out[0:c2[0], c2[1]:, 0:c2[2]] = a[ctri[0]:, 0:ctri[1], ctri[2]:]
#            out[c2[0]:, c2[1]:, 0:c2[2]] = a[0:ctri[0], 0:ctri[1], ctri[2]:]
#            out[0:c2[0], 0:c2[1], c2[2]:] = a[ctri[0]:, ctri[1]:, 0:ctri[2]]
#            out[c2[0]:, 0:c2[1], c2[2]:] = a[0:ctri[0], ctri[1]:, 0:ctri[2]]
#            out[0:c2[0], c2[1]:, c2[2]:] = a[ctri[0]:, 0:ctri[1], 0:ctri[2]]
#            out[c2[0]:, c2[1]:, c2[2]:] = a[0:ctri[0], 0:ctri[1], 0:ctri[2]]
#    else:
#        # Sub-pixel shift
#        fout = np.fft.fftn(a.astype(complex))
#        out = np.fft.ifftn(fout * np.exp(2j * np.pi * np.sum(fgrid(sh,ctr/sh),axis=0)))
#
#    #return out.astype(a.dtype)
#    return out

#OLD VERSION KEPT FOR NOW FOR DOCUMENTATION
#def pshift(a, ctr, method='linear'):
#    """\
#    Shift an periodically array so that ctr becomes the origin.
#    
#    Available methods are 'fourier', 'nearest' and 'linear'. Fourier used to be the default
#    but it produced artifacts at strong edges.
#    """
#    sh = np.array(a.shape)
#    ctr = np.asarray(ctr) % sh
#
#    if method.lower() == 'nearest':
#        ctri = np.round(ctr).astype(int)
#        out = np.empty_like(a)
#        c2 = sh - ctri
#        if out.ndim == 1:
#            out[0:c2[0]] = a[ctri[0]:]
#            out[c2[0]:] = a[0:ctri[0]]
#    
#        elif out.ndim == 2:
#            out[0:c2[0], 0:c2[1]] = a[ctri[0]:, ctri[1]:]
#            out[0:c2[0], c2[1]:] = a[ctri[0]:, 0:ctri[1]]
#            out[c2[0]:, 0:c2[1]] = a[0:ctri[0], ctri[1]:]
#            out[c2[0]:, c2[1]:] = a[0:ctri[0], 0:ctri[1]]
#        else:
#            out[0:c2[0], 0:c2[1], 0:c2[2]] = a[ctri[0]:, ctri[1]:, ctri[2]:]
#            out[c2[0]:, 0:c2[1], 0:c2[2]] = a[0:ctri[0], ctri[1]:, ctri[2]:]
#            out[0:c2[0], c2[1]:, 0:c2[2]] = a[ctri[0]:, 0:ctri[1], ctri[2]:]
#            out[c2[0]:, c2[1]:, 0:c2[2]] = a[0:ctri[0], 0:ctri[1], ctri[2]:]
#            out[0:c2[0], 0:c2[1], c2[2]:] = a[ctri[0]:, ctri[1]:, 0:ctri[2]]
#            out[c2[0]:, 0:c2[1], c2[2]:] = a[0:ctri[0], ctri[1]:, 0:ctri[2]]
#            out[0:c2[0], c2[1]:, c2[2]:] = a[ctri[0]:, 0:ctri[1], 0:ctri[2]]
#            out[c2[0]:, c2[1]:, c2[2]:] = a[0:ctri[0], 0:ctri[1], 0:ctri[2]]
#
#    elif method.lower() == 'fourier':
#        fout = np.fft.fftn(a.astype(complex))
#        out = np.fft.ifftn(fout * np.exp(2j * np.pi * np.sum(fgrid(sh,ctr/sh),axis=0)))
#
#    elif method.lower() == 'linear':
#        ctri = np.floor(ctr).astype(int)
#        if a.ndim == 1:
#            x = ctr-ctri
#            a0 = pshift(a,ctri, method='nearest')
#            a1 = pshift(a,ctri + 1, method='nearest')
#            out = a0*(1-x) + a1*x
#        elif a.ndim == 2:   
#            x,y = ctr-ctri
#            a00 = pshift(a,ctri, method='nearest')
#            a01 = pshift(a,ctri + [0, 1], method='nearest')
#            a10 = pshift(a,ctri + [1, 0], method='nearest')
#            a11 = pshift(a,ctri + [1, 1], method='nearest')
#            out = a00*(1-x)*(1-y) + a01*(1-x)*y + a10*x*(1-y) + a11*x*y
#
#    return out

def pshift(a, ctr, method='linear', fill=None):
    """\
    Shift a multidimensional array so that ``ctr`` becomes the origin.
    
    Parameters
    ----------
    a : nd-array
        Input array.
        
    ctr : array
        Position of new origin.
    
    method : str={'linear', 'nearest', 'fourier'}, Default='linear', optional
        Shift method.
        
    fill : bool, Default=None, optional
        If fill is None, the shifted image is rolled periodically.
    
    .. note::
        Fourier used to be the default but it produced artifacts at strong edges.
    
    Returns
    -------
    out : nd-array
        Shiftet array. 
          
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> m = np.array([i for i in range(9)]).reshape(3,3)
    >>> m
    array([[0, 1, 2],
           [3, 4, 5],
           [6, 7, 8]])
    >>> pyE17.utils.pshift(m,[1,2], method='linear')
    array([[5, 3, 4],
           [8, 6, 7],
           [2, 0, 1]])
    >>> pyE17.utils.pshift(m,[1,2], method='linear', fill=True)
    array([[5, 1, 1],
           [8, 1, 1],
           [1, 1, 1]])
    """
    sh  = np.array(a.shape)
    out = np.empty_like(a)

    if method.lower() == 'nearest':
        ctri  = np.round(ctr).astype(int)
        ctri2 = -ctri % sh  # force swap shift direction and force shift indices to be positive

        if fill is not None:
            # the filling case
            if (np.abs(ctri) > sh).any():
                return out             # shift is out of volume
            out.fill(fill)
            ctri2 -= sh * (ctri == 0)  # restore the sign of the shift index
        
        # walk through all (but the first) combinations of 0 and 1 on a length of a.ndim,
        # which are all possible copies of the original image in the output:
        #   0 is the first possible copy of the image in one dimension
        #   1 the second one
        comb_num = 2**a.ndim
        for comb_i in range(comb_num):
            comb = np.asarray(tuple(("{0:0" + str(a.ndim) + "b}").format(comb_i)), dtype=int)

            ctri3 = ctri2 - sh * comb
            out[ [slice(None,  s) if s >  0 else slice(s,  None) for s in ctri3] ] = \
              a[ [slice(-s, None) if s >= 0 else slice(None, -s) for s in ctri3] ]
            
            if fill is not None:
                break  # only the first copy of the image wanted

    elif method.lower() == 'linear':
        ctri = np.floor(ctr).astype(int)
        ctrx = np.empty((2, a.ndim))
        ctrx[1,:] = ctr - ctri     # second weight factor
        ctrx[0,:] = 1 - ctrx[1,:]  # first  weight factor
        out.fill(0.)
        
        # walk through all combinations of 0 and 1 on a length of a.ndim:
        #   0 is the shift with shift index floor(ctr[d]) for a dimension d
        #   1 the one for floor(ctr[d]) + 1
        comb_num = 2**a.ndim
        for comb_i in range(comb_num):
            comb = np.asarray(tuple(("{0:0" + str(a.ndim) + "b}").format(comb_i)), dtype=int)
            
            # add the weighted contribution for the shift corresponding to this combination
            out += pshift(a, ctri + comb, method='nearest', fill=fill) * ctrx[comb,list(range(a.ndim))].prod()

    elif method.lower() == 'fourier':
        fout = np.fft.fftn(a.astype(complex))
        out = np.fft.ifftn(fout * np.exp(2j * np.pi * np.sum(fgrid(sh,ctr/sh),axis=0)))

    return out




def delxf(a, axis = -1, out = None):
    """\
    Forward first order derivative for finite difference calculation.
    
    .. note::
        The last element along the derivative direction is set to 0.\n
        Pixel units are used (:math:`\\Delta x = \\Delta h = 1`).
    
    Parameters
    ----------
    a : nd-numpy-array
        Input array.
        
    axis : int, Default=-1, optional
        Which direction used for the derivative.
    
    out : nd-array, Default=None, optional
        Array in wich the resault is written (same size as ``a``).
    
    Returns
    -------
    out : nd-numpy-array
        Derived array.
          
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> import matplotlib.pyplot as plt
    >>> s = np.array([i**3 for i in range(-100,100)])
    >>> ds = pyE17.utils.delxf(s)
    >>> plt.plot(s)
    >>> plt.plot(ds)
    >>> plt.show()
    
    See Also
    --------
    delxb : Backward first order derivative.
    delxc : Central first order derivative.
    delxpb : Forward first order derivative (PBC).
    delxpb : Backward first order derivative (PBC).
    delxpc : Central first order derivative (PBC).
    """
    nd   = len(a.shape)
    axis = list(range(nd))[axis]
    
    slice1 = [ slice(1,  None) if i == axis else slice(None) for i in range(nd) ]
    slice2 = [ slice(None, -1) if i == axis else slice(None) for i in range(nd) ]
    
    if out == None:  out = np.empty_like(a)
    
    # compute difference
    if a is out:  # in-place
        out *= -1.
        out[slice2] -= out[slice1]
    else:
        out[slice2] = a[slice1] - a[slice2]
    
    # set last row to 0
    slice3 = [ slice(-1, None) if i == axis else slice(None) for i in range(nd) ]
    out[slice3] = 0.
    
    return out

def delxb(a,axis=-1):
    """\
    Backward first order derivative for finite difference calculation.

    .. note::
        The first element along the derivative direction is set to 0.\n
        Pixel units are used (:math:`\\Delta x = \\Delta h = 1`).
    
    Parameters
    ----------
    a : nd-numpy-array
        Input array.
        
    axis : int, Default=-1, optional
        Which direction used for the derivative.
    
    Returns
    -------
    out : nd-numpy-array
        Derived array.
          
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> import matplotlib.pyplot as plt
    >>> s = np.array([i**3 for i in range(-100,100)])
    >>> ds = pyE17.utils.delxb(s)
    >>> plt.plot(s)
    >>> plt.plot(ds)
    >>> plt.show()
    
    See Also
    --------
    delxf : Forward first order derivative.
    delxc : Central first order derivative.
    delxpb : Forward first order derivative (PBC).
    delxpb : Backward first order derivative (PBC).
    delxpc : Central first order derivative (PBC).
    """

    nd = len(a.shape)
    axis = list(range(nd))[axis]
    slice1 = [slice(1,None) if i==axis else slice(None) for i in range(nd)]
    slice2 = [slice(None,-1) if i==axis else slice(None) for i in range(nd)]
    b = np.zeros_like(a)
    b[slice1] = a[slice1] - a[slice2]
    return b

def delxc(a,axis=-1):
    """\
    Central first order derivative for finite difference calculation.
    
    .. note::
        Forward and backward derivatives are used for first and last 
        elements along the derivative direction.\n
        Pixel units are used (:math:`\\Delta x = \\Delta h = 1`).
    
    Parameters
    ----------
    a : nd-numpy-array
        Input array.
        
    axis : int, Default=-1, optional
        Which direction used for the derivative.
    
    Returns
    -------
    out : nd-numpy-array
        Derived array.
          
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> import matplotlib.pyplot as plt
    >>> s = np.array([i**3 for i in range(-100,100)])
    >>> ds = pyE17.utils.delxc(s)
    >>> plt.plot(s)
    >>> plt.plot(ds)
    >>> plt.show()
    
    See Also
    --------
    delxf : Forward first order derivative.
    delxb : Backward first order derivative.
    delxpb : Forward first order derivative (PBC).
    delxpb : Backward first order derivative (PBC).
    delxpc : Central first order derivative (PBC).
    """
    nd = len(a.shape)
    axis = list(range(nd))[axis]
    slice_middle = [slice(1,-1) if i==axis else slice(None) for i in range(nd)]
    b = delxf(a,axis) + delxb(a,axis)
    b[slice_middle] *= .5
    return b

def del2(a,axis=None,out=None):
    """\
    N-dimensional discrete laplacian :math:`\Delta`.
    
    .. note::
        Pixel units are used (:math:`\\delta x = \\delta h = 1`).
    
    Parameters
    ----------
    a : nd-numpy-array
        Input array.
        
    axis : int, Default=-1, optional
        The laplacian is computed along the provided axis or list of axes, or all axes if None
    
    out : nd-array, Default=None, optional
        Array in wich the resault is written (same size as ``a``).
    
    Returns
    -------
    out : nd-numpy-array
        Derived array.
          
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> import matplotlib.pyplot as plt
    >>> s = np.array([i**3 for i in range(-100,100)])
    >>> ds = pyE17.utils.del2(s)
    >>> plt.plot(ds)
    [<matplotlib.lines.Line2D object at 0x7fb931ccc6d0>]
    >>> plt.show()
    
    See Also
    --------
    del2p : N-dimensional discrete laplacian (PBC).
    """
    nd = len(a.shape)
    if axis is None:
        axis = list(range(nd))
    else:
        try:
            axis = [axis+0]
        except TypeError:
            pass

    if out is None:  out = np.empty_like(a)
    elif a is out:  # reference comparison (did not find an in-place solution)
        raise ValueError("Parameter a must differ from out. In-place operation is not supported.")
        

    is_first_axis = True
    for ia in axis:
        #out += delxf(a,axis=ia)  # memory and time consuming
        #out -= delxb(a,axis=ia)

        # b = a[n-1] - 2 a[n] + a[n+1]
        slice_l = [slice(None,-2) if i==ia else slice(None) for i in range(nd)]
        slice_c = [slice(1,   -1) if i==ia else slice(None) for i in range(nd)]
        slice_r = [slice(2, None) if i==ia else slice(None) for i in range(nd)]
        slice_0 = [ 0             if i==ia else slice(None) for i in range(nd)]
        slice_e = [-1             if i==ia else slice(None) for i in range(nd)]
        
        # optimized for memory usage and speed:
        if is_first_axis:
            out[slice_c]  = a[slice_c]
            out[slice_c] *= -2.
            is_first_axis = False
        else:  
            out[slice_c] += -2. * a[slice_c]
        out[slice_c] += a[slice_l]
        out[slice_c] += a[slice_r]
        out[slice_0]  = 0.
        out[slice_e]  = 0.

    return out

def delxpf(a,axis=-1):
    """\
    Forward first order derivative for finite difference calculation.
    Periodic boundary conditions (PBC).
    
    .. note::
        Pixel units are used (:math:`\\Delta x = \\Delta h = 1`).
    
    Parameters
    ----------
    a : nd-numpy-array
        Input array.
        
    axis : int, Default=-1, optional
        Which direction used for the derivative.
    
    Returns
    -------
    b : nd-numpy-array
        Derived array.
          
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> s = np.array([i**3 for i in range(-100,100)])
    >>> ds = pyE17.utils.delxpf(s)
    
    See Also
    --------
    delxf : Forward first order derivative.
    delxb : Backward first order derivative.
    delxc : Central first order derivative.
    delxpb : Backward first order derivative (PBC).
    delxpc : Central first order derivative (PBC).
    """
    nd = len(a.shape)
    axis = list(range(nd))[axis]
    slice1 = [slice(1,None) if i==axis else slice(None) for i in range(nd)]
    slice2 = [slice(None,-1) if i==axis else slice(None) for i in range(nd)]
    b = -a.copy()
    b[slice2] += a[slice1]
    slice1[axis] = 0
    slice2[axis] = -1
    b[slice2] += a[slice1]
    return b

def delxpb(a,axis=-1):
    """\
    Backward first order derivative for finite difference calculation.
    Perodic boundary conditions (PBC).
    
    .. note::
        Pixel units are used (:math:`\\Delta x = \\Delta h = 1`).
    
    Parameters
    ----------
    a : nd-numpy-array
        Input array.
        
    axis : int, Default=-1, optional
        Which direction used for the derivative.
    
    Returns
    -------
    b : nd-numpy-array
        Derived array.
          
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> s = np.array([i**3 for i in range(-100,100)])
    >>> ds = pyE17.utils.delxpb(s)
    
    See Also
    --------
    delxf : Forward first order derivative.
    delxb : Backward first order derivative.
    delxc : Central first order derivative.
    delxpf : Forward first order derivative (PBC).
    delxpc : Central first order derivative (PBC).
    """
    nd = len(a.shape)
    axis = list(range(nd))[axis]
    slice1 = [slice(1,None) if i==axis else slice(None) for i in range(nd)]
    slice2 = [slice(None,-1) if i==axis else slice(None) for i in range(nd)]
    b = a.copy()
    b[slice1] -= a[slice2]
    slice1[axis] = 0
    slice2[axis] = -1
    b[slice1] -= a[slice2]
    return b

def delxpc(a,axis=-1):
    """\
    Central first order derivative for finite difference calculation.
    Periodic boundary conditions (PBC).
    
    .. note::
        Pixel units are used (:math:`\\Delta x = \\Delta h = 1`).
    
    Parameters
    ----------
    a : nd-numpy-array
        Input array.
        
    axis : int, Default=-1, optional
        Which direction used for the derivative.
    
    Returns
    -------
    b : nd-numpy-array
        Derived array.
          
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> s = np.array([i**3 for i in range(-100,100)])
    >>> ds = pyE17.utils.delxpc(s)
    
    See Also
    --------
    delxf : Forward first order derivative.
    delxb : Backward first order derivative.
    delxc : Central first order derivative.
    delxpf : Forward first order derivative (PBC).
    delxpb : Backward first order derivative (PBC).
    """
    b = .5*(delxpf(a,axis) + delxpb(a,axis))
    return b

def del2p(a,axis=None):
    """\
    N-dimensional discrete laplacian.
    Perdiodic boundary conditions (PBC).
    
    .. note::
        Pixel units are used (:math:`\\delta x = \\delta h = 1`).
    
    Parameters
    ----------
    a : nd-numpy-array
        Input array.
        
    axis : int, Default=-1, optional
        The laplacian is computed along the provided axis or list of axes, or all axes if None
    
    Returns
    -------
    out : nd-numpy-array
        Derived array.
          
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> import matplotlib.pyplot as plt
    >>> s = np.array([i**3 for i in range(-100,100)])
    >>> ds = pyE17.utils.del2p(s)
    >>> plt.plot(ds)
    >>> plt.show()
    
    See Also
    --------
    del2 : N-dimensional discrete laplacian.
    """
    nd = len(a.shape)
    if axis is None:
        axis = list(range(nd))
    else:
        try:
            axis = [axis+0]
        except TypeError:
            pass
    b = np.zeros_like(a)
    for ia in axis:
        b += delxpf(a,axis=ia)
        b -= delxpb(a,axis=ia)
    return b

#### added by Guillaume ########

def rebin_old(a, *args):
    '''\
    Rebin ndarray data into a smaller ndarray of the same rank whose dimensions
    are factors of the original dimensions.
    
    .. note::
        eg. An array with 6 columns and 4 rows
        can be reduced to have 6,3,2 or 1 columns and 4,2 or 1 rows.
    
    Parameters
    ----------
    a : nd-numpy-array
        Input array.
        
    axis : int, Default=-1, optional
        The laplacian is computed along the provided axis or list of axes, or all axes if None
    
    Returns
    -------
    out : nd-numpy-array
        Rebined array.
          
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> a=np.random.rand(6,4) 
    >>> b=pyE17.utils.rebin(a,3,2)
    a.reshape(args[0],factor[0],args[1],factor[1],).sum(1).sum(2)*( 1./factor[0]/factor[1])
    >>> a2=np.random.rand(6)
    >>> b2=pyE17.utils.rebin(a2,2)
    a.reshape(args[0],factor[0],).sum(1)*( 1./factor[0])
    '''
    shape = a.shape
    lenShape = a.ndim
    factor = np.asarray(shape)/np.asarray(args)
    evList = ['a.reshape('] + \
             ['args[%d],factor[%d],'%(i,i) for i in range(lenShape)] + \
             [')'] + ['.sum(%d)'%(i+1) for i in range(lenShape)] + \
             ['*( 1.'] + ['/factor[%d]'%i for i in range(lenShape)] + [')']
    #print ''.join(evList)
    return eval(''.join(evList))


def rebin(ndarray, new_shape, operation='sum'):
    """
    Bins an ndarray in all axes based on the target shape, by summing or
        averaging.

    Number of output dimensions must match number of input dimensions and
        new axes must divide old ones.

    Example
    -------
    >>> m = np.arange(0,100,1).reshape((10,10))
    >>> n = bin_ndarray(m, new_shape=(5,5), operation='sum')
    >>> print(n)

    [[ 22  30  38  46  54]
     [102 110 118 126 134]
     [182 190 198 206 214]
     [262 270 278 286 294]
     [342 350 358 366 374]]

    from https://stackoverflow.com/a/29042041
    """
    operation = operation.lower()
    if not operation in ['sum', 'mean']:
        raise ValueError("Operation not supported.")
    if ndarray.ndim != len(new_shape):
        raise ValueError("Shape mismatch: {} -> {}".format(ndarray.shape,
                                                           new_shape))
    compression_pairs = [(d, c//d) for d,c in zip(new_shape,
                                                  ndarray.shape)]
    flattened = [l for p in compression_pairs for l in p]
    ndarray = ndarray.reshape(flattened)
    for i in range(len(new_shape)):
        op = getattr(ndarray, operation)
        ndarray = op(-1*(i+1))
    return ndarray


def radial_power_spectrum(a, binsize=1.):
    """\
    Azimuthally averaged power spectrum distribution.
    
    Parameters
    ----------
    a : 2D-numpy-array
        The 2D array.
        
    binsize : float, Default=1., optional
        Size of the averaging bin, in the same units as pixsize.
        
    Returns
    -------
    bin_centers : 1D-numpy-array
        Array with bin centers
    
    radial_prof : 1D-numpy-array
        Array with average of each bin from the ``np.abs(np.fft.fftn(a))**2``.
        
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> a=np.random.rand(50,50) 
    >>> bin_center, radial_prof = pyE17.utils.radial_power_spectrum(a, binsize=2.)
    >>> bin_center
    array([ 0.02,  0.06,  0.1 ,  0.14,  0.18,  0.22,  0.26,  0.3 ,  0.34,
           0.38,  0.42,  0.46,  0.5 ,  0.54,  0.58,  0.62,  0.66,  0.7 ,  0.74])
    >>> radial_prof
    array([  1.75512136e+05,   1.78365662e+02,   2.00550152e+02,
             2.00616322e+02,   2.01170854e+02,   2.07898467e+02,
             2.07330155e+02,   2.38324027e+02,   2.11053515e+02,
             2.11612551e+02,   2.04571626e+02,   1.95927279e+02,
             2.18037006e+02,   2.19605333e+02,   2.63182437e+02,
             2.47427615e+02,   1.19379279e+02,   1.69737831e+02,
                        nan])
                        
    .. note::
        Adapted from: http://agpy.googlecode.com/svn-history/r317/trunk/agpy/radialprofile.py
    """
    sh = a.shape
    f2 = np.abs(np.fft.fftn(a))**2
    r = np.sqrt(fvec2(sh, 1./np.array(sh)))
    binsize = float(binsize) / min(sh)

    nbins = int(np.round(r.max() / binsize)+1)
    bins = np.linspace(0,nbins * binsize,nbins+1)

    whichbin = np.digitize(r.flat,bins)
    nr = np.bincount(whichbin)[1:]

    f2r = f2.ravel()
    radial_prof = np.array([f2r[whichbin==b].sum() / (whichbin==b).sum() for b in range(1,nbins+1)])

    bin_centers = (bins[1:]+bins[:-1])/2.
    return bin_centers, radial_prof

def nrmse(a,b,rescale_on=False):
    """\
    Normalized root mean square error of ``a`` and ``b``. Normalized to ``a``.
    
    Parameters
    ----------
    a : numpy_array
        Array to normalize on.
    
    b : numpy_array
        Array for error.        
    
    rescale_on : bool, Default=False, optional
        If True, minimize a-b*rescale.
        
    Returns
    -------
    error : float
        Mean square error.
    
    rescale : float, optional
        Rescale factor.
        
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> a = np.random.rand(10,10,10)
    >>> b = np.random.rand(10,10,10)
    >>> pyE17.utils.nrmse(a,b)
    0.71311274187237506 #random
    >>> error, rescale = pyE17.utils.nrmse(a,b, rescale_on=True)
    
    :Author: Marco    
    """
    if rescale_on:
        rescale=np.abs(a).sum()/(np.abs(b).sum())
        e2=(np.abs(a-b*rescale)**2).sum()/((np.abs(a)**2).sum())
        return np.sqrt(e2), rescale
    else:
        e2=(np.abs(a-b)**2).sum()/((np.abs(a)**2).sum())
        return np.sqrt(e2)

def errorFienup(w1,w2,rescale_on=False):
    """\
    Calculates the sqrt error of two wavefronts where one wavefront is allowed
    to have a constant phase offset. Normalized to ``w1``.
    According to Fienup: Invariant error metrics for image reconstruction.
    
    
    Parameters
    ----------
    w1 : numpy_array
        Array to normalize on.
    
    w2 : numpy_array
        Array for error.        
    
    rescale_on : bool, Default=False, optional
        If ``rescale_on=True`` , w2 will be multiplied by a constant factor so that the error is minimized.
        
    Returns
    -------
    error : float
        Mean square error.
    
    rescale : float, optional
        Rescale factor.
        
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> a = np.random.rand(100,2).view(dtype=np.complex128)
    >>> b = np.random.rand(100,2).view(dtype=np.complex128)
    >>> pyE17.utils.nrmse(a,b)
    0.6538093398866105 #random
    >>> error, rescale = pyE17.utils.errorFienup(a,b, rescale_on=True)   
    
    :Author: Marco
    """
    w1_abs=(np.abs(w1)**2).sum()
    w2_abs=(np.abs(w2)**2).sum()
    cc_w12=np.abs((w1*w2.conj()).sum())#cross-corr for zero 
    if rescale_on:
        rescale=cc_w12/w2_abs
        error=np.sqrt((w1_abs+rescale**2*w2_abs-2*rescale*cc_w12)/w1_abs)        
        return error,rescale
    else:
        error=np.sqrt((w1_abs+w2_abs-2*cc_w12)/w1_abs)    
        return error
  
def fienupPhase(w1,w2):
    """\
    Calculates the phase-offset between to wavefronts via cross-corr according to fienup
    so that ``w1`` and ``w2*exp(1i*fienupPhase(w1,w2))`` are in phase.
    
    Parameters
    ----------
    w1 : numpy_array
        Wavefront.
    
    w2 : numpy_array
        Wavefront.        
        
    Returns
    -------
    float
        Phase-offset between to wavefronts.
        
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> a=np.random.rand(100,2).view(dtype=np.complex128)
    >>> b=np.random.rand(100,2).view(dtype=np.complex128)
    >>> pyE17.utils.fienupPhase(a,b)
    -0.066449370208335107 #random
    
    :Author: Marco
    """    
    
    return np.angle((w1*w2.conj()).sum())

def roll_anypad(a, shift, axis=None,anyNumber=1):
    """\
    Roll array elements along a given axis.

    Elements off the end of the array are treated as anyNumber.
    
    Adapted from the web...

    Parameters
    ----------
    a : array_like
        Input array.
    shift : int
        The number of places by which elements are shifted.
    axis : int, optional
        The axis along which elements are shifted.  By default, the array
        is flattened before shifting, after which the original
        shape is restored.
    anyNumber : float, Default=1, optional
        Added numbers to the array.
    
    Returns
    -------
    res : array_like
        Rolled array.
        
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np
    >>> a=np.random.rand(5,5)
    >>> a
    array([[ 0.83012522,  0.13426836,  0.12027849,  0.99011072,  0.83481243],   #random
           [ 0.69667573,  0.84077342,  0.99149702,  0.87083386,  0.49749519],   #random
           [ 0.67894601,  0.72199065,  0.33219532,  0.26829838,  0.32242914],   #random
           [ 0.6163832 ,  0.24278867,  0.90765908,  0.56588041,  0.57898317],   #random
           [ 0.84104277,  0.94597751,  0.23624819,  0.96209888,  0.20598501]])  #random
    >>> pyE17.utils.roll_anypad(a,7)
    array([[ 1.        ,  1.        ,  1.        ,  1.        ,  1.        ],
           [ 1.        ,  1.        ,  0.83012522,  0.13426836,  0.12027849],   #random
           [ 0.99011072,  0.83481243,  0.69667573,  0.84077342,  0.99149702],   #random
           [ 0.87083386,  0.49749519,  0.67894601,  0.72199065,  0.33219532],   #random
           [ 0.26829838,  0.32242914,  0.6163832 ,  0.24278867,  0.90765908]])  #random
    >>> pyE17.utils.roll_anypad(a,2,axis=1)
    array([[ 1.        ,  1.        ,  0.83012522,  0.13426836,  0.12027849],   #random
           [ 1.        ,  1.        ,  0.69667573,  0.84077342,  0.99149702],   #random
           [ 1.        ,  1.        ,  0.67894601,  0.72199065,  0.33219532],   #random
           [ 1.        ,  1.        ,  0.6163832 ,  0.24278867,  0.90765908],   #random
           [ 1.        ,  1.        ,  0.84104277,  0.94597751,  0.23624819]])  #random
    >>> pyE17.utils.roll_anypad(a,2,axis=0, anyNumber=4.3)
    array([[ 4.3       ,  4.3       ,  4.3       ,  4.3       ,  4.3       ],
           [ 4.3       ,  4.3       ,  4.3       ,  4.3       ,  4.3       ],
           [ 0.83012522,  0.13426836,  0.12027849,  0.99011072,  0.83481243],   #random
           [ 0.69667573,  0.84077342,  0.99149702,  0.87083386,  0.49749519],   #random
           [ 0.67894601,  0.72199065,  0.33219532,  0.26829838,  0.32242914]])  #random
           
    See Also
    --------
    roll_onepad : ``anyNumber=1``.
    roll_zeropad : ``anyNumber=0``.
    """
    a = np.asanyarray(a)
    if shift == 0: return a
    if axis is None:
        n = a.size
        reshape = True
    else:
        n = a.shape[axis]
        reshape = False
    if np.abs(shift) > n:
        res = np.ones_like(a)*anyNumber
    elif shift < 0:
        shift += n
        zeros = np.ones_like(a.take(np.arange(n-shift), axis))*anyNumber
        res = np.concatenate((a.take(np.arange(n-shift,n), axis), zeros), axis)
    else:
        zeros = np.ones_like(a.take(np.arange(n-shift,n), axis))*anyNumber
        res = np.concatenate((zeros, a.take(np.arange(n-shift), axis)), axis)
    if reshape:
        return res.reshape(a.shape)
    else:
        return res
   
def roll_zeropad(a,shift,axis=None):
    """\    
    Wrapper for :py:func:`roll_anypad` with ``anyNumber=0``.
    
    See Also
    --------
    roll_anypad : Roll array elements along a given axis.
    roll_onepad : anyNumber=1.
    """
    return roll_anypad(a,shift,axis,anyNumber=0)

def roll_onepad(a,shift,axis=None):
    """
    Wrapper for :py:func:`roll_anypad` with ``anyNumber=1``.
    
    See Also
    --------
    roll_anypad : Roll array elements along a given axis.
    roll_zeropad : ``anyNumber=0``.
    """
    return roll_anypad(a,shift,axis,anyNumber=1)

def invert(inarray):
    """Invert a numpy array, i.e. exchange min and max values.
    
    Parameters
    ----------
    inarray : array_like
        Input array.
    
    Returns
    -------
    array_like
        Inverted numpy array.
        
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np 
    >>> a = np.array([1,3,5,7])
    >>> pyE17.utils.invert(a)
    array([6, 4, 2, 0])
    >>> b = np.random.rand(5)
    >>> pyE17.utils.invert(b)
    array([ 0.        ,  0.12916509,  0.48932371,  0.64603256,  0.21894844]) #random
    >>> b
    array([ 0.69376397,  0.56459887,  0.20444026,  0.04773141,  0.47481552]) #random
    """
    temp = np.ones_like(inarray)
    maxval = np.max(inarray)
    return temp*maxval-inarray

def normalize(inarray):
    """Normalize a numpy array to range [0,1].
    
    Parameters
    ----------
    inarray : array_like
        Input array.
    
    Returns
    -------
    array_like
        Normalized numpy array.
        
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np 
    >>> a = np.array([1,3,5,7],dtype=float)
    >>> pyE17.utils.normalize(a)
    array([ 0.        ,  0.33333333,  0.66666667,  1.        ])   
    """
    maxval = np.max(inarray)
    minval = np.min(inarray)
    return (inarray - minval)/(maxval-minval)

def logpolar(a, shape=None, center=None):
    """
    Return log-polar transformed image and log base.\n
    (from http://www.lfd.uci.edu/~gohlke/code/imreg.py.html)
    
    Parameters
    ----------
    a : array_like
        Input array.
    shape : array, Default=None, optional
        Used shape (number of angles, number of radii), if None shape of ``a`` is used.
    center : array, Defaul=None, optional
        Used center postion, pixel units. If None center of image is used.
        
    Returns
    -------
    output : array_like
        Log-polar transformed image.
    log_base : float
        Log base.
        
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np 
    >>> image=np.random.rand(100,100)
    >>> transf_image, log_base = pyE17.utils.logpolar(image, center=[12,40])
    
    .. warning::
        ``shape`` option not correct implemented! Use Default!
      
    """
    from scipy import ndimage
    sh = a.shape
    if shape is None:
        angles = sh[0]
        radii = sh[1]
    if center is None:
        center = sh[0] / 2, sh[1] / 2
    theta = -np.linspace(0, np.pi, angles, endpoint=False).reshape((angles,1))
    d = np.hypot(sh[0]-center[0], sh[1]-center[1])
    log_base = 10.0 ** (np.log10(d) / (radii))
    radius = np.power(log_base, np.arange(radii, dtype=np.float64)).reshape((1,radii)) - 1.0
    x = radius * np.sin(theta) + center[0]
    y = radius * np.cos(theta) + center[1]
    output = ndimage.interpolation.map_coordinates(a, [x, y])
    return output, log_base

######################## Added by Sebastian Ehn ###############################################################


def fill_holes(img_, radius = 1, mask_ = None, method = 'mean'):
    """Replace NaN elements in an array using a simple iterative image inpainting algorithm.
    
    The algorithm is the following:
    
        1. For each element in the input array, replace it by a weighted average
           of the neighbouring elements which are not NaN themselves.
           
        2. Several iterations are needed if there are adjacent NaN elements.
           If this is the case, information is "spread" from the edges of the missing
           regions iteratively, until there are no NaN's left.
       
    One can choose if the image filtering and filling is done using a simple mean or a median filter. Median filtering gives 
    highly improved results, but is slow at the time!
    
    Parameters
    ----------
    
    img\_ : np.array
        an array containing the input image data. Can have more than 2d for more thanon image. NaN elements that have to be replaced.
    
    radius : int
        the raduis of the filter kernel
    
    mask\_ :  np.array
        a boolean mask to mask out areas where no replacement is done, eg. outside of gratings. Use this to minmize computing time.
    
    method : string
        a string that indicated which method should be used for filtereing and filling up the holes. Possible values are:
        'mean' or 'median'
    
    
    Returns
    -------
    
    img : np.ndarray
        a copy of the input array, where NaN elements have been replaced.
    """
    #TODO: incorporate other inpainting algorithms like PDE,....
    #      speed up median filtering process
    
    
    
    img = img_.copy()
    
    if mask_ is None:
        mask = np.ones_like(img, dtype=np.bool)
    else:
        mask = np.resize(mask_, img.shape)
    
    

    if method=='mean':
        
        img_mask    = np.logical_and(np.isfinite(img), mask)        
        
        while not np.isfinite(img[mask]).all():
        
            actual_img = np.nan_to_num(img)
            actual_img_mask = np.logical_and(np.isfinite(img), mask)
        
            actual_fraction = 1. - float(actual_img_mask[mask].sum()) / actual_img_mask[mask].size
            print("fraction of invalid data: %.3g" % (actual_fraction))

            it_sum  = np.zeros_like(actual_img)
            it_norm = np.zeros_like(actual_img_mask, dtype = np.int)
        
            for i_x in range(-radius, radius + 1):
                for i_y in range(-radius, radius + 1):
                
                    left_slices  = [slice(None)] * (img.ndim - 2) + [slice(max(i_y, 0), min(img.shape[-2] + i_y, img.shape[-2])), slice(max(i_x, 0), min(img.shape[-1] + i_x, img.shape[-1]))]
                    right_slices = [slice(None)] * (img.ndim - 2) + [slice(max(-i_y, 0), min(img.shape[-2] - i_y, img.shape[-2])), slice(max(-i_x, 0), min(img.shape[-1] - i_x, img.shape[-1]))]
                    it_sum[left_slices]  = it_sum[left_slices]  + actual_img[right_slices]
                    it_norm[left_slices] = it_norm[left_slices] + actual_img_mask[right_slices]

            actual_img_mask = np.logical_and((img_mask == 0), (it_norm != 0))

            img[actual_img_mask] = it_sum[actual_img_mask] / it_norm[actual_img_mask]
    
        return img
        
    if method=='median':
            
        def median_nan(array):
            med= np.median(array[np.isfinite(array)])
            return med
            
        pix_to_replace = np.isnan(img_)
        
        while not np.isfinite(img[mask]).all():
            valid_pixels = np.isfinite(img)
            actual_fraction = 1. - float(valid_pixels[mask].sum()) / valid_pixels[mask].size
            print("fraction of invalid data: %.3g" % (actual_fraction))
            
            img = ndimage.filters.generic_filter(img,median_nan,size=radius)
            
        img_filled = img_.copy()
        img_filled[pix_to_replace] = img[pix_to_replace]
        return img_filled



######################## Added by Andreas Fehringer ###############################################################

def delxrc(a,is2ndOperator=None,axis1=-2,axis2=-1):
    """\
    Roberts cross first order derivative for finite difference calculation.
    
    .. note::
        The last element along the derivative direction is set to 0.\n
        Pixel units are used (:math:`\\Delta x = \\Delta h = 1`).
    
    Parameters
    ----------  
    a : np.array
        Input array.   
    is2ndOperator : bool, Default=None, optional
        Used to switch axes.
    axis1 :  int, Default=-2, optional
        First axis used. 
    axis2 : int, Default=-1, optional
        Second axis used.
    
    Returns
    ------- 
    b: np.ndarray
        Derivative of array ``a``.
        
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np 
    >>> a = np.array([[i+j**2 for j in range(5)] for i in range(5)])
    >>> a
    array([[ 0,  1,  4,  9, 16],
           [ 1,  2,  5, 10, 17],
           [ 2,  3,  6, 11, 18],
           [ 3,  4,  7, 12, 19],
           [ 4,  5,  8, 13, 20]])
    >>> pyE17.utilz.delxrc(a)
    array([[-1, -2, -4, -5,  0],
           [-1, -2, -4, -5,  0],
           [-1, -2, -4, -5,  0],
           [-1, -2, -4, -5,  0],
           [ 0,  0,  0,  0,  0]])
    >>> pyE17.utils.delxrc(c,is2ndOperator=True)
    array([[ 0, -1, -2, -4,  0],
           [ 0, -1, -2, -4,  0],
           [ 0, -1, -2, -4,  0],
           [ 0, -1, -2, -4,  0],
           [ 0,  0,  0,  0,  0]])

    See Also
    --------
    delxrc3D : Diagonal first order derivative for finite difference calculation in 3D.
    """
    if is2ndOperator:
        axis1, axis2 = axis2, axis1  # switch axes
    elif is2ndOperator == None:
        is2ndOperator = axis2 < axis1
    nd = len(a.shape)
    axis1 = list(range(nd))[axis1]
    axis2 = list(range(nd))[axis2]
    if axis1 == axis2:
        raise ValueError('axis1 must differ from axis2.')

    if is2ndOperator:    # 2nd roberts cross operator
        slice1  = [slice(None,-1) if i==axis1 else slice(1,None)  if i==axis2 else slice(None) for i in range(nd)]
        slice2  = [slice(1,None)  if i==axis1 else slice(None,-1) if i==axis2 else slice(None) for i in range(nd)]
        slice_b = [slice(None,-1) if i==axis1 or i==axis2 else slice(None) for i in range(nd)]
    else:                # 1st roberts cross operator
        slice1  = [slice(None,-1) if i==axis1 or i==axis2 else slice(None) for i in range(nd)]
        slice2  = [slice(1,None)  if i==axis1 or i==axis2 else slice(None) for i in range(nd)]
        slice_b = slice1
    b = np.zeros_like(a)
    b[slice_b] = (a[slice1] - a[slice2]) * (np.sqrt(2) * .5)
    return b

def delxrc3D(a,diagonal_nr=None,axis1=-2,axis2=-1,axis3=None):
    """\
    Diagonal first order derivative for finite difference calculation in 3D.
    
    The difference to the Roberts cross operator is that the positon of the 
    derivative in the dimension orthogonal to the two given axes is no more in 
    the center of the edge of each voxel but on the corner. This makes it 
    possible to calculate exact absolute gradients (because the positions of 
    the derivatives of all three dimensions lie on top of each other).
    
    .. note::
        The last element along all three dimensions is set to 0.\n
        Pixel units are used (:math:`\\Delta x = \\Delta h = 1`).
    
    Parameters
    ----------  
    a : np.array
        Input array.   
    diagonal_nr : bool, Default=None, optional
        The parameter ``diagonal_nr`` lets a user walk through all axis easily. 
        It's value must be one of 0, 1 or 2.
    axis1 :  int, Default=-2, optional
        First axis used. 
    axis2 : int, Default=-1, optional
        Second axis used.
    axis3 : int, Default=None, optional
        By default, ``axis3`` will be set to the fastest dimension still available.
    
    Returns
    ------- 
    b: np.ndarray
        Derivative of array ``a``.
        
    Examples
    --------
    >>> import pyE17
    >>> import numpy as np 
    >>> a = np.random.rand(5,5,5)
    >>> da=pyE17.utilz.delxrc3D(a)
        
    See Also
    --------
    delxrc : Roberts cross first order derivative for finite difference calculation.
    """
    # [#4]
    nd = len(a.shape)
    if diagonal_nr is not None:
        axis1, axis2, axis3 = ((-2, -1, -3), (-1, -3, -2), (-3, -2, -1))[diagonal_nr]
    axis1 = list(range(nd))[axis1]
    axis2 = list(range(nd))[axis2]
    if axis3 is None:
        if axis1 == axis2:
            raise ValueError('axis1, axis2 and axis3 must be pairwise distict.')
        axis3 = np.arange(nd,dtype=np.int)
        axis3[axis1] = 0
        axis3[axis2] = 0
        axis3 = axis3.max()
    else:
        axis3 = list(range(nd))[axis3]
        if axis1 == axis2 or axis1 == axis3 or axis2 == axis3:
            raise ValueError('axis1, axis2 and axis3 must be pairwise distict.')
    
    slice1  = [slice(1,None)  if i==axis1 or i==axis2 or i==axis3 else slice(None) for i in range(nd)]
    slice2  = [slice(None,-1) if i==axis1 or i==axis2 else slice(1,None) if i==axis3 else slice(None) for i in range(nd)]
    slice3  = [slice(None,-1) if i==axis3 else slice(1,None) if i==axis1 or i==axis2 else slice(None) for i in range(nd)]
    slice4  = [slice(None,-1) if i==axis1 or i==axis2 or i==axis3 else slice(None) for i in range(nd)]
    slice_b = slice4

    b = np.zeros_like(a)
    b[slice_b] = (a[slice1] - a[slice2] + a[slice3] - a[slice4]) * (np.sqrt(2) * .25)
    return b


def selective_gauss_filter(img, radius, gamma = .5, stepsize = .5):
    """
    Apply the Perona Malik filter on the last two dimensions of an array.
    
    The Perona Malik filter can be described as diffusion of image intensities where the diffusivity is locally higher for strong edges.
    
    Parameters
    ----------
    img : array_like
        The input array (ndim >= 2).
    radius : float
        Gaussian blurring radius for areas without edges.
    gamma : float, Default=0.5, optional
        Edge parameter, independent of the intensity range (smaller values means more edges are preserved).
    stepsize : float, Defalut=0.5, optional
        Timestep in each iteration (the uppermost limit is sqrt(2)).

    Returns
    -------
    img_f[...,1:,1:] : array_like
        Filtered image.
    """
    #  [#2], [#3]
    # the derivative function must be as exact as possible and compute the
    # derivative at equal positions for different dimensions (for the gradient)
    # (a difference over a long distance has a smoothing effect,
    # which returns too spacially inexact results!)
    # e.g. roberts cross for 2D; central difference would also be ok, but not so exact
    
    time = radius**2 * .5
    # if g was constantly 1 everywhere, this diffusion process would equal
    # gaussian smoothing with a  radius = sqrt(2 *  time)
    
    inv_gamma_255_squared = (255. / (img.max() * gamma))**2
    # rescale gamma relative to the maximum value of the image / 255
    
    g = np.zeros(list(img.shape[:-2]) + [img.shape[-2] + 1, img.shape[-1] + 1])
    img_f = np.zeros_like(g)
    img_f[...,1:,1:] = img[...]
        # leave a border of 0 at the left and upper edge (for the last derivative)
    
    for t in np.arange(0., time, stepsize):
        # weight for the edges by Perona & Malik:
        # (i.e. the diffusivity at all pixel corners of the 2D image)
        #     g = 1. / sqrt(1 + abs_grad(img)**2 / gamma**2)
        g[...,1:-1,1:-1] = 1. / np.sqrt(1. + (
                delxrc(img_f, 0)[...,1:-1,1:-1]**2 + 
                delxrc(img_f, 1)[...,1:-1,1:-1]**2
            ) * inv_gamma_255_squared)
            # enforce the changes to the outside of the image to be 0
            # (no intensity may leave the image)
        
        # intensity changes because of diffusion along the different diagonals:
        img_f[...,1:,1:] += min(time - t, stepsize) * (  # remaining stepsize
                delxrc(delxrc(img_f, 0) * g, 0)[...,:-1,:-1] + 
                delxrc(delxrc(img_f, 1) * g, 1)[...,:-1,:-1]
            )
            # stepsize is limited in size by the size of the derivatives dx, dy,
            # where g <= 1:  stepsize * g < min(dx,dy)

    return img_f[...,1:,1:]


def selective_gauss_filter_3D(img, radius, gamma = .5, stepsize = .5):
    """
    Apply the Perona Malik filter on the last three dimensions of an array.
    
    The Perona Malik filter can be described as diffusion of image intensities where the diffusivity is locally higher for strong edges.
    
    Parameters
    ----------
    img : array_like
        The input array (ndim >= 3).
    radius : float
        Gaussian blurring radius for areas without edges.
    gamma : float, Default=0.5, optional
        Edge parameter, independent of the intensity range (smaller values means more edges are preserved).
    stepsize : float, Defalut=0.5, optional
        Timestep in each iteration (the uppermost limit is sqrt(2)).
    
    Notes
    -----    
    Author / support: Andreas.Fehringer@ph.tum.de

    Returns
    -------
    img_f[...,1:,1:,1:] : array_like
        Filtered image.
    """
    #  [#2], [#3], [#4]
    # the derivative function must be as exact as possible and compute the
    # derivative at equal positions for different dimensions (for the gradient)
    # (a difference over a long distance has a smoothing effect,
    # which returns too spacially inexact results!)
    # e.g. special "roberts cross" for 3D; central difference would also be ok, but not so exact
    
    time = radius**2 * .5
    # if g was constantly 1 everywhere, this diffusion process would equal
    # gaussian smoothing with a  radius = sqrt(2 *  time)
    
    inv_gamma_255_squared = (255. / (img.max() * gamma))**2
    # rescale gamma relative to the maximum value of the image / 255
    
    g = np.zeros(list(img.shape[:-3]) + [img.shape[-3] + 1, img.shape[-2] + 1, img.shape[-1] + 1])
    img_f = np.zeros_like(g)
    img_f[...,1:,1:,1:] = img[...]
        # leave a border of 0 at the left and upper edge (for the last derivative)
    
    for t in np.arange(0., time, stepsize):
        # weight for the edges by Perona & Malik:
        # (i.e. the diffusivity at all pixel corners of the 2D image)
        #     g = 1. / sqrt(1 + abs_grad(img)**2 / gamma**2)
        g[...,1:-1,1:-1,1:-1] = 1. / np.sqrt(1. + (
                delxrc3D(img_f, 0)[...,1:-1,1:-1,1:-1]**2 + 
                delxrc3D(img_f, 1)[...,1:-1,1:-1,1:-1]**2 + 
                delxrc3D(img_f, 2)[...,1:-1,1:-1,1:-1]**2
            ) * inv_gamma_255_squared)
            # enforce the changes to the outside of the image to be 0
            # (no intensity may leave the image)
        
        # intensity changes because of diffusion along the different diagonals:
        img_f[...,1:,1:,1:] += min(time - t, stepsize) * (  # remaining stepsize
                delxrc3D(delxrc3D(img_f, 0) * g, 0)[...,:-1,:-1,:-1] + 
                delxrc3D(delxrc3D(img_f, 1) * g, 1)[...,:-1,:-1,:-1] + 
                delxrc3D(delxrc3D(img_f, 2) * g, 2)[...,:-1,:-1,:-1]
            )
            # stepsize is limited in size by the size of the derivatives
            # dx, dy, dz, where g <= 1:  stepsize * g < min(dx,dy,dz)

    return img_f[...,1:,1:,1:]



def reverse_axis(   vol, axis):
    """\
    reverse_axis flips the orientation of the specified axis and returns
    a view of the input volume, if a ndarray is passed.
    
    Author:Sebastian Allner

    Parameters
    ----------
    vol : array_like
        the volume from which one axis shall be swapped
    axis : int
        the axis which shall be swapped. The number should not be
        higher than the dimensionality of the input volume (< vol.ndim).
    
    See Also
    -------- 
    np.swapaxes()
    """
    return np.swapaxes(   np.swapaxes(vol,0, axis)[::-1], 0, axis)
    
def mirror_boundaries(  data, axis, margin):
    """\
    mirror_boundaries extends the dataset in the given axis by the 
    spezified margin. It enlarges the input array with mirrored data.
    The applied margins have to be smaller than the shape in the specified axis.
    The parameters margin and axis must have the same length, so that every 
    given axis is extended by a certain margin. This function works for any
    n-dimensional array.
    
    Author:Sebastian Allner

    Parameters
    ----------
    data : array_like
        input data which shall be padded with the mirrored boundaries.
    axis : int or tuple of ints
        defines which axis of the array shall be padded. The number should not 
        be higher than the dimensionality of the input data (< data.ndim).
        For at least 2D arrays, also more axes can be given in a tuple, see 
        Examples.
    margins : int or tuple of ints
        defines which margins of the array shall be padded to the respective 
        axis. The number should be small in comparison to the array length of 
        the input data that the array content stays meaningful.
        For at least 2D arrays, also more axes can be given in a tuple, see 
        Examples.
    
    Returns
    -------
    data : array_like
    returns the array padded with the mirrored boundaries of the given axes.

    Examples
    --------
    a = np.arange(100).reshape((10,10)
    
    b = mirror_boundaries(a, axis = 0, margin = 4 )    
    or
    b = mirror_boundaries(a, axis = (0,1), margin = (4,5) )
    
    plt.imshow(b) 
    """
    
    # one axis extension
    if np.ndim(axis) ==0:
        ext_front = np.delete(data, list(range( margin, data.shape[axis])), axis = axis)
#        data = np.concatenate( (reverse_axis(ext_front, axis) ,data)   , axis =axis)
        ext_end   = np.delete(data, list(range( data.shape[axis]- margin)), axis = axis)
        data = np.concatenate( (reverse_axis(ext_front, axis), data, reverse_axis(ext_end, axis))   , axis =axis)
    # extension on more than one axis
    else:
        for (a,m) in zip(axis,margin):
            ext_front = np.delete(data, list(range( m, data.shape[a])), axis = a)
#            data = np.concatenate( (reverse_axis( ext_front, axis = a), data), axis =a)
            ext_end   = np.delete(data, list(range( data.shape[a]-m)), axis = a)
            data = np.concatenate( (reverse_axis( ext_front, axis = a), data, reverse_axis( ext_end, axis = a)), axis =a)
    return data
  
def gaussian_distance_weights(  weighting_sigma, \
                                weighting_fraction=0.1, \
                                return_pos = False):
    """\
    gaussian_distance_weights creates a gaussian weighting array in arbitrary
    dimensions in the range [0,1]. It takes a sigma to specify the standard
    deviation of the gaussian bell curve in pixels.
    
    If the return_pos flag is True, it additionally returns the positions of the
    array values in the order [x, y, z, ....] depending on the specified
    dimensions.
    
    The weighting_fraction cuts off the array on the coordinate axes at the 
    specific weight to restrict the array size by given value.
    
    Author:Sebastian Allner
    
    Parameters
    ----------
    weighting_sigma : int or tuple of ints
        defines the standard deviation of the gaussian kernel in each array
        dimension. Zero is also possible for a length=1 axis . 
    weighting_fraction : float
        defines the cutoff fraction which should still be in the array.
    
    Notes
    --------
    The size of the array is determined by both the weighting_sigma and the 
    weighting_fraction parameters.
    The central voxel is defined as 1.
    
    Examples
    --------
    w = gaussian_distance_weights( (2,1,3), weighting_fraction= 0.05 )
    creates a 3D array which contains in each axis the gaussian weights
    that cuts of at a weight of 0.05 on all main axes.
    or
    w, positions = gaussian_distance_weights( (1,0), return_pos = True )
    creates a 2D array which contains in each axis the gaussian weights
    that cuts of at the default weight of 0.1 on all main axes. The zero on
    the second axis means that in this dimension the array has a size of 1
    and the weight is only influenced by the other axis (or axes for 3D...).
    It additionally returns the positions.
    """
    weighting_sigma = np.asarray(weighting_sigma)
    #determine shape according to maximum weighting fraction
    w_shape = np.array(2*np.ceil(np.sqrt(-2*(weighting_sigma**2)*np.log(weighting_fraction))), dtype=np.int)
    w_shape+= (w_shape%2==0) 
    wh_shape= w_shape//2 

    #initialize array and array positions relative to central voxel 
    w = np.zeros(w_shape)
    positions= np.asarray(np.where(w==0)).T-wh_shape
    
    # avoid deviding by zero, if sigma=0 in one or more axes 
    weighting_sigma+= (weighting_sigma==0)   
    
    w= np.exp(   -(positions**2/(2.*weighting_sigma**2)).sum(axis =1)  ).reshape(w_shape)
    
    if(return_pos==False):return w
    else:return (w, positions.astype(int).reshape(np.append(w_shape,3)))



def find_extrema(signal, which = 'all', sigma = 0., cutoff = 0, axis = -1):
    """\
Finds the indices of extrema along a given axis.

Parameters
----------
signal : array_like
    Input signal, n-dimensional. 

which : string, optional
    Type of extrema to find. 'min' returns only minima, 'max' only maxima, 
    everything else returns both (default).

sigma : integer, optional
    Standarddeviation of noise to suppress.  
    Actually this is the sigma of a Gauss filter applied before finding extrema.
    Default is 0.
    
cutoff : integer, optional
    Number of high frequencies to cut off the `signal` before finding extrema.
    Default is 0.
    
axis : integer, optional
    Axis along which extrema are found. By default -1.
    

Returns
-------
min : ndarray
    Array containing the indices of the minima (only if `which` is not 'max').

max : ndarray
    Array containing the indices of the maxima (only if `which` is not 'min').
    

Notes
-----
The algorithm cannot find extrema at the borders of the array, i.e. at indices 0
and -1.

Author / support: Andreas.Fehringer@ph.tum.de

    

Examples
--------
>>> import numpy as np
>>> signal  = np.sin(np.linspace(0., 3. * np.pi, 300))
>>> signal += np.random.normal(scale = .5, size = signal.shape)
>>> find_extrema(signal, which = 'max')
"""   
    # handle input
    signal = np.array(signal)
    axis   = list(range(signal.ndim))[axis]

    def sl(s, fill = None):
        if fill is None:  fill = slice(None)
        return [ s if i == axis else fill  for i in range(signal.ndim) ]
    
    if sigma > 0. or cutoff > 0:
        f_signal = np.fft.rfft(signal, axis = axis, n = 2 * signal.shape[axis])  # using 2x zero padding
        if sigma > 0.:
            # taken from http://en.wikipedia.org/wiki/Gaussian_filter#Definition
            f_signal *= np.exp(np.fft.rfftfreq(signal.shape[axis] * 2)**2 * (-4. * np.pi**2 * sigma**2))
        if cutoff > 0:
            # cutoff works exactly with 2x zero padding together with rfft
            f_signal[sl(slice(signal.shape[axis] - cutoff, None))] = 0.
        extr_mask = np.fft.irfft(f_signal, axis = axis)[sl(slice(0, signal.shape[axis]))]
    else:  extr_mask = signal
    extr_mask = delxb((delxf(extr_mask, axis = axis) > 0.).astype(np.int32), axis = axis)
    extr_mask[[0,-1]] = 0

    all_indices = np.resize(
        np.arange(signal.shape[axis]).reshape(sl(-1, 1)), 
        signal.shape
    )
    result = []
    if which != 'max':  result += [ all_indices[extr_mask > 0] ]
    if which != 'min':  result += [ all_indices[extr_mask < 0] ]

    if which == 'all':  return result
    else:               return result[0]



def edge_profile(img, axis = -1, is_overwrite_input = False):
    """
    Extract the profile of an edge or surface within an image.

    Parameters
    ----------
    img : array_like
        An image containing the edge or surface (and nothing more).

    axis : integer, optional
        Axis to operate on. It should best be orthogonal to the edge or surface. 
        -1 by default.

    is_overwrite_input : boolean, optional
        Tells if the input image may be overwritten with its gradient along 
        `axis` to save memory. False by default.


    Notes
    -----
    Author / support: Andreas.Fehringer@ph.tum.de


    Returns
    -------
    profile : ndarray
        The profile of the edge or surface in `img`.
    """
    grad_x = delxf(img, axis = axis, out = img if is_overwrite_input else None)
    norm   = grad_x.sum(axis = axis)
    norm[norm == 0.] = 1.
    
    weights_1D_shape       = [1] * grad_x.ndim
    weights_1D_shape[axis] = -1
    weights = np.resize(np.arange(grad_x.shape[-1]).reshape(weights_1D_shape) + .5, grad_x.shape)
    
    return (grad_x * weights).sum(axis = axis) / norm
    
def merge(a,b,shift,blend=1):
    '''Simple stitching of to images a and b with linear blending (standard)
    or sigmoidal or average blending.
    
    Parameters
    -----------
    a,b : array-like
        The two images, that should be merged together. Must have same 
        x-dimension.
    shift: int
        The number of pixels the two images should overlap.
    fade: int, optional, default=1
        the blending method.
        0: The overlapping region is just the average of the images.
        1: The two images are linearly blended.
        2: Sigmoidal blending.
        3: Difference blending.
    
    Returns
    -------
    m : array-like
        The blended images.
    '''
    x,y1 = a.shape
    x2,y2 = b.shape
    if not x2==x:
        raise NameError('Images have different x size')
    m = np.zeros((x,y1+y2-shift))
    m[:,:y1]=a
    m[:,y1:]=b[:,shift:]
    if blend==1:
        grad=np.linspace(1,0,shift)
        grad=np.tile(grad,x).reshape((x,shift))
    elif blend==2:
        e=np.linspace(6,-6,num=shift)
        ex=[]
        for i in e:
            ex.append(erf(i))
        ex=np.array(ex)
        grad=(ex+1)/2.
        grad=np.tile(grad,x).reshape((x,shift))
    elif blend==3:
        m[:,y1-shift:y1]=m[:,y1-shift:y1]-b[:,:shift]
        return m
    else:
        m[:,y1-shift:y1]=(m[:,y1-shift:y1]+b[:,:shift])/2.
        return m
    m[:,y1-shift:y1]*=grad
    m[:,y1-shift:y1]=m[:,y1-shift:y1]+b[:,:shift]*np.fliplr(grad)
    return m




