import h5py
def hdf5_read(filename):
    '''read hdf5 files created with our system...'''
    fid = h5py.File(filename,'r')
    data = fid['/entry/data']
    return data
