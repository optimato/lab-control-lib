"""
Enumeration of the Varex DexelaPy constants.
"""

__all__ = ['FullWellModes', 'ExposureModes', 'Bins', 'Derr', 'DexImageTypes', 'ExposureTriggerSource', 'FileType',
           'pType', 'ReadoutModes']


def next_k():
    """helper function to assign an incrementing integer."""
    next_k.k += 1
    return next_k.k-1


next_k.k = 0


class FullWellModes:
    # The low noise reduced dynamic range mode
    Low = next_k()
    # The normal full well mode
    High = next_k()


class ExposureModes:
    # The detector should clear the sensor and wait for exposure time to pass
    # before reading the detector image.
    # -------
    # The detector will send a single frame for each trigger it receives
    Expose_and_read = next_k()

    # The detector should take a sequence of images with no gaps.
    # -------
    # The detector will send a pre-configured number of frames for each trigger
    # it receives. Each frame will have an identical exposure time (set using the
    # SetExposureTime method). The number of frames can be set using the
    # SetNumOfExposures method. There will be no gap between the images.
    Sequence_Exposure = next_k()

    # The detector should take a sequence of images with a specified gap no
    # less than the minimum exposure time for the bin level.
    # ------
    # Similar to Sequence_Exposure except each image will have a
    # pre-configured gap time between frames. The gap-time can be set using
    # the SetGapTime method and will be a minimum of 1 read-out period.
    Frame_Rate_exposure = next_k()

    # The detector should take a number of images with preset exposure times
    # without a gap.
    # -------
    # The detector will send up to 4 frames for each trigger it receives. Each
    # frame can have a different exposure time and there will be no gap
    # between the images. The exposure times can be set using the
    # SetPreProgrammedExposureTimesMethod.
    Preprogrammed_exposure = next_k()


class Bins:
    x11 = next_k()     # Unbinned
    x12 = next_k()     # Binned vertically by 2
    x14 = next_k()     # Binned vertically by 4
    x21 = next_k()     # Binned horizontally by 2
    x22 = next_k()     # Binned horizontally by 2 and vertically by 2
    x24 = next_k()     # Binned horizontally by 2 and vertically by 4
    x41 = next_k()     # Binned horizontally by 4
    x42 = next_k()     # Binned horizontally by 4 and vertically by 2
    x44 = next_k()     # Binned horizontally by 4 and vertically by 4
    ix22 = next_k()    # Digital 2x2 binning
    ix44 = next_k()   # Digital 4x4 binning

    # Indicates that the binning mode is not known
    BinningUnknown = next_k()


class Derr:
    SUCCESS = next_k()         # The operation was successful
    NULL_IMAGE = next_k()      # The image pointer was NULL
    WRONG_TYPE = next_k()      # The image pixel type was wrong for the operation requested
    WRONG_DIMS = next_k()      # The image dimensions were wrong for the operation requested
    BAD_PARAM = next_k()       # One or more parameters were incorrect
    BAD_COMMS = next_k()       # The communications channel is not open or could not be opened
    BAD_TRIGGER = next_k()     # An invalid trigger source was requested
    BAD_COMMS_OPEN = next_k()  # The communications channel failed to open
    BAD_COMMS_WRITE = next_k() # A failure in a detector write command occurred
    BAD_COMMS_READ = next_k()  # A failure in a detector read command occurred
    BAD_FILE_IO = next_k()     # An error occurred opening or reading from a file
    BAD_BOARD = next_k()       # The software failed to open the PC driver or frame grabber
    OUT_OF_MEMORY = next_k()   # A function call was not able to reserve the memory it required
    EXPOSURE_FAILED = next_k() # Exposure Acquisition failed
    BAD_BIN_LEVEL = next_k()   # Incorrect bin level specified


class DexImageTypes:
    Data = next_k()        # A data image
    Offset = next_k()      # An offset (dark) image
    Gain = next_k()        # An gain (flood) image
    Defect = next_k()      # A defect-map image
    UnknownType = next_k() # The type of the image is not known


class ExposureTriggerSource:
    Ext_neg_edge_trig = next_k()
    Internal_Software = next_k()
    Ext_Duration_Trig = next_k()


class FileType:
    SMV = next_k()
    TIF = next_k()
    HIS = next_k()
    UNKNOWN = next_k()


class pType:
    u16 = next_k()     # A pixel type of 16-bit unsigned short
    flt = next_k()     # A pixel type of 32-bit floating point
    u32 = next_k()     # A pixel type of 32-bit unsigned int


class ReadoutModes:
    # The sensor is continuously read-out using the minimum read-out time.
    # On request an image will be transmitted. A frame request can be an
    # external trigger pulse, internal trigger or software trigger
    ContinuousReadout = next_k()

    # The sensor is only read out (using the minimum frame time) on request.
    # The read-out will be followed by the transmission of the image. A frame
    # request can be an external trigger pulse, internal trigger or software
    # trigger
    IdleMode = next_k()
