import scipy.ndimage
import numpy as np
import skimage.feature
import skimage.transform


################################################################################
#
def straighten_edge(edge):
    '''take first and last column and align them via zero crossing'''
    # filter input image to get rid of hot pixels
    edge_filt = scipy.ndimage.filters.median_filter(edge,5)
    x1 = edge_filt[:,0]
    x2 = edge_filt[:,-1]
    # normalize
    x1 = (x1 - np.mean(x1))/np.std(x1)
    x2 = (x2 - np.mean(x2))/np.std(x2)
    # zero crossing
    x1_zero_crossing = np.where(x1>0)[0][0]
    x2_zero_crossing = np.where(x2>0)[0][0]
    # angle
    angle = np.arctan((x2_zero_crossing - x1_zero_crossing)*1.0/edge.shape[1])
    edge_trafo = scipy.ndimage.rotate(edge,angle*180/np.pi,reshape=False)
    return edge_trafo, angle


################################################################################
def straighten_edge_hough(edge,sigma_canny=10):
    # try finding edge through canny edge detection
    edge_filt = scipy.ndimage.filters.median_filter(edge,5)
    edge_canny = skimage.filter.canny(edge_filt,sigma_canny)
    # detect line with hough transform
    h,a,d = skimage.transform.hough_line(edge_canny,np.arange(np.pi*2/5,np.pi*3/5,0.0005)) # the second argument specifies the angular range to search
    qq, angle, dist = skimage.transform.hough_line_peaks(h,a,d)
    # angle returns the tilt in radians, quite accurate
    # # rotate image back so axis is horizontal
    angle = angle*180/np.pi - 90
    edge_trafo = scipy.ndimage.rotate(edge,angle,reshape=False)
    return edge_trafo, angle


################################################################################
# line spread function lsf
def get_lsf(edge,cutxy=100):
    # try to get lsf
    lsf = np.diff(np.sum(edge[cutxy:-cutxy,cutxy:-cutxy],axis=1))
    return lsf,cutxy


################################################################################
# 50% value of MTF
def get_MTF_50(lsf):
    # make fft of lsf
    MTF = np.abs(np.fft.fft(lsf))
    # perform lowpass
    fMTF = np.fft.fft(MTF)
    fMTF[30:-30] = 0
    MTF = np.abs(np.fft.ifft(fMTF))
    # normalize, only take the first half of values
    MTF = MTF[0:int(np.ceil(MTF.shape[0]/2.))]/MTF[0]
    # return the position of the first value below 0.5
    ind_first = np.where(MTF<0.5)[0]
    ind_first = ind_first[0]
    # get subpixel location, linear with a*x = b
    a = (MTF[ind_first] - MTF[ind_first-1])/(ind_first - (ind_first-1)) # slope
    b = MTF[ind_first] - a*ind_first # b = y - a*x
    x = (0.5 - b)/a
    return MTF, x # ind_first

################################################################################
# everything together
def calc_MTF(s,sigma_canny=5,use_hough=False):
    if use_hough:
        e,q = straighten_edge_hough(s,sigma_canny=sigma_canny)
    else:
        e,q = straighten_edge(s)
    e,cutxy = get_lsf(e)
    q,e = get_MTF_50(e)
    return q,e
