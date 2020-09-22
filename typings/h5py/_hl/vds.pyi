"""
This type stub file was generated by pyright.
"""

from collections import namedtuple
from .. import h5, version
from typing import Any, Optional

"""
    High-level interface for creating HDF5 virtual datasets
"""
class VDSmap(namedtuple('VDSmap', ('vspace', 'file_name', 'dset_name', 'src_space'))):
    '''Defines a region in a virtual dataset mapping to part of a source dataset
    '''
    ...


vds_support = False
hdf5_version = version.hdf5_version_tuple[0: 3]
if hdf5_version >= h5.get_config().vds_min_hdf5_version:
    vds_support = True
class VirtualSource(object):
    """Source definition for virtual data sets.

    Instantiate this class to represent an entire source dataset, and then
    slice it to indicate which regions should be used in the virtual dataset.

    path_or_dataset
        The path to a file, or an h5py dataset. If a dataset is given,
        no other parameters are allowed, as the relevant values are taken from
        the dataset instead.
    name
        The name of the source dataset within the file.
    shape
        A tuple giving the shape of the dataset.
    dtype
        Numpy dtype or string.
    maxshape
        The source dataset is resizable up to this shape. Use None for
        axes you want to be unlimited.
    """
    def __init__(self, path_or_dataset, name: Optional[Any] = ..., shape: Optional[Any] = ..., dtype: Optional[Any] = ..., maxshape: Optional[Any] = ...):
        self.path = ...
        self.name = ...
        self.dtype = ...
        self.sel = ...
    
    @property
    def shape(self):
        ...
    
    def __getitem__(self, key):
        ...
    


class VirtualLayout(object):
    """Object for building a virtual dataset.

    Instantiate this class to define a virtual dataset, assign to slices of it
    (using VirtualSource objects), and then pass it to
    group.create_virtual_dataset() to add the virtual dataset to a file.

    This class does not allow access to the data; the virtual dataset must
    be created in a file before it can be used.

    shape
        A tuple giving the shape of the dataset.
    dtype
        Numpy dtype or string.
    maxshape
        The virtual dataset is resizable up to this shape. Use None for
        axes you want to be unlimited.
    """
    def __init__(self, shape, dtype: Optional[Any] = ..., maxshape: Optional[Any] = ...):
        self.shape = ...
        self.dtype = ...
        self.maxshape = ...
        self.sources = ...
    
    def __setitem__(self, key, source):
        ...
    


