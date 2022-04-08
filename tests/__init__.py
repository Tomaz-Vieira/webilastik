import os
from pathlib import Path, PurePosixPath
import time
from typing import Any, Sequence, Tuple
import uuid

from ndstructs.point5D import Point5D, Shape5D
import numpy as np

from webilastik.annotations.annotation import Annotation, Color
from webilastik.classifiers.pixel_classifier import VigraPixelClassifier
from webilastik.datasink import FsDataSink
from webilastik.datasink.precomputed_chunks_sink import PrecomputedChunksScaleSink
from webilastik.datasource import DataSource
from webilastik.datasource.precomputed_chunks_info import PrecomputedChunksScale, RawEncoder
from webilastik.datasource.skimage_datasource import SkimageDataSource
from webilastik.features.channelwise_fastfilters import GaussianSmoothing, HessianOfGaussianEigenvalues
from webilastik.features.ilp_filter import IlpFilter
from webilastik.filesystem import JsonableFilesystem
from webilastik.filesystem.bucket_fs import BucketFs
from webilastik.filesystem.osfs import OsFs
from webilastik.utility import get_now_string

def get_project_root_dir() -> Path:
    return Path(__name__).parent

def get_sample_c_cells_datasource() -> SkimageDataSource:
    return SkimageDataSource(
        filesystem=OsFs(get_project_root_dir().as_posix()), path=PurePosixPath("public/images/c_cells_1.png")
    )

def get_test_output_osfs() -> OsFs:
    test_dir_path = f"/tmp/webilastik-test-{time.monotonic()}/"
    os.makedirs(test_dir_path, exist_ok=True)
    return OsFs(test_dir_path)

def create_precomputed_chunks_sink(*, shape: Shape5D, dtype: "np.dtype[Any]", chunk_size: Shape5D, fs: "JsonableFilesystem | None" = None) -> FsDataSink:
    return PrecomputedChunksScaleSink(
        filesystem=fs or get_test_output_osfs(),
        info_dir=PurePosixPath(f"{uuid.uuid4()}.precomputed"),
        dtype=dtype,
        num_channels=shape.c,
        scale=PrecomputedChunksScale(
            key=PurePosixPath("some_data"),
            size=(shape.x, shape.y, shape.z),
            resolution=(1,1,1),
            voxel_offset=(0,0,0),
            chunk_sizes=tuple([
                (chunk_size.x, chunk_size.y, chunk_size.z)
            ]),
            encoding=RawEncoder(),
        )
    )

def get_sample_c_cells_pixel_annotations() -> Tuple[Annotation, ...]:
    raw_data_source = get_sample_c_cells_datasource()
    return (
        Annotation.interpolate_from_points(
            voxels=[Point5D.zero(x=140, y=150), Point5D.zero(x=145, y=155)],
            color=Color(r=np.uint8(0), g=np.uint8(0), b=np.uint8(255)),
            raw_data=raw_data_source
        ),
        Annotation.interpolate_from_points(
            voxels=[Point5D.zero(x=238, y=101), Point5D.zero(x=229, y=139)],
            color=Color(r=np.uint8(0), g=np.uint8(0), b=np.uint8(255)),
            raw_data=raw_data_source
        ),
        Annotation.interpolate_from_points(
            voxels=[Point5D.zero(x=283, y=87), Point5D.zero(x=288, y=92)],
            color=Color(r=np.uint8(255), g=np.uint8(0), b=np.uint8(0)),
            raw_data=raw_data_source
        ),
        Annotation.interpolate_from_points(
            voxels=[Point5D.zero(x=274, y=168), Point5D.zero(x=256, y=191)],
            color=Color(r=np.uint8(255), g=np.uint8(0), b=np.uint8(0)),
            raw_data=raw_data_source
        ),
    )

def get_sample_feature_extractors() -> Sequence[IlpFilter]:
    return (
        GaussianSmoothing(sigma=0.3, axis_2d="z"),
        GaussianSmoothing(sigma=0.7, axis_2d="z"),
        GaussianSmoothing(sigma=1.0, axis_2d="z"),
        GaussianSmoothing(sigma=1.6, axis_2d="z"),
        GaussianSmoothing(sigma=3.5, axis_2d="z"),
        GaussianSmoothing(sigma=5.0, axis_2d="z"),
        GaussianSmoothing(sigma=10.0, axis_2d="z"),
        HessianOfGaussianEigenvalues(scale=0.7, axis_2d="z"),
    )

def get_sample_c_cells_pixel_classifier() -> VigraPixelClassifier[IlpFilter]:
    return VigraPixelClassifier.train(
        feature_extractors=get_sample_feature_extractors(),
        annotations=get_sample_c_cells_pixel_annotations(),
    )