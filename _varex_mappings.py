"""
Map varex_constants to DexelaPy values.

This module should be imported only where DexelaPy is present. Will fail otherwise.
"""
import DexelaPy

from ._varex_constants import *


API_map = {
       FullWellModes.Low: DexelaPy.FullWellModes.Low,
       FullWellModes.High: DexelaPy.FullWellModes.High,
       ExposureModes.Expose_and_read: DexelaPy.ExposureModes.Expose_and_read,
       ExposureModes.Sequence_Exposure: DexelaPy.ExposureModes.Sequence_Exposure,
       ExposureModes.Frame_Rate_exposure: DexelaPy.ExposureModes.Frame_Rate_exposure,
       ExposureModes.Preprogrammed_exposure: DexelaPy.ExposureModes.Preprogrammed_exposure,
       Bins.x11: DexelaPy.bins.x11,
       Bins.x12: DexelaPy.bins.x12,
       Bins.x14: DexelaPy.bins.x14,
       Bins.x21: DexelaPy.bins.x21,
       Bins.x22: DexelaPy.bins.x22,
       Bins.x24: DexelaPy.bins.x24,
       Bins.x41: DexelaPy.bins.x41,
       Bins.x42: DexelaPy.bins.x42,
       Bins.x44: DexelaPy.bins.x44,
       Bins.ix22: DexelaPy.bins.ix22,
       Bins.ix44: DexelaPy.bins.ix44,
       Bins.BinningUnknown: DexelaPy.bins.BinningUnknown,
       Derr.SUCCESS: DexelaPy.Derr.SUCCESS,
       Derr.NULL_IMAGE: DexelaPy.Derr.NULL_IMAGE,
       Derr.WRONG_TYPE: DexelaPy.Derr.WRONG_TYPE,
       Derr.WRONG_DIMS: DexelaPy.Derr.WRONG_DIMS,
       Derr.BAD_PARAM: DexelaPy.Derr.BAD_PARAM,
       Derr.BAD_COMMS: DexelaPy.Derr.BAD_COMMS,
       Derr.BAD_TRIGGER: DexelaPy.Derr.BAD_TRIGGER,
       Derr.BAD_COMMS_OPEN: DexelaPy.Derr.BAD_COMMS_OPEN,
       Derr.BAD_COMMS_WRITE: DexelaPy.Derr.BAD_COMMS_WRITE,
       Derr.BAD_COMMS_READ: DexelaPy.Derr.BAD_COMMS_READ,
       Derr.BAD_FILE_IO: DexelaPy.Derr.BAD_FILE_IO,
       Derr.BAD_BOARD: DexelaPy.Derr.BAD_BOARD,
       Derr.OUT_OF_MEMORY: DexelaPy.Derr.OUT_OF_MEMORY,
       Derr.EXPOSURE_FAILED: DexelaPy.Derr.EXPOSURE_FAILED,
       Derr.BAD_BIN_LEVEL: DexelaPy.Derr.BAD_BIN_LEVEL,
       DexImageTypes.Data: DexelaPy.DexImageTypes.Data,
       DexImageTypes.Offset: DexelaPy.DexImageTypes.Offset,
       DexImageTypes.Gain: DexelaPy.DexImageTypes.Gain,
       DexImageTypes.Defect: DexelaPy.DexImageTypes.Defect,
       DexImageTypes.UnknownType: DexelaPy.DexImageTypes.UnknownType,
       ExposureTriggerSource.Ext_neg_edge_trig: DexelaPy.ExposureTriggerSource.Ext_neg_edge_trig,
       ExposureTriggerSource.Internal_Software: DexelaPy.ExposureTriggerSource.Internal_Software,
       ExposureTriggerSource.Ext_Duration_Trig: DexelaPy.ExposureTriggerSource.Ext_Duration_Trig,
       FileType.SMV: DexelaPy.FileType.SMV,
       FileType.TIF: DexelaPy.FileType.TIF,
       FileType.HIS: DexelaPy.FileType.HIS,
       FileType.UNKNOWN: DexelaPy.FileType.UNKNOWN,
       pType.u16: DexelaPy.pType.u16,
       pType.flt: DexelaPy.pType.flt,
       pType.u32: DexelaPy.pType.u32,
       ReadoutModes.ContinuousReadout: DexelaPy.ReadoutModes.ContinuousReadout,
       ReadoutModes.IdleMode: DexelaPy.ReadoutModes.IdleMode
       }
