from typing import Optional
from pathlib import Path
import enum
import json
from webilastik.filesystem import JsonableFilesystem
from ndstructs.utils.json_serializable import JsonObject, JsonValue, ensureJsonObject, ensureJsonString

import numpy as np
from fs.errors import ResourceNotFound
from ndstructs import Point5D, Interval5D, Array5D

from webilastik.datasource.n5_attributes import N5Compressor, N5DatasetAttributes
from webilastik.datasource import DataSource

class N5Block(Array5D):
    class Modes(enum.IntEnum):
        DEFAULT = 0
        VARLENGTH = 1

    @classmethod
    def from_bytes(cls, data: bytes, axiskeys: str, dtype: np.dtype, compression: N5Compressor, location: Point5D):
        data = np.frombuffer(data, dtype=np.uint8)

        header_types = [
            ("mode", ">u2"),  # mode (uint16 big endian, default = 0x0000, varlength = 0x0001)
            ("num_dims", ">u2"),  # number of dimensions (uint16 big endian)
        ]
        preamble = np.frombuffer(data, dtype=header_types, count=1)
        header_types.append(
              # dimension 1[,...,n] (uint32 big endian)
            ("dimensions", str(preamble["num_dims"].item()) + ">u4") # type: ignore
        )

        if preamble["mode"].item() == cls.Modes.VARLENGTH.value:
            # mode == varlength ? number of elements (uint32 big endian)
            header_types.append(("num_elements", ">u4")) # type: ignore
            raise RuntimeError("Don't know how to handle varlen N5 blocks")

        header_dtype = np.dtype(header_types)
        header_data = np.frombuffer(data, dtype=header_dtype, count=1)
        array_shape = header_data["dimensions"].squeeze()

        compressed_buffer = np.frombuffer(data, offset=header_dtype.itemsize, dtype=np.uint8)
        decompressed_buffer = compression.decompress(compressed_buffer.tobytes())
        raw_array = np.frombuffer(decompressed_buffer, dtype=dtype.newbyteorder(">")).reshape(array_shape, order="F") # type: ignore

        return cls(raw_array, axiskeys=axiskeys[::-1], location=location)

    def to_n5_bytes(self, axiskeys: str, compression: N5Compressor):
        # because the axistags are written in reverse order to attributes.json, bytes must be written in C order.
        data_buffer = compression.compress(self.raw(axiskeys).astype(self.dtype.newbyteorder(">")).tobytes("C")) # type: ignore
        tile_types = [
            ("mode", ">u2"),  # mode (uint16 big endian, default = 0x0000, varlength = 0x0001)
            ("num_dims", ">u2"),  # number of dimensions (uint16 big endian)
            ("dimensions", f"{len(axiskeys)}>u4"),  # dimension 1[,...,n] (uint32 big endian)
            ("data", f"{len(data_buffer)}u1"),
        ]
        tile = np.zeros(1, dtype=tile_types)
        tile["mode"] = self.Modes.DEFAULT.value
        tile["num_dims"] = len(axiskeys)
        tile["dimensions"] = [self.shape[k] for k in axiskeys[::-1]]
        tile["data"] = np.ndarray((len(data_buffer),), dtype=np.uint8, buffer=data_buffer)
        return tile.tobytes()


class N5DataSource(DataSource):
    """A DataSource representing an N5 dataset. "axiskeys" are, like everywhere else in ndstructs, C-ordered."""

    def __init__(self, path: Path, *, location: Optional[Point5D] = None, filesystem: JsonableFilesystem):
        self.path = path
        self.filesystem = filesystem

        with self.filesystem.openbin(path.joinpath("attributes.json").as_posix(), "r") as f:
            attributes_json = f.read().decode("utf8")
        self.attributes = N5DatasetAttributes.from_json_data(json.loads(attributes_json), location_override=location)

        super().__init__(
            tile_shape=self.attributes.blockSize,
            interval=self.attributes.interval,
            dtype=self.attributes.dataType,
            axiskeys=self.attributes.axiskeys,
        )

    def to_json_value(self) -> JsonObject:
        out = {**super().to_json_value()}
        out["path"] = self.path.as_posix()
        out["filesystem"] = self.filesystem.to_json_value()
        return out

    @classmethod
    def from_json_value(cls, value: JsonValue) -> "N5DataSource":
        value_obj = ensureJsonObject(value)
        raw_location = value_obj.get("location")
        return N5DataSource(
            path=Path(ensureJsonString(value_obj.get("path"))),
            filesystem=JsonableFilesystem.from_json_value(value_obj.get("filesystem")),
            location=raw_location if raw_location is None else Point5D.from_json_value(raw_location),
        )

    def __hash__(self) -> int:
        return hash((self.filesystem.desc(self.path.as_posix()), self.interval))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, N5DataSource) and
            super().__eq__(other) and
            self.filesystem.desc(self.path.as_posix()) == self.filesystem.desc(self.path.as_posix())
        )

    def _get_tile(self, tile: Interval5D) -> Array5D:
        slice_address = self.path / self.attributes.get_tile_path(tile)
        try:
            with self.filesystem.openbin(slice_address.as_posix()) as f:
                raw_tile = f.read()
            tile_5d = N5Block.from_bytes(
                data=raw_tile, axiskeys=self.axiskeys, dtype=self.dtype, compression=self.attributes.compression, location=tile.start
            )
        except ResourceNotFound:
            tile_5d = self._allocate(interval=tile, fill_value=0)
        return tile_5d

    def __getstate__(self) -> JsonObject:
        return self.to_json_value()

    def __setstate__(self, data: JsonValue):
        data_obj = ensureJsonObject(data)
        self.__init__(
            path=Path(ensureJsonString(data_obj.get("path"))),
            location=Interval5D.from_json_value(data_obj.get("interval")).start,
            filesystem=JsonableFilesystem.from_json_value(data_obj.get("filesystem"))
        )

DataSource.datasource_from_json_constructors[N5DataSource.__name__] = N5DataSource.from_json_value
