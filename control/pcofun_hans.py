################################################################################
# Some basic functions for camera control
# Function names should be rather self explanatory
# call '<functionname>?' in ipython for a short description
# version 0, 22.03.2017, Hans
# FUNCTION LIST
#  - pco_init --> sets some parameters to sensible values. ALWAYS required before running
#  - pco_snap_view --> takes one image and displays on screen
#  - pco_live_view --> not implemented yet...
#  - pco_pixelclock_get --> read back current pixel clock
#  - pco_pixelclock_set --> set pixel clock
#  - pco_roi_get --> get current settings for ROI and binning
#  - pco_roi_set --> set current settings for ROI and binning
#  - pco_roi_reset --> reset ROI to full frame
#  - pco_bin_xy_set --> binning
#  - pco_acquire_series --> acquire a series of frames
# TO DO
# - refine pco_acquire_series
#     - implement longer exposure times, here :CAM:NumExposures might actually help
#     - implement a wait condition if camera temperature is outside some tolerance interval
#     - implement temperature control during acquisition
#     - IMPORTANT: check if the time.sleep in the for loop of acquire_series affects performance
# - share the whole raid system (windows D: drive) to make things more robust
# - Metadata log file, needs tinkering
# - ...
# History
# 10.07.2017 - Hans
#    It seems better to create instances for each PV instead of calling ep.PV each time
#    as pyepics holds a chache of these PVs. Also changed some ep.PV("pvname").get() to ep.caget("pvname")
#    and some ep.PV("pvname").put(x) to ep.caput("pvname",x).
#    Added a time.sleep condition in combination with ".put_complete" to the for loop
#    in pco_acquire_series
# 09.08.2017 - Hans
#    added the option to save the snap view to a different file name
# 25.10.2017 - Hans
#    added global exp time so that snap wiev takes same exposure as aquisition
# 21.11.2017 Hans Moved actual displaying of images from function pco_snap_view to one module up
#    --> user_defined_names_for_functions.py to allow for flatfield correction
#    To reduce overhead of snap_view, commented out setting of some epics variables, needs testing...
################################################################################

import epics as ep
import h5py
import PIL # for loading tiffs
# import matplotlib.pyplot as plt
import numpy as np
import time
import os

################################################################################
# some variables shared among Functions
pco_init_done = False # this keeps track if pco_init() was performed
fh_snap = [] # figure handle for snap view
snap_xcoord = [] # used py xmouse
snap_ycoord = [] # used py xmouse
snap_mousebutton = 3 # used py xmouse
exp_time =0.1

# EPICS doesnt really need global variables as values can be read back from
# the RBV variables


################################################################################
# set some PCO values to some sensible defaults
def pco_init(CameraPrefix='PCO',FileType='HDF5',pix_rate=0):
    '''initialize some detector PVs to default values,
       suitable for standard acquisitions
       FileType can be 'HDF5' or 'TIFF'
       Syntax:
          pco_init(CameraPrefix='PCO',FileType='HDF5')
          CP is camera prefix, depends on the ioc used,
            normally is 'PCO' (ioc=exampleStandalone)
          FT is File Type, depends on the ioc used,
            normally is 'HDF5' (ioc=exampleStandalone)'''
    #---------------------------------------------------------------------------
    # some variables used outside this function
    global pco_init_done
    global CP # Camera Prefix
    global FT # File Type
    global exp_time
    CP = CameraPrefix
    FT = FileType #
    #---------------------------------------------------------------------------
    # default file name and path_name
    file_name = 'pco' # file prefix
    path_name = 'D:/camserver/dump' # save to here !! Windods path
    #---------------------------------------------------------------------------
    # camera settings
    # create instances of the PVs
    PVcapture = ep.PV(CP+':'+FT+':Capture')
    PVcapture.put(0) # stop all capturing
    PVacquire = ep.PV(CP+':CAM:Acquire')
    PVacquire.put(0) # arm - 1 or disarm - 0  the camera
    PVacquireTime = ep.PV(CP+':CAM:AcquireTime')
    PVacquireTime.put(exp_time) # exposure time in s
    PVacquirePeriod = ep.PV(CP+':CAM:AcquirePeriod')
    PVacquirePeriod.put(0) # Acquire period in s, 0 for default
    PVnumExposures = ep.PV(CP+':CAM:NumExposures')
    PVnumExposures.put(1) # number of exposures per image, reswulting image is sum over the num exposures
    PVnumImages = ep.PV(CP+':CAM:NumImages')
    PVnumImages.put(0) # number of images to capture (?)1
    PVimageMode = ep.PV(CP+':CAM:ImageMode')
    PVimageMode.put(2) # 0-single, 1-multiple, 2-continuous
    PVtriggerMode = ep.PV(CP+':CAM:TriggerMode')
    PVtriggerMode.put(0) # 0-auto, 1-soft, 2-Ext.+Soft,3-Ext. Pulse, 5-Ext. only
    PVtimestampMode = ep.PV(CP+':CAM:TIMESTAMP_MODE')
    PVtimestampMode.put(0) # 0 - None, 1 - BCD, 2 - BCD+ASCII, 3 ASCII
    PVpixRate = ep.PV(CP+':CAM:PIX_RATE')
    PVpixRate.put(pix_rate) # [put pixel clock to 95333333 Hz (0) or 272250000 Hz (1)
    #---------------------------------------------------------------------------
    # HDF5 settings
    # create instances of the PVs
    PVenableCallbacks = ep.PV(CP+':'+FT+':EnableCallbacks')
    PVenableCallbacks.put(1) # Enable EPICS complaining about things
    PVfileWriteMode = ep.PV(CP+':'+FT+':FileWriteMode')
    PVfileWriteMode.put(2) # 0 - single, 1 - capture (reads everything to memory, then writes in one file to disk), 2 - Stream (appends to file on disk)
    PVfileName = ep.PV(CP+':'+FT+':FileName')
    PVfileName.put(file_name) # file name
    PVfilePath = ep.PV(CP+':'+FT+':FilePath')
    PVfilePath.put(path_name) # windows path to folder
    PVlazyOpen = ep.PV(CP+':'+FT+':LazyOpen')
    PVlazyOpen.put(1) # needed to avoid EPICS wanting to have an image prior to recording
    PVautoIncrement = ep.PV(CP+':'+FT+':AutoIncrement')
    PVautoIncrement.put(1) # activate auto increment file number
    #PVfileNumber = ep.PV(CP+':'+FT+':FileNumber')
    #PVfileNumber.put(1) # reset file numbering
    PVxmlFileName = ep.PV(CP+':'+FT+':XMLFileName')
    PVxmlFileName.put('C:/autosave/exampleCamera/test01_hdf5layout.xml') # this file defines the layout of the
    # hdf5 file, including which metadata will be written
    # the definition of the metadata attributes is done in a separate xml file
    # (at the moment C:\epics\support\pcocam2-3-0-4\iocs\exampleStandalone\exampleStandaloneApp\data\attribute_list.xml)
    # this second file is specified in the .boot file of the ioc and loaded at startup.
    # It is stored in the PV PCO:HDF5:NDAttributesFile, this pointer can be changed via caput
    #---------------------------------------------------------------------------
    # give some feedback
    print('file path is %s but we might save to the filestore instead' % path_name)
    print('file prefix is %s but we might also change this33' % file_name)
    print('file number is %06d' % ep.caget(CP+':'+FT+':FileNumber_RBV'))
    print('pixel clock is %s' % ('95333333 Hz' if not pix_rate else '272250000 Hz'))
    pco_init_done = True
    #---------------------------------------------------------------------------
    # reset ROI to full frame and binning to 1
    pco_roi_reset()
    pco_bin_xy_set(1,1)
    print('binning and ROI reset')
    print('file type is %s' % FT)

################################################################################
# read back current file type
def pco_filetype_get():
    return FT

################################################################################
# take one image and display
def pco_snap_view(exp_time,savename='snap', save_file='live_view/', add_number=False, save_disk = 'camserver', silent=False):
    '''single shot viewer of PCO camera
       Syntax:
          pco_live_view(exp_time=.1,savename='snap',save_file='live_view/', add_number=False)
          exp_time in seconds
          savename = 'snap' is the name of the saved image
          save_file = 'live_view/'- saves to /disk/savefile/savename.h5
          add_number = 'False' - if True it numbers the image using the default pco autoincrementing numbering,
          if False it appends _000000 to the savename
          save_disk = 'camserver' - if 'CTData_incoming' it will save to /CTData_incoming instead
          returns the number of the image taken
          '''
    #---------------------------------------------------------------------------
    # some variables used outside this function
    # global exp_time # no need to make this global?
    #---------------------------------------------------------------------------
    # check if pco_init() was run
    if not pco_init_done:
        print('camera not initialized, please run pco_init() first. Aborting...')
        return
    #---------------------------------------------------------------------------
    # variables used outside this function
    global snap
    #---------------------------------------------------------------------------
    if save_disk == 'CTData_incoming':
        disk_path = 'Z:/'
        print('saving to file store (/CTData_incoming)')
    elif save_disk == 'camserver':
        disk_path = 'D:/camserver/'
        print('saving on camserver')
    else:
        disk_path = 'D:/camserver/'
        print('Youve put something silly as the savedisk so saving to the camserver')


    # store some epics variables
    exp_time_old = ep.caget(CP+':CAM:AcquireTime_RBV')
    averages_old = ep.caget(CP+':CAM:NumExposures_RBV')
    print(('averages old' + str(averages_old)))
    timestamp_mode_old = ep.caget(CP+':CAM:TIMESTAMP_MODE')
    file_path_old = ep.caget(CP+':'+FT+':FilePath_RBV')
    file_name_old = ep.caget(CP+':'+FT+':FileName_RBV')
    image_mode_old = ep.caget(CP+':CAM:ImageMode_RBV')
    acquire_period_old = ep.caget(CP+':CAM:AcquirePeriod_RBV')
    file_write_mode_old = ep.caget(CP+':'+FT+':FileWriteMode_RBV')
    auto_increment_old = ep.caget(CP+':'+FT+':AutoIncrement_RBV')
    file_number_old = ep.caget(CP+':'+FT+':FileNumber_RBV')
    num_capture_old = ep.caget(CP+':'+FT+':NumCapture_RBV')
    #---------------------------------------------------------------------------
    # set epics variables for single acquisition
    if ep.caget(CP+':CAM:Acquire_RBV'):
        ep.caput(CP+':CAM:Acquire',0,wait=True)
    if ep.caget(CP+':CAM:TIMESTAMP_MODE'):
        ep.caput(CP+':CAM:TIMESTAMP_MODE',0) # no timestamp
    if ep.caget(CP+':CAM:ImageMode') != 2:
        ep.caput(CP+':CAM:ImageMode',2) # image mode to continuous
    if ep.caget(CP+':CAM:AcquirePeriod'):
        ep.caput(CP+':CAM:AcquirePeriod',0) # Acquire period, 0 for default
    if ep.caget(CP+':'+FT+':FileWriteMode') != 2:
        ep.caput(CP+':'+FT+':FileWriteMode',2) # stream
    ep.caput(CP+':'+FT+':AutoIncrement',1) # deactivate auto increment file number
    if add_number is False:
        ep.caput(CP+':'+FT+':FileNumber',0) # reset file numbering
    ep.caput(CP+':'+FT+':NumCapture',1) # capture 1 frame per run
    ep.caput(CP+':'+FT+':FilePath',disk_path+save_file) # dump directory for live view files
    ep.caput(CP+':'+FT+':FileName',savename)
    # ep.caput(CP+':CAM:NumExposures',averages)
    ep.caput(CP+':CAM:AcquireTime',exp_time)
    #---------------------------------------------------------------------------
    # capture one image
    if not silent:
        logger.info('Capturing image.')
        logger.info('File type is %s.' % FT)
    ep.caput(CP+':CAM:Acquire',1) # arm camera
    ep.caput(CP+':'+FT+':Capture',1,wait=True) # capture image
    ep.caput(CP+':CAM:Acquire',0) # disarm camera
    #---------------------------------------------------------------------------
    # restore old epics variables
    ep.caput(CP+':CAM:AcquireTime',exp_time_old)
    # ep.caput(CP+':CAM:NumExposures',averages_old)
    # ep.caput(CP+':CAM:TIMESTAMP_MODE',timestamp_mode_old)
    ep.caput(CP+':'+FT+':FilePath',file_path_old)
    ep.caput(CP+':'+FT+':FileName',file_name_old)
    # ep.caput(CP+':CAM:ImageMode',image_mode_old)
    # ep.caput(CP+':CAM:AcquirePeriod',acquire_period_old)
    # ep.caput(CP+':'+FT+':FileWriteMode',file_write_mode_old)
    #ep.caput(CP+':'+FT+':AutoIncrement',auto_increment_old)
    if add_number is False:
        ep.caput(CP+':'+FT+':FileNumber',file_number_old)
    ep.caput(CP+':'+FT+':NumCapture',num_capture_old)
    return ep.caget(CP + ':' + FT + ':FileNumber') - 1



################################################################################
# change ROI settings
def pco_roi_set(x0=None,y0=None,size_x=None,size_y=None,verbose=0):
    '''sets a ROI for the detector
       Syntax:
          pco_roi_set(x0=0,y0=0,size_x=2060,size_y=2048)
          x0,y0 spcify the upper left corner of the ROI
          delta_x,delta_y specify the width in pixels.
          y-ROI must be simmetric with respect to the camera.
          Only specify y0 or size_y, not both.
          Will not change omitted parameters'''
    #---------------------------------------------------------------------------
    # check if pco_init() was run
    if not pco_init_done:
        print('camera not initialized, please run pco_init() first. Aborting...')
        return
    #---------------------------------------------------------------------------
    # get the current settings for ROI and binning
    x0_old = ep.PV(CP+':CAM:MinX_RBV').get()
    y0_old = ep.PV(CP+':CAM:MinY_RBV').get()
    size_x_old = ep.PV(CP+':CAM:SizeX_RBV').get()
    size_y_old = ep.PV(CP+':CAM:SizeY_RBV').get()
    bin_x_old = ep.PV(CP+':CAM:BinX_RBV').get()
    bin_y_old = ep.PV(CP+':CAM:BinY_RBV').get()
    print('x-binning is %d, y-binning is %d' %(bin_x_old,bin_y_old))
    #---------------------------------------------------------------------------
    # Maximum allowed sizes are different from the expected max_size/binning for the x-axis:
    # 2060 for bin 1; 1020 for bin 2; 500 for bin 4
    # use the following formula to calc them:
    # (2080 - 20*binning)/binning
    # !!!
    # y-ROI must be simmetric with respect to the camera
    #---------------------------------------------------------------------------
    # check whether only y0 or size_y was specified, complain otherwise
    if y0 is not None and size_y is not None:
        print('y-ROI must be simmetric with respect to camera')
        print('please only specify y0 OR size_y, not both. Aborting...')
        return
    #---------------------------------------------------------------------------
    # set x0 value
    if x0 is not None:
        # EPICS starts counting at 0
        x0 = x0-1
        # check if value is Valid
        if x0 < 0 or x0 > (2080-20*bin_x_old)/bin_x_old:
            print('x0 out of bounds, aborting...')
            return
        else:
            ep.PV(CP+':CAM:MinX').put(x0)
            if size_x is None:
                # need to readjust size_x accordingly
                size_x = size_x_old - (x0-x0_old)
    #---------------------------------------------------------------------------
    # set y0 value
    if y0 is not None:
        # EPICS starts counting at 0
        y0 = y0-1
        # check if value is Valid
        if y0 < 0 or y0 > 2048/bin_y_old/2:
            print('y0 out of bounds, aborting...')
            return
        else:
            ep.PV(CP+':CAM:MinY').put(y0)
            # need to adjust size_y accordingly
            size_y = 2048/bin_y_old - 2*y0
            ep.PV(CP+':CAM:SizeY').put(size_y)
    #---------------------------------------------------------------------------
    # set size_x value
    if size_x is not None:
        # check if value is Valid
        if size_x < 1 or int(x0 or x0_old) + size_x > (2080-20*bin_x_old)/bin_x_old:
            print('invalid size_x value, aborting...')
            return
        else:
            ep.PV(CP+':CAM:SizeX').put(size_x)
            print('adjusting size x to %d' % size_x)
    #---------------------------------------------------------------------------
    # set size_y value
    if size_y is not None:
        # check if value is Valid
        if size_y < 2 or int(y0 or y0_old) + size_y > 2048/bin_y_old:
            print('invalid size_y value, aborting...')
            return
        else:
            # as y-ROI must be simmetric, need an even value
            # if size_y is odd, make even
            size_y = int(round(size_y/2)*2)
            ep.PV(CP+':CAM:SizeY').put(size_y)
            # need to adjust y0 accordingly
            y0 = (2048/bin_y_old - size_y)/2
            ep.PV(CP+':CAM:MinY').put(y0)
    #---------------------------------------------------------------------------
    # feedback
    if verbose:
        print('new ROI is:')
        print('[%d,%d][x,y] top left corner' % (int(x0 or x0_old)+1,int(y0 or y0_old)+1)) # int(x0 or x0_old) returns x0_old if x0 is None, X0 otherwise
        print('[%d,%d][size_x,size_y]' % (int(size_x or size_x_old),int(size_y or size_y_old)))
        print('y-ROI set to be symmetric with respect to camera')



