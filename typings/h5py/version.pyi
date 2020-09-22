"""
This type stub file was generated by pyright.
"""

import sys
import numpy
from collections import namedtuple
from . import h5 as _h5

"""
    Versioning module for h5py.
"""
_H5PY_VERSION_CLS = namedtuple("_H5PY_VERSION_CLS", "major minor bugfix pre post dev")
hdf5_built_version_tuple = _h5.HDF5_VERSION_COMPILED_AGAINST
version_tuple = _H5PY_VERSION_CLS(2, 10, 0, None, None, None)
version = "{0.major:d}.{0.minor:d}.{0.bugfix:d}".format(version_tuple)
if version_tuple.pre is not None:
    ...
if version_tuple.post is not None:
    ...
if version_tuple.dev is not None:
    ...
hdf5_version_tuple = _h5.get_libversion()
hdf5_version = "%d.%d.%d" % hdf5_version_tuple
api_version_tuple = (1, 8)
api_version = "%d.%d" % api_version_tuple
info = """\
Summary of the h5py configuration
---------------------------------

h5py    %(h5py)s
HDF5    %(hdf5)s
Python  %(python)s
sys.platform    %(platform)s
sys.maxsize     %(maxsize)s
numpy   %(numpy)s
""" % { 'h5py': version,'hdf5': hdf5_version,'python': sys.version,'platform': sys.platform,'maxsize': sys.maxsize,'numpy': numpy.__version__ }
