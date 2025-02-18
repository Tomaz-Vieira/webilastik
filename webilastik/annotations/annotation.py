from concurrent.futures import ThreadPoolExecutor
from typing import List, Sequence, Mapping, Tuple, Dict, Iterable, Sequence, Any, Optional

import numpy as np
from ndstructs import Interval5D, Point5D, Shape5D
from ndstructs import Array5D, All, ScalarData, StaticLine
from ndstructs.utils.json_serializable import JsonObject, JsonValue, ensureJsonArray, ensureJsonInt, ensureJsonObject, ensureJsonString

from webilastik.datasource import DataSource, DataRoi
from webilastik.features.feature_extractor import FeatureExtractor, FeatureData


class Color:
    def __init__(
        self,
        r: np.uint8 = np.uint8(0),
        g: np.uint8 = np.uint8(0),
        b: np.uint8 = np.uint8(0),
        a: np.uint8 = np.uint8(255),
        name: str = "",
    ):
        self.r = r
        self.g = g
        self.b = b
        self.a = a
        self.name = name or f"Label {self.rgba}"

    @classmethod
    def from_json_data(cls, data: JsonValue) -> "Color":
        data_dict = ensureJsonObject(data)
        return Color(
            r=np.uint8(ensureJsonInt(data_dict.get("r", 0))),
            g=np.uint8(ensureJsonInt(data_dict.get("g", 0))),
            b=np.uint8(ensureJsonInt(data_dict.get("b", 0))),
            a=np.uint8(ensureJsonInt(data_dict.get("a", 255))),
        )

    def to_json_data(self) -> JsonObject:
        return {
            "r": int(self.r),
            "g": int(self.g),
            "b": int(self.b),
            "a": int(self.a),
        }

    @classmethod
    def from_channels(cls, channels: List[np.uint8], name: str = "") -> "Color":
        if len(channels) == 0 or len(channels) > 4:
            raise ValueError(f"Cannnot create color from {channels}")
        if len(channels) == 1:
            channels = [channels[0], channels[0], channels[0], np.uint8(255)]
        return cls(r=channels[0], g=channels[1], b=channels[2], a=channels[3], name=name)

    @property
    def rgba(self) -> Tuple[np.uint8, np.uint8, np.uint8, np.uint8]:
        return (self.r, self.g, self.b, self.a)

    @property
    def q_rgba(self) -> int:
        return sum(c * (16 ** (3 - idx)) for idx, c in enumerate(self.rgba))

    @property
    def ilp_data(self) -> np.ndarray:
        return np.asarray(self.rgba, dtype=np.int64)

    def __hash__(self):
        return hash(self.rgba)

    def __eq__(self, other: object) -> bool:
        return not isinstance(other, Color) or self.rgba == other.rgba

    @classmethod
    def sort(cls, colors: Iterable["Color"]) -> List["Color"]:
        return sorted(colors, key=lambda c: c.q_rgba)

    @classmethod
    def create_color_map(cls, colors: Iterable["Color"]) -> Dict["Color", np.uint8]:
        return {color: np.uint8(idx + 1) for idx, color in enumerate(cls.sort(set(colors)))}


class FeatureSamples(FeatureData, StaticLine):
    """A multi-channel array with a single spacial dimension, with each channel representing a feature calculated on
    top of an annotated pixel. Features are assumed to be relative to a single label (annotation color)"""

    @classmethod
    def create(cls, annotation: "Annotation", data: FeatureData):
        samples = data.sample_channels(annotation.as_mask()) #type: ignore
        return cls.fromArray5D(samples)

    @property
    def X(self) -> np.ndarray:
        return self.linear_raw()

    def get_y(self, label_class: np.uint8) -> np.ndarray:
        return np.full((self.shape.volume, 1), label_class, dtype=np.uint32)


class AnnotationOutOfBounds(Exception):
    def __init__(self, annotation_roi: Interval5D, raw_data: DataSource):
        super().__init__(f"Annotation roi {annotation_roi} exceeds bounds of raw_data {raw_data}")