################################################################################
# reads the current ROI settings
def pco_roi_get(verbose=0):
    '''prints current ROI and binning settings
       Syntax:
          pco_roi_get()'''
    #---------------------------------------------------------------------------
    # check if pco_init() was run
    if not pco_init_done:
        print('camera not initialized, please run pco_init() first. Aborting...')
        return
    #---------------------------------------------------------------------------
    # get the current settings for ROI and binning
    x0_old = ep.PV(CP+':CAM:MinX_RBV').get()
    y0_old = ep.PV(CP+':CAM:MinY_RBV').get()
    size_x_old = ep.PV(CP+':CAM:SizeX_RBV').get()
    size_y_old = ep.PV(CP+':CAM:SizeY_RBV').get()
    bin_x_old = ep.PV(CP+':CAM:BinX_RBV').get()
    bin_y_old = ep.PV(CP+':CAM:BinY_RBV').get()
    #---------------------------------------------------------------------------
    if verbose:
        print('x-binning is %d, y-binning is %d' %(bin_x_old,bin_y_old))
        print('ROI upper left corner is [%d,%d][x,y]' % (x0_old+1,y0_old+1))
        print('ROI size is [%d,%d][x,y]' % (size_x_old,size_y_old))
    return x0_old, y0_old, size_x_old, size_y_old



################################################################################
# resets ROI to full frame, keep binning
def pco_roi_reset():
    '''resets the ROI to full detector, mantains binning
       Syntax:
          pco_roi_reset()'''
    #---------------------------------------------------------------------------
    # check if pco_init() was run
    if not pco_init_done:
        print('camera not initialized, please run pco_init() first. Aborting...')
        return
    #---------------------------------------------------------------------------
    # get the current settings for ROI and binning
    bin_x_old = ep.PV(CP+':CAM:BinX_RBV').get()
    bin_y_old = ep.PV(CP+':CAM:BinY_RBV').get()
    #---------------------------------------------------------------------------
    # set values
    ep.PV(CP+':CAM:MinX').put(0)
    ep.PV(CP+':CAM:MinY').put(0)
    ep.PV(CP+':CAM:SizeX').put((2080-20*bin_x_old)/bin_x_old)
    ep.PV(CP+':CAM:SizeY').put(2048/bin_y_old)
    #---------------------------------------------------------------------------
    print("roi reset")


################################################################################
# returns current biunning of detector
def pco_bin_xy_get(verbose=0):
    '''Returns current binning of camera in x and y'''
    #---------------------------------------------------------------------------
    # check if pco_init() was run
    if not pco_init_done:
        print('camera not initialized, please run pco_init() first. Aborting...')
        return
    #---------------------------------------------------------------------------
    bin_x_old = ep.PV(CP+':CAM:BinX_RBV').get()
    bin_y_old = ep.PV(CP+':CAM:BinY_RBV').get()
    # print 'camera [x,y] binning is []' # NO PRINTED OUTPUT!
    if verbose:
        print('binning is (%d,%d)' % (bin_x_old, bin_y_old))
    return bin_x_old, bin_y_old


################################################################################
# bins detector, mantains current ROI if possible
def pco_bin_xy_set(bin_x,bin_y,verbose=0):
    '''Bins the camera in x and/or y and resets the FOV accordingly
    Try mantaiing current ROI
       Syntax:
          pco_bin_xy_set(binx,biny)
       Binning factors can be 1,2 or 4, no other values are permitted'''
    # the pco.edge behaves a bit oddly when binning. When binning, the size of
    # the new active area must be manually set to a valid value, otherwise the
    # camera throws an error. Valid values are given in the comments to
    # pco_roi_set()
    #---------------------------------------------------------------------------
    # check if pco_init() was run
    if not pco_init_done:
        print('camera not initialized, please run pco_init() first. Aborting...')
        return
    #---------------------------------------------------------------------------
    # get the current settings for ROI and binning
    x0_old = ep.PV(CP+':CAM:MinX_RBV').get()
    y0_old = ep.PV(CP+':CAM:MinY_RBV').get()
    size_x_old = ep.PV(CP+':CAM:SizeX_RBV').get()
    size_y_old = ep.PV(CP+':CAM:SizeY_RBV').get()
    bin_x_old = ep.PV(CP+':CAM:BinX_RBV').get()
    bin_y_old = ep.PV(CP+':CAM:BinY_RBV').get()
    #---------------------------------------------------------------------------
    # check if input parameters are Valid
    bin_valid = [1,2,4]
    if bin_x not in bin_valid:
        print('invalid bin_x value. Valid values are 1,2 or 4. Aborting...')
        return
    if bin_y not in bin_valid:
        print('invalid bin_y value. Valid values are 1,2 or 4. Aborting...')
        return
    #---------------------------------------------------------------------------
    # reset ROI parameters
    conversion_factor_x = float(bin_x)/bin_x_old # might return o if not float (integer division...)
    x0 = int(np.ceil(x0_old/conversion_factor_x))
    size_x = int(min(np.floor(size_x_old/conversion_factor_x),(2080-20*bin_x)/bin_x)) # min() ensures that the maximum allowed active area is selected

    conversion_factor_y = float(bin_y)/bin_y_old
    y0 = int(np.ceil(y0_old/conversion_factor_y))
    size_y = int(np.floor(size_y_old/conversion_factor_y))
    # need to make sure that size_y is still symmetric
    if size_y+2*y0 != 2048/bin_y:
        size_y = 2048/bin_y - 2*y0

    if conversion_factor_x != 1:
        ep.PV(CP+':CAM:MinX').put(x0)
        ep.PV(CP+':CAM:SizeX').put(size_x)
        ep.PV(CP+':CAM:BinX').put(bin_x)
    if conversion_factor_y != 1:
        ep.PV(CP+':CAM:MinY').put(y0)
        ep.PV(CP+':CAM:SizeY').put(size_y)
        ep.PV(CP+':CAM:BinY').put(bin_y)
    #---------------------------------------------------------------------------
    # feedback
    if verbose:
        print('binning is [%d,%d][x,y]' % (ep.PV(CP+':CAM:BinX_RBV').get(),ep.PV(CP+':CAM:BinY_RBV').get()))
        print('ROI origin is [%d,%d][x,y]' % (ep.PV(CP+':CAM:MinX_RBV').get()+1,ep.PV(CP+':CAM:MinY_RBV').get()+1))
        print('ROI size is [%d,%d][x,y]' % (ep.PV(CP+':CAM:SizeX_RBV').get(),ep.PV(CP+':CAM:SizeY_RBV').get()))



################################################################################
# read back pixel clock
def pco_pixelclock_get():
    '''reads the current value of the pixel clock
       returns 0 for 95333333 Hz, 1 for 272250000 Hz'''
    #---------------------------------------------------------------------------
    # check if pco_init() was run
    if not pco_init_done:
        print('camera not initialized, please run pco_init() first. Aborting...')
        return
    #---------------------------------------------------------------------------
    pix_rate = ep.caget(CP+':CAM:PIX_RATE_RBV')
    if pix_rate:
        print('pixel clock is 272250000 Hz')
        return pix_rate
    else:
        print('pixel clock is 95333333 Hz')
        return pix_rate



################################################################################
# set pixel clock
def pco_pixelclock_set(pix_rate):
    '''sets pixel clock:
       0 -->  95333333 Hz
       1 --> 272250000 Hz'''
    #---------------------------------------------------------------------------
    # check if pco_init() was run
    if not pco_init_done:
        print('camera not initialized, please run pco_init() first. Aborting...')
        return
    #---------------------------------------------------------------------------
    # check validity of input
    if pix_rate != 0 and pix_rate != 1:
        print('invalid input. Please input')
        print('0 for  95333333 Hz, or')
        print('1 for 272250000 Hz. Aborting...')
        return
    #---------------------------------------------------------------------------
    # set value
    ep.PV(CP+':CAM:PIX_RATE').put(pix_rate)
    while ep.PV(CP+':CAM:PIX_RATE_RBV').get() != pix_rate: # make sure value was set
        ep.PV(CP+':CAM:PIX_RATE').put(pix_rate)
    pco_pixelclock_get()



