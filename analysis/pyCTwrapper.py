"""
Wrapping astra-toolbox to keep basic pyCT behaviour
"""
import numpy as np
import multiprocessing
import time
import astra
try:
    from tqdm import tqdm
    use_tqdm = True
except ImportError():
    use_tqdm = False

DEFAULT_POOL_SIZE = int(.75 * multiprocessing.cpu_count())


def _reconstruct_slice(i, sino, sino_id, alg_id, vol_id):
    """
    Worker function for multiprocessing, called from Parallel._bp
    """
    astra.data2d.store(sino_id, sino)
    astra.algorithm.run(alg_id)
    out = astra.data2d.get(vol_id)
    return i, out


def _project_slice(i, vol, vol_id, fp_id, sino_id):
    """
    Worker function for multiprocessing, called from Parallel.project
    """
    astra.data2d.store(vol_id, vol)
    astra.algorithm.run(fp_id)
    out = astra.data2d.get(sino_id)
    return i, out


class Parallel(object):
    def __init__(self, angles, det_N, img_N=None, det_shift=None, pool_size=None):
        """
        Parallel projector

        angles in degrees

        Expected formats are
        volume 2d: (row, column)
        volume 3d: (row, slice, column)
        sinogram 2d: (angle, row)
        sinogram 3d: (angle, slice, row)
        """

        # Starting point: all None
        self.vol_geom = None
        self.proj_geom = None

        self.vol_id = None
        self.sino_id = None
        self.proj_id = None
        self.fp_id = None
        self.bp_id = None
        self.fbp_id = None

        self.is_3d = False

        # Parse and store initial values
        self._angles = angles

        if img_N is None:
            img_N = det_N
        if np.isscalar(img_N):
            assert np.isscalar(det_N)
            self._row_count = img_N
            self._det_count = det_N
            self._slice_count = None
        elif len(img_N) == 2:
            self.is_3d = True
            self._row_count = img_N[0]
            self._slice_count = img_N[1]
            if np.isscalar(det_N):
                self._det_count = det_N
            else:
                assert det_N[1] == self._slice_count
                self._det_count = det_N[0]
        self._det_shift = det_shift

        # Create objects
        self._update_geometry()

        # This will create a multiprocessing pool
        # self.pool_size = DEFAULT_POOL_SIZE

        # For now default is create pool only when explicitely requested.
        self.pool_size = pool_size

    @staticmethod
    def tomo_filter(N, filter='ram-lak', dpc=False):
        f = np.fft.fftfreq(N)
        omega = 2 * np.pi * f
        if dpc:
            flt = -1j * np.sign(f) / np.pi
        else:
            flt = 2 * np.abs(f)
        if filter == 'ram-lak' or filter == 'ramp' or ((filter == 'hilbert') and dpc):
            return flt
        elif filter == "shepp-logan":
            flt[1:] = flt[1:] * np.sin(omega[1:]) / omega[1:]
        elif filter == "cosine":
            flt *= np.cos(omega)
        elif filter == "hamming":
            flt *= (0.54 + 0.46 * np.cos(omega / 2))
        elif filter == "hann":
            flt *= (1 + np.cos(omega / 2)) / 2
        else:
            raise ValueError("Unknown filter: %s" % filter)
        return flt

    def _update_geometry(self):
        """
        Update astra vol_geom and proj_geom
        """
        # Update of proj_goem possible only if angles and detector pixel count has been defined
        if self._angles is not None and self._det_count is not None:
            self.proj_geom = {'type': 'parallel',
                              'DetectorWidth': 1.0,
                              'DetectorCount': self._det_count,
                              'ProjectionAngles': self._angles}

            # If the projector center shift is non-zero, apply this
            if (self._det_shift is not None) and (self._det_shift != 0):
                self.proj_geom = astra.geom_postalignment(self.proj_geom, self._det_shift)
        else:
            self.proj_geom = None

        # Update of vol_geom possible only if volume size is known
        if self._row_count is not None:
            self.vol_geom = astra.create_vol_geom(self._row_count, self._row_count)
        else:
            self.vol_geom = None
        self._create_ids()

    def _del_ids(self):

        if self.vol_id is not None:
            astra.data2d.delete(self.vol_id)
            self.vol_id = None
        if self.sino_id is not None:
            astra.data2d.delete(self.sino_id)
            self.sino_id = None
        if self.proj_id is not None:
            astra.projector.delete(self.proj_id)
            self.proj_id = None
        if self.fp_id is not None:
            astra.algorithm.delete(self.fp_id)
            self.fp_id = None
        if self.bp_id is not None:
            astra.algorithm.delete(self.bp_id)
            self.bp_id = None
        if self.fbp_id is not None:
            astra.algorithm.delete(self.fbp_id)
            self.fbp_id = None
        return

    def _create_ids(self):
        """
        Generate all astra objects.
        """

        if self.vol_geom is None or self.proj_geom is None:
            # Maybe better to check if related ids exist and delete objects accordingly
            return

        self.vol_id = astra.data2d.create('-vol', self.vol_geom)
        self.sino_id = astra.data2d.create('-sino', self.proj_geom)
        self.proj_id = astra.create_projector('linear', self.proj_geom, self.vol_geom)

        # Forward projection
        cfg = astra.astra_dict('FP')
        cfg['ProjectorId'] = self.proj_id
        cfg['ProjectionDataId'] = self.sino_id
        cfg['VolumeDataId'] = self.vol_id
        self.fp_id = astra.algorithm.create(cfg)

        # Forward projection
        cfg = astra.astra_dict('BP')
        cfg['ProjectorId'] = self.proj_id
        cfg['ProjectionDataId'] = self.sino_id
        cfg['ReconstructionDataId'] = self.vol_id
        self.bp_id = astra.algorithm.create(cfg)

        # Filtered backprojection
        cfg = astra.astra_dict('FBP')
        cfg['ReconstructionDataId'] = self.vol_id
        cfg['ProjectionDataId'] = self.sino_id
        cfg['ProjectorId'] = self.proj_id
        self.fbp_id = astra.algorithm.create(cfg)

    def _bp(self, sino, algo='BP'):
        """
        Run FBP or BP algorithm

        sino is (angle, row) or (angle, slice, row)
        """
        if self.proj_geom is None or self.vol_geom is None:
            sh = sino.shape
            assert sh[0] == len(self._angles)
            if self._det_count is None:
                self._det_count = sh[-1]
            if self._row_count is None:
                self._row_count = sh[-1]
            if len(sh) == 2:
                self._slice_count = None
            elif len(sh) == 3:
                self._slice_count = sh[1]

            self._update_geometry()
            if self.proj_geom is None or self.vol_geom is None:
                raise RuntimeError('Some parameters are missing')

        if algo == 'BP':
            alg_id = self.bp_id
        elif algo == 'FBP':
            alg_id = self.fbp_id
        else:
            raise RuntimeError('Unknown algorithm %s' % algo)

        if self.is_3d:
            out = np.empty(shape=(self._row_count, self._slice_count, self._row_count))
            if self.pool is None:
                print('Warning not using multiprocessing (set pool_size to change this)')
                rng = list(range(self._slice_count))
                if use_tqdm: rng = tqdm(rng)
                for i in rng:
                    astra.data2d.store(self.sino_id, sino[:, i, :])
                    astra.algorithm.run(alg_id)
                    out[:, i, :] = astra.data2d.get(self.vol_id)
                return out

            # Multiprocessing
            # Start all tasks
            all_workers = [self.pool.apply_async(_reconstruct_slice, (i, sino[:, i, :], self.sino_id, alg_id, self.vol_id)) for i in range(self._slice_count)]

            # Wait for results
            if use_tqdm:
                pbar = tqdm(total=self._slice_count)
                done = 0
                while True:
                    d = sum(future.ready() for future in all_workers)
                    pbar.update(d - done)
                    done = d
                    if d == self._slice_count:
                        break
                    time.sleep(0.1)
                pbar.close()
            else:
                while not all(future.ready() for future in all_workers):
                    time.sleep(0.1)

            # Collect results
            for future in all_workers:
                if not future.successful():
                    raise RuntimeError("Something went wrong")
                i, out_slice = future.get()
                out[:, i, :] = out_slice
            return out
        else:
            astra.data2d.store(self.sino_id, sino)
            astra.algorithm.run(alg_id)
            return astra.data2d.get(self.vol_id)

    def fbp(self, sino, filter='ramp', dpc=False):
        """
        Run FBP algorithm

        sino is (angle, row) or (angle, slice, row)
        filter is one of 'ramp' (or 'ram-lak'), 'shepp-logan', 'cosine', 'hann', 'hamming'
        if dpc=True, use a Hilbert filter instead of ramp filter.
        """
        if (filter == 'ramp' or filter == 'ram-lak') and not dpc:
            # This is Astra's default - probably faster?
            return self._bp(sino, 'FBP')
        else:
            N2 = 1 << (self._det_count-1).bit_length()
            flt = self.tomo_filter(N2, filter=filter, dpc=dpc)
            sino_filtered = np.real(np.fft.ifft(flt * np.fft.fft(sino, n=N2, axis=-1), axis=-1))[..., :self._det_count]
            return self.backproject(sino_filtered) * np.pi / (2 * len(self._angles))

    def backproject(self, sino):
        """
        Apply backprojection to input volume
        """
        return self._bp(sino, 'BP')

    def project(self, vol):
        """
        Apply forward projection to input volume

        vol is (row, column) or (row, slice, column)
        """
        if self.proj_geom is None or self.vol_geom is None:
            raise RuntimeError('Some parameters are missing')
        if self.is_3d:
            out = np.empty(shape=(len(self._angles), self._slice_count, self._det_count))
            if self.pool is None:
                print('Warning not using multiprocessing (set pool_size to change this)')
                rng = list(range(self._slice_count))
                if use_tqdm: rng = tqdm(rng)
                for i in rng:
                    astra.data2d.store(self.vol_id, vol[:, i, :])
                    astra.algorithm.run(self.fp_id)
                    out[:, i, :] = astra.data2d.get(self.sino_id)
                return out

            # Multiprocessing
            # Start all tasks
            all_workers = [self.pool.apply_async(_project_slice, (i, vol[:, i, :], self.vol_id, self.fp_id, self.sino_id)) for i in range(self._slice_count)]

            # Wait for results
            if use_tqdm:
                pbar = tqdm(total=self._slice_count)
                done = 0
                while True:
                    d = sum(future.ready() for future in all_workers)
                    pbar.update(d - done)
                    done = d
                    if d == self._slice_count:
                        break
                    time.sleep(0.1)
                pbar.close()
            else:
                while not all(future.ready() for future in all_workers):
                    time.sleep(0.1)

            # Collect results
            for future in all_workers:
                if not future.successful():
                    raise RuntimeError("Something went wrong")
                i, out_slice = future.get()
                out[:, i, :] = out_slice
            return out
        else:
            astra.data2d.store(self.vol_id, vol)
            astra.algorithm.run(self.fp_id)
            return astra.data2d.get(self.sino_id)

    def __del__(self):
        self._del_ids()
        return

    def _create_pool(self):
        """
        Create (or recreate) multiprocessing pool.
        """
        if self._pool_size is None:
            self.pool = None
            return
        self.pool = multiprocessing.Pool(processes=self._pool_size)

    @property
    def angles(self):
        return self._angles

    @property
    def img_volume_size(self):
        if self.is_3d:
            return self._row_count, self._slice_count
        else:
            return self._row_count

    @property
    def det_N(self):
        if self.is_3d:
            return self._det_count, self._slice_count
        else:
            return self._det_count

    @property
    def det_shift(self):
        return self._det_shift

    @det_shift.setter
    def det_shift(self, value):
        self._del_ids()
        self._det_shift = value
        self._update_geometry()

    @property
    def pool_size(self):
        return self._pool_size

    @pool_size.setter
    def pool_size(self, value):
        self._pool_size = value
        self._create_pool()