class Annotation(ScalarData):
    """User annotation attached to the raw data onto which they were drawn"""

    def __hash__(self):
        return hash((self._data.tobytes(), self.color))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Annotation):
            return False
        return self.color == other.color and bool(np.all(self._data == other._data))

    def __init__(
        self, arr: np.ndarray, *, axiskeys: str, location: Point5D = Point5D.zero(), color: Color, raw_data: DataSource
    ):
        super().__init__(arr.astype(bool), axiskeys=axiskeys, location=location)
        if not raw_data.interval.contains(self.interval):
            raise AnnotationOutOfBounds(annotation_roi=self.interval, raw_data=raw_data)
        self.color = color
        self.raw_data = raw_data

    def rebuild(self, arr: np.ndarray, *, axiskeys: str, location: Point5D = None) -> "Annotation":
        location = self.location if location is None else location
        return self.__class__(arr, axiskeys=axiskeys, location=location, color=self.color, raw_data=self.raw_data)

    @classmethod
    def interpolate_from_points(cls, color: Color, voxels: Sequence[Point5D], raw_data: DataSource):
        start = Point5D.min_coords(voxels)
        stop = Point5D.max_coords(voxels) + 1  # +1 because slice.stop is exclusive, but max_point isinclusive
        scribbling_roi = Interval5D.create_from_start_stop(start=start, stop=stop)
        if scribbling_roi.shape.c != 1:
            raise ValueError(f"Annotations must not span multiple channels: {voxels}")
        scribblings = Array5D.allocate(scribbling_roi, dtype=np.dtype(bool), value=False)

        anchor = voxels[0]
        for voxel in voxels:
            for interp_voxel in anchor.interpolate_until(voxel):
                scribblings.paint_point(point=interp_voxel, value=True)
            anchor = voxel

        return cls(scribblings._data, axiskeys=scribblings.axiskeys, color=color, raw_data=raw_data, location=start)

    @classmethod
    def from_json_value(cls, data: JsonValue) -> "Annotation":
        data_dict = ensureJsonObject(data)
        raw_voxels = ensureJsonArray(data_dict.get("voxels"))
        voxels : Sequence[Point5D] = [Point5D.from_json_value(raw_voxel) for raw_voxel in raw_voxels]

        color = Color.from_json_data(data_dict.get("color"))
        raw_data = DataSource.from_json_value(data_dict.get("raw_data"))

        start = Point5D.min_coords(voxels)
        stop = Point5D.max_coords(voxels) + 1  # +1 because slice.stop is exclusive, but max_point isinclusive
        scribbling_roi = Interval5D.create_from_start_stop(start=start, stop=stop)
        if scribbling_roi.shape.c != 1:
            raise ValueError(f"Annotations must not span multiple channels: {voxels}")
        scribblings = Array5D.allocate(scribbling_roi, dtype=np.dtype(bool), value=False)

        for voxel in voxels:
            scribblings.paint_point(point=voxel, value=True)

        return cls(scribblings._data, axiskeys=scribblings.axiskeys, color=color, raw_data=raw_data, location=start)

    def to_json_data(self) -> JsonObject:
        voxels : List[Point5D] = []

        # FIXME: annotation should probably not be an Array6D
        for x, y, z in zip(*self.raw("xyz").nonzero()): # type: ignore
            voxels.append(Point5D(x=x, y=y, z=z) + self.location)

        return {
            "color": self.color.to_json_data(),
            "raw_data": self.raw_data.to_json_value(),
            "voxels": tuple(vx.to_json_value() for vx in voxels),
        }

    def get_feature_samples(self, feature_extractor: FeatureExtractor) -> FeatureSamples:
        interval_under_annotation = self.interval.updated(c=self.raw_data.interval.c)

        def make_samples(data_tile: DataRoi) -> FeatureSamples:
            annotation_tile = self.clamped(data_tile)
            feature_tile = feature_extractor.compute(data_tile).cut(annotation_tile.interval, c=All())
            return FeatureSamples.create(annotation_tile, feature_tile)

        tile_shape = self.raw_data.tile_shape.updated(c=self.raw_data.shape.c)
        with ThreadPoolExecutor() as executor:
            all_feature_samples = list(executor.map(
                make_samples,
                self.raw_data.roi.clamped(interval_under_annotation).get_tiles(tile_shape=tile_shape, tiles_origin=self.raw_data.location)
            ))

        return all_feature_samples[0].concatenate(*all_feature_samples[1:])

    @classmethod
    def sort(cls, annotations: Sequence["Annotation"]) -> List["Annotation"]:
        return sorted(annotations, key=lambda a: a.color.q_rgba)

    def colored(self, value: np.uint8) -> Array5D:
        return Array5D(self._data * value, axiskeys=self.axiskeys, location=self.location)

    @staticmethod
    def merge(annotations: Sequence["Annotation"], color_map: Optional[Dict[Color, np.uint8]] = None) -> Array5D:
        out_roi = Interval5D.enclosing(annot.interval for annot in annotations)
        out = Array5D.allocate(interval=out_roi, value=0, dtype=np.dtype('uint8'))
        color_map = color_map or Color.create_color_map(annot.color for annot in annotations)
        for annot in annotations:
            out.set(annot.colored(color_map[annot.color]), mask_value=0)
        return out

    @staticmethod
    def dump_as_ilp_data(
        annotations: Sequence["Annotation"],
        color_map: Optional[Dict[Color, np.uint8]] = None,
        block_size: Optional[Shape5D] = None,
    ) -> Dict[str, Any]:
        if len(annotations) == 0:
            return {}
        if len(set(annot.raw_data for annot in annotations)) > 1:
            raise ValueError(f"All Annotations must come from the same datasource!")
        axiskeys = annotations[0].raw_data.axiskeys
        merged_annotations = Annotation.merge(annotations, color_map=color_map)

        out = {}
        for block_index, block in enumerate(merged_annotations.split(block_size or merged_annotations.shape)):
            out[f"block{block_index:04d}"] = {
                "__data__": block.raw(axiskeys),
                "__attrs__": {
                    "blockSlice": "["
                    + ",".join(f"{slc.start}:{slc.stop}" for slc in block.interval.to_slices(axiskeys))
                    + "]"
                },
            }
        return out

    @property
    def ilp_data(self) -> Mapping[str, Any]:
        axiskeys = self.raw_data.axiskeys
        return {
            "__data__": self.raw(axiskeys),
            "__attrs__": {
                "blockSlice": "[" + ",".join(f"{slc.start}:{slc.stop}" for slc in self.interval.to_slices(axiskeys)) + "]"
            },
        }

    def __repr__(self):
        return f"<Annotation {self.shape} for raw_data: {self.raw_data}>"