################################################################################
# acquire a series of images
def pco_acquire_series(exp_time,no_frames,frames_per_block=100,file_name='pco',path_name='D:/camserver/dump',delay=0,time_stamp=0,pix_rate=0,averages=1):
    '''Acquire a series of images
       Syntax:
           pco_acquire_series(exp_time,no_frames,frames_per_block=100,file_name='pco',path_name='Z:/camserver/dump',delay=0,time_stamp=0,pix_rate=0,averages=1)
           exp_time : exposure time
           no_frames : number of frames to acquire'''
    #---------------------------------------------------------------------------
    # check if pco_init() was run
    if not pco_init_done:
        print('camera not initialized, please run pco_init() first. Aborting...')
        return
    #---------------------------------------------------------------------------
    # check input parameters
    # permitted exp time is between 100 us and 10 s
    if exp_time < 100e-6 or exp_time > 10:
        print('exp. time out of bounds')
        print('permitted exp. time is between 100 us and 10 s')
        print('Aborting...')
        return
    # permitted delay is between 0 s and 1 s
    if delay < 0 or delay > 1:
        print('delay out of bounds')
        print('permitted delay is between 0 s and 1 s')
        print('Aborting...')
        return
    # pix rate
    if pix_rate != 0 and pix_rate != 1:
        print('invalid pixel clock value')
        print('permitted values are 0 and 1')
        print('Aborting...')
        return
    # timestamp, permitted values are 0 - None, 1 - BCD, 2 - BCD+ASCII, 3 ASCII
    if time_stamp not in [0,1,2,3]:
        print('invalid timestamp settings, please select')
        print('0 - None, 1 - BCD, 2 - BCD+ASCII, 3 - ASCII')
        print('Aborting...')
        return
    # averaged frames per image must be integer and larger than 0
    if averages < 1:
        print('invalid number of averaged frames per image %f' % averages)
        print('must be integer >=1, aborting...')
    # check if output directory exists
    path_name_local = path_name[13:] # need to convert windows path to local path
    path_name_local = '/camserver/'+path_name_local
    if not os.path.isdir(path_name_local):
        print('directory %s doesnt exist, creating...' % path_name_local)
        os.makedirs(path_name_local) # recursively creates directories
    # check if directory is empty, warn if otherwise
    if os.listdir(path_name_local):
        toggle_continue = []
        print('ATTENTION! Directory is not empty')
        print('files might be overwritten')
        toggle_continue = input('continue anyway? (y/[n]): ')
        if toggle_continue is '':
            toggle_continue = 'n'
        while toggle_continue != 'y' and toggle_continue != 'n':
            toggle_continue = input('invalid input, pleaqse select "y" or "n":')
        if toggle_continue == 'n':
            print('Aborting...')
            return
    #---------------------------------------------------------------------------
    # most settings should be ok after pco_init(), set remaining ones
    # stop acquisition before changing settings
    # some PVs should be instantiated
    # disarm camera
    PVacquireRBV = ep.PV(CP+':CAM:Acquire_RBV')
    PVacquire = ep.PV(CP+':CAM:Acquire')
    if PVacquireRBV.get():
        PVacquire.put(0)
        while PVacquireRBV.get():
            time.sleep(.5)
            PVacquire.put(0)
            # print "PROBLEM"
    # make sure file number autoincrement is active
    if not ep.caget(CP+':'+FT+':AutoIncrement_RBV'):
        ep.caput(CP+':'+FT+':AutoIncrement',1)
    # average several exposures to get one frame if requested
    averages_old = ep.caget(CP+':CAM:NumExposures_RBV')
    if averages > 1:
        ep.caput(CP+':CAM:NumExposures',averages)
        print('something')
        # ep.caput(CP+':CAM:NumImages',averages)
    # set exp. time
    ep.caput(CP+':CAM:AcquireTime',exp_time)
    # set delay
    ep.caput(CP+':CAM:DELAY_TIME',delay)
    # set pixel clock
    ep.caput(CP+':CAM:PIX_RATE',pix_rate)
    # set frames per file
    PVnumCapture = ep.PV(CP+':'+FT+':NumCapture')
    PVnumCapture.put(frames_per_block)
    # set timestamp
    ep.caput(CP+':CAM:TIMESTAMP_MODE',time_stamp)
    # set file name and directory
    ep.caput(CP+':'+FT+':FileName',file_name)
    ep.caput(CP+':'+FT+':FilePath',path_name)
    # AcquirePeriod tends to change when changing exposure time for some reason
    # needs to be reset to 0
    ep.caput(CP+':CAM:AcquirePeriod',0)
    #---------------------------------------------------------------------------
    # warn user about some odd stuff
    # at slow pixelclock, the fastest acqui time is roughly 30 Hz
    if not pix_rate and (exp_time < 0.03):
        print('ATTENTION, highest frame rate at slow pixel clock is ~30 Hz')
        print('at current exp. time this will increase overhead')
        print('consider switching to fast pixel clock')
        print('however this will slightly increase noise')
    #---------------------------------------------------------------------------
    # get the number of files to write
    no_files = int(no_frames/frames_per_block) # int() should work as floor()
    print("acquiring %d files" % no_files)
    # the last file might be not filled completely, this is handeled later on
    #---------------------------------------------------------------------------
    # set up scan
    PVacquire.put(1) # arm camera
    while not PVacquireRBV.get(): # wait for camera to arm
        print("camera not responding, retrying...")
        time.sleep(.5)
        PVacquire.put(1)
    print('saving to %s/%s' % (path_name,file_name))
    print('exposure time is %f' % ep.caget(CP+':CAM:AcquireTime_RBV'))
    #---------------------------------------------------------------------------
    # loop through blocks
    for ind_file in range(no_files):
        # check that EPICS file numbering corresponds to the correct block
        # while ep.caget(CP+':'+FT+':FileNumber_RBV') != ind_file+1:
        #     print "EPICS file numbering is off, waiting..."
        #     time.sleep(.5)
        print("Acquiring block number %02d of %02d" % (ind_file+1,no_files))
        # for longer acquisition times, putting "wait=True" is not enough. PyEPICS
        # has an internal timeout of 30 (60?) seconds. If exp_time*frames_per_block
        # exceeds this wait time, python will resume and continue with the loop, resulting in
        # errors. In practice python will start sending commands to the camera while
        # it is still acquiring, resulting in odd behaviour. To avoid this use the
        # "use_complete" option from pyepics. This will generate a put_complete callable
        # on the PV, which tells wether the rpcess is complete. Better to create an instance
        # of the PV for this
        PVcapture = ep.PV(CP+':'+FT+':Capture') # create instance of the PV "Capture"
        PVcapture.put(1,use_complete=True) # acquire, also generate a put_complete callable
        # time.sleep(frames_per_block*exp_time) # waiting for the time estimated for acqui to finish actually increases file size for some reason (?)
        # check wether acquisition of the block is done, wait otherwise
        while not PVcapture.put_complete:
            # print "capture not finished, waiting..."
            time.sleep(.5) # maybe wait for a shorter time?
    #---------------------------------------------------------------------------
    # acquire remaining frames if anyway
    no_frames_left = no_frames%frames_per_block
    if no_frames_left:
        PVnumCapture.put(no_frames_left) # set new number of files
        PVcapture.put(1,use_complete=True) # acquire
        time.sleep(no_frames_left*exp_time)
        while not PVcapture.put_complete: # make sure acquisition is done
            time.sleep(.5)
        PVnumCapture.put(frames_per_block) # reset number of frames per block
    print('Acquisition done!')
    # disarm camera --> this should be done automatically
    # print "set Capture to 0..."
    # PVcapture.put(0,wait=True)
    print("Disarming camera...")
    PVacquire.put(0,wait=True) # disarm camera
    while PVacquireRBV.get():
        print('camera not responding, retrying...')
        time.sleep(.5)
        PVacquire.put(0) # disarm camera
    # reset numbering
    print('resetting file number to 1...')
    ep.caput(CP+':'+FT+':FileNumber',1)
    ep.caput(CP+':CAM:NumExposures',averages_old)
    print("Done")