class Fan(object):
    def __init__(self, angles, det_N, det_p, dist_sr, dist_rd, img_N=None, img_p=None, det_shift=None):
        """
        Fan beam projectors

        angles:
        psize: pixel size in millimetres (det_width)
        det_N: width of projection (number of pixels) (det_count)
        dist_sr: distance between the source and the center of rotation (in mm)
        dist_rd: distance between the center of rotation and the detector array (in mm)

        :param angles: projection angles in radians
        :param det_N: width of projection (number of pixels)
        :param det_p: detector pixel width (mm)
        :param dist_sr: distance source to rotation axis (mm)
        :param dist_rd: distance rotation axis to detector (mm)
        :param img_N: reconstruction width (number of pixels)
        :param img_p: reconsttruction voxel size (mm)
        :param det_shift: shift in axis of rotation
        """

        # Starting point: all None
        self.vol_geom = None
        self.proj_geom = None

        self.vol_id = None
        self.sino_id = None
        self.proj_id = None
        self.fp_id = None
        self.bp_id = None
        self.fbp_id = None

        self.is_3d = False

        self._angles = angles

        # Compute magnification
        M = (dist_rd + dist_sr) / dist_sr

        self.det_p = det_p
        self.dist_rd = dist_rd
        self.dist_sr = dist_sr
        self.M = M

        # Default voxel size is demagnified detector size
        if img_p is None:
            self.img_p = det_p / M
        else:
            self.img_p = img_p

        # Default reconstruction width is full field of view
        if img_N is None:
            img_w = dist_sr * det_N * det_p / (.5*det_N*det_p + dist_sr + dist_rd)
            self.img_N = int(np.ceil(img_w / self.img_p))
        else:
            self.img_N = img_N

        # Store renormalised values
        self._psize = det_p / self.img_p
        self._dist_rd = dist_rd / self.img_p
        self._dist_sr = dist_sr / self.img_p

        # 3D stuff unsupported for now
        self._row_count = self.img_N
        self._det_count = det_N
        self._slice_count = None

        print(("""
        row_count : {0._row_count}
        det_count : {0._det_count}
        psize : {0._psize}
        dist_sr : {0._dist_sr}
        dist_rd : {0._dist_rd}
        """.format(self)))

        """
        if np.isscalar(det_N):
            self._row_count = det_N
            self._det_count = det_N
            self._slice_count = None
        elif len(det_N) == 2:
            self.is_3d = True
            self._row_count = det_N[0]
            self._slice_count = det_N[1]
            self._det_count = det_N[0]
        """

        self._det_shift = det_shift if det_shift is not None else None

        # Create objects
        self._update_geometry()

    def _update_geometry(self):
        """
        Update astra vol_geom and proj_geom
        """
        # Update of proj_goem possible only if angles and detector pixel count has been defined
        if self._angles is not None and self._det_count is not None:
            self.proj_geom = {'type': 'fanflat',
                              'DetectorWidth': self._psize,
                              'DetectorCount': self._det_count,
                              'ProjectionAngles': self._angles,
                              'DistanceOriginSource': self._dist_sr,
                              'DistanceOriginDetector': self._dist_rd}

            # If the projector center shift is non-zero, apply this
            if (self._det_shift is not None) and (self._det_shift != 0):
                self.proj_geom = astra.geom_postalignment(self.proj_geom, self._det_shift)
        else:
            self.proj_geom = None

        # Update of vol_geom possible only if volume size is known
        if self._row_count is not None:
            self.vol_geom = astra.create_vol_geom(self._row_count, self._row_count)
        else:
            self.vol_geom = None
        self._create_ids()

    def _del_ids(self):

        if self.vol_id is not None:
            astra.data2d.delete(self.vol_id)
            self.vol_id = None
        if self.sino_id is not None:
            astra.data2d.delete(self.sino_id)
            self.sino_id = None
        if self.proj_id is not None:
            astra.projector.delete(self.proj_id)
            self.proj_id = None
        if self.fp_id is not None:
            astra.algorithm.delete(self.fp_id)
            self.fp_id = None
        if self.bp_id is not None:
            astra.algorithm.delete(self.bp_id)
            self.bp_id = None
        if self.fbp_id is not None:
            astra.algorithm.delete(self.fbp_id)
            self.fbp_id = None
        return

    def _create_ids(self):
        """
        Generate all astra objects.
        """

        if self.vol_geom is None or self.proj_geom is None:
            # Maybe better to check if related ids exist and delete objects accordingly
            return

        self.vol_id = astra.data2d.create('-vol', self.vol_geom)
        self.sino_id = astra.data2d.create('-sino', self.proj_geom)
        self.proj_id = astra.create_projector('line_fanflat', self.proj_geom, self.vol_geom)
        #self.proj_id = astra.create_projector('strip_fanflat', self.proj_geom, self.vol_geom)

        # Forward projection
        cfg = astra.astra_dict('FP')
        cfg['ProjectorId'] = self.proj_id
        cfg['ProjectionDataId'] = self.sino_id
        cfg['VolumeDataId'] = self.vol_id
        self.fp_id = astra.algorithm.create(cfg)

        # Forward projection
        cfg = astra.astra_dict('BP')
        cfg['ProjectorId'] = self.proj_id
        cfg['ProjectionDataId'] = self.sino_id
        cfg['ReconstructionDataId'] = self.vol_id
        self.bp_id = astra.algorithm.create(cfg)

        # Filtered backprojection
        cfg = astra.astra_dict('FBP')
        cfg['ReconstructionDataId'] = self.vol_id
        cfg['ProjectionDataId'] = self.sino_id
        cfg['ProjectorId'] = self.proj_id
        self.fbp_id = astra.algorithm.create(cfg)

    def _bp(self, sino, algo='BP'):
        """
        Run FBP or BP algorithm

        sino is (angle, row) or (angle, slice, row)
        """
        if self.proj_geom is None or self.vol_geom is None:
            sh = sino.shape
            assert sh[0] == len(self._angles)
            if self._det_count is None:
                self._det_count = sh[-1]
            if self._row_count is None:
                self._row_count = sh[-1]
            if len(sh) == 2:
                self._slice_count = None
            elif len(sh) == 3:
                self._slice_count = sh[1]

            self._update_geometry()
            if self.proj_geom is None or self.vol_geom is None:
                raise RuntimeError('Some parameters are missing')

        if algo == 'BP':
            alg_id = self.bp_id
        elif algo == 'FBP':
            alg_id = self.fbp_id
        else:
            raise RuntimeError('Unknown algorithm %s' % algo)

        if self.is_3d:
            out = np.empty(shape=(self._row_count, self._slice_count, self._row_count))
            for i in range(self._slice_count):
                astra.data2d.store(self.sino_id, sino[:, i, :])
                astra.algorithm.run(alg_id)
                out[:, i, :] = astra.data2d.get(self.vol_id)
            return out
        else:
            astra.data2d.store(self.sino_id, sino)
            astra.algorithm.run(alg_id)
            return astra.data2d.get(self.vol_id)

    def fbp(self, sino):
        """
        Run FBP algorithm

        sino is (angle, row) or (angle, slice, row)
        """
        return self._bp(sino, 'FBP')

    def backproject(self, sino):
        """
        Apply backprojection to input volume
        """
        return self._bp(sino, 'BP')

    def project(self, vol):
        """
        Apply forward projection to input volume

        vol is (row, column) or (row, slice, column)
        """
        if self.proj_geom is None or self.vol_geom is None:
            raise RuntimeError('Some parameters are missing')
        if self.is_3d:
            out = np.empty(shape=(len(self._angles), self._slice_count, self._det_count))
            for i in range(self._slice_count):
                astra.data2d.store(self.vol_id, vol[:, i, :])
                astra.algorithm.run(self.fp_id)
                out[:, i, :] = astra.data2d.get(self.sino_id)
            return out
        else:
            astra.data2d.store(self.vol_id, vol)
            astra.algorithm.run(self.fp_id)
            return astra.data2d.get(self.sino_id)

    def __del__(self):
        self._del_ids()
        return

    @property
    def angles(self):
        return self._angles

    @property
    def img_volume_size(self):
        if self.is_3d:
            return self._row_count, self._slice_count
        else:
            return self._row_count

    @property
    def det_N(self):
        if self.is_3d:
            return self._det_count, self._slice_count
        else:
            return self._det_count

    @property
    def det_shift(self):
        return self._det_shift

    @det_shift.setter
    def det_shift(self, value):
        self._del_ids()
        self._det_shift = value
        self._update_geometry()