################################################################################
# reads thye binary timestamp in the upper left corner of a projection
def pco_get_timestamp_from_proj(proj,averages=1):
    '''read the BCD timestamp from a projection
       Syntax:
          pco_get_timestamp_from_proj(proj)
       returns a dict with timestamp entries'''
    #---------------------------------------------------------------------------
    # get the pixels_in
    px = proj[0,0:14]/averages
    s = []
    for ind_px in range(len(px)):
        # replace the '0b' and add '0's where needed
        tmp = bin(int(px[ind_px])).replace('0b','')
        while len(tmp) < 8:
            tmp = '0' + tmp
        s.append(int(tmp[:4],2))
        s.append(int(tmp[-4:],2))
    #---------------------------------------------------------------------------
    # parse the string
    # frame_nr, year, month,  day, hour, minute, second,microsecond
    #     %08d, %04d,  %02d, %02d, %02d,   %02d,   %02d,       %06d
    d = (np.ones((8,))*10)**list(range(7,-1,-1)) # creates a vector with powers of
                                           # 10 from 10^7 to 10^0
    time_stamp = {}
    time_stamp['frame_nr'] = sum(d*s[0:8]);
    time_stamp['year'] = sum(d[-4:]*s[8:12]);
    time_stamp['month'] = sum(d[-2:]*s[12:14]);
    time_stamp['day'] = sum(d[-2:]*s[14:16]);
    time_stamp['hour'] = sum(d[-2:]*s[16:18]);
    time_stamp['minute'] = sum(d[-2:]*s[18:20]);
    time_stamp['second'] = sum(d[-2:]*s[20:22]);
    time_stamp['microsecond'] = sum(d[-6:]*s[22:28]);
    #---------------------------------------------------------------------------
    return time_stamp




def pco_acquire_series_logfile(logfile_directory):
    '''Is called from pco_acquire_series, writes some useful info
       to a log file in the same directory'''
    # need timestamp
    # need motor positions (in near future)
    #

    pass



################################################################################
# click on a figure and return the coords of the click
def pco_onclick(event):
    '''this function is needed by pco_xmouse'''
    # print 'x=%d, y=%d' % (event.x,event.y)
    global snap_mousebutton
    snap_mousebutton = event.button
    global snap_xcoord
    snap_xcoord = event.x
    global snap_ycoord
    snap_ycoord = event.y
    print('click!')
    return event.x,event.y
#-------------------------------------------------------------------------------
def pco_xmouse():
    '''returns the coords of click location in the snap view windows
       rightclick will print coords and wait for another click
       leftclick will return coords and end the function'''
    #---------------------------------------------------------------------------
    # check if correct figure exists
    if not fh_snap:
        print('no snap view figure open!')
        return
    #---------------------------------------------------------------------------
    # call clicking on figure
    list_x = [] # store coords
    list_y = []
    # cid = fh_snap.canvas.mpl_connect('button_press_event', pco_onclick)
    # while not snap_mousebutton: # wait for user to click the figure
    #     time.sleep(.5)
    # list_x.append(snap_xcoord)
    # list_y.append(snap_ycoord)
    # #---------------------------------------------------------------------------
    # # check which mouse button was pressed, exit if 1 (LMB), continue if 3 (RMB)
    # if snap_mousebutton == 1:
    #     print 'x = %f' % list_x
    #     print 'y = %f' % list_y
    #     return
    # elif snap_mousebutton == 3:
    while snap_mousebutton == 3:
        cid = fh_snap.canvas.mpl_connect('button_press_event', pco_onclick)
        list_x_len = len(list_x)
        list_x.append(snap_xcoord)
        list_y.append(snap_ycoord)
        if len(list_x) > list_x_len:
            if len(list_x) < 2:
                print('x = %s' % list_x[-1])
                print('y = %s' % list_y[-1])
            else:
                print('x = %s, deltax = %s' % (list_x[-1],float(list_x[-1])-float(list_x[-2])))
                print('y = %s, deltay = %s' % (list_y[-1],float(list_y[-1])-float(list_y[-2])))
    else:
        cid = fh_snap.canvas.mpl_connect('button_press_event', pco_onclick)
        list_x.append(snap_xcoord)
        list_y.append(snap_ycoord)
        print('x = %s, deltax = %s' % (list_x[-1],list_x[-1]-list_x[-2]))
        print('y = %s, deltay = %s' % (list_y[-1],list_y[-1]-list_y[-2]))
        return









# NumCapture --> frames per file
# :CAM:NumImages --> number of files????












################################################################################
# Live view is not running as intended, implement later on (if ever...)
# def pco_live_view(exp_time=.1,cmin=None,cmax=None,CP='PCO',FT='HDF5'):
#     '''Starts a live stream to figure of the detector output.
#        pco_live_view(exp_time=.1,cmin=None,cmax=None,CP="PCO",FT="HDF5")
#        ATTENTION!!, do not start this routine by itself. use
#        pco_live_view_start() and pco_live_view_stop() instead...'''
#     ########################################
#     # set some epics variables
#     if ep.PV(CP+':CAM:Acquire').get():
#         ep.PV(CP+':CAM:Acquire').put(0)
#     if ep.PV(CP+':CAM:TIMESTAMP_MODE').get():
#         ep.PV(CP+':CAM:TIMESTAMP_MODE').put(0) # no timestamp
#     if not ep.PV(CP+':CAM:PIX_RATE').get():
#         ep.PV(CP+':CAM:PIX_RATE').put(1) # fast readout
#     if ep.PV(CP+':CAM:ImageMode').get() != 2:
#         ep.PV(CP+':CAM:ImageMode').put(2) # image mode to continuous
#     if ep.PV(CP+':CAM:AcquirePeriod').get():
#         ep.PV(CP+':CAM:AcquirePeriod').put(0) # Acquire period, 0 for default
#     if ep.PV(CP+':'+FT+':FileWriteMode').get() != 2:
#         ep.PV(CP+':'+FT+':FileWriteMode').put(2) # stream
#     ep.PV(CP+':'+FT+':LazyOpen').put(1) # needed to avoid EPICS wanting to have an image prior to recording
#     ep.PV(CP+':'+FT+':AutoIncrement').put(0) # deactivate auto increment file number
#     ep.PV(CP+':'+FT+':FileNumber').put(0) # reset file numbering
#     ep.PV(CP+':'+FT+':NumCapture').put(1) # capture 1 frame per run
#     ep.PV(CP+':'+FT+':FilePath').put('D:/camserver/live_view') # dup directory for live view files
#     ep.PV(CP+':'+FT+':FileName').put('live')
#     ep.PV(CP+':CAM:AcquireTime').put(exp_time)
#     ep.PV(CP+':CAM:Acquire').put(1)
#
#     ########################################
#     #make a loop that keeps acquiring and displaying frames_per_file
#     while 1 # toggle_start:
#         # capture one frame
#         ep.PV(CP+':'+FT+':Capture').put(1,wait=True)
#         fid_live = h5py.File('/media/sf_camserver/live_view/live_000000.h5','r')
#         live_data = np.squeeze(fid_live['/entry/data/data'])
#         f200 = plt.figure(200)
#         plt.clf()
#         plt.set_cmap('inferno')
#         # set scaling
#         if not cmin:
#             cmin = min(live_data.flatten())
#         if not cmax:
#             cmax = max(live_data.flatten())
#         plt.imshow(live_data,vmin=cmin,vmax=cmax)
#         plt.colorbar()
#         f200.show()
#         f200.canvas.draw()
#         fid_live.close()
#         time.sleep(exp_time*2)

# Functions below not working yet...
# def pco_live_view_start(exp_time=.1,cmin=None,cmax=None,CP='PCO',FT='HDF5'):
#     global toggle_start
#     toggle_start = 1
#     pco_live_view(exp_time,cmin,cmax,CP,FT)
#
# def pco_live_view_stop(exp_time=.1,cmin=None,cmax=None,CP='PCO',FT='HDF5'):
#     global toggle_start
#     toggle_start = 0
#     pco_live_view(exp_time,cmin,cmax,CP,FT)#
