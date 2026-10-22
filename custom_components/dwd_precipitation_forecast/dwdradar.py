from datetime import UTC, datetime, timedelta
from io import BytesIO
import math
import re
import tarfile

import h5py
import numpy as np
import requests
import logging

API_URL = "https://opendata.dwd.de/weather/radar/composite/rv/composite_rv_LATEST.tar"

# Filename: composite_rv_YYYYMMDD_HHMM_PPP.hd5 (PPP = forecast in minutes)
_MEMBER_RE = re.compile(r"composite_rv_(\d{8})_(\d{4})_(\d{3})")

_LOGGER = logging.getLogger(__name__)


# 6370.04 * (1 + sin(60 deg)), constant part of projection
_PROJ_SCALE = 6370.04 * (1 + math.sin(60 / 180 * math.pi))


class NotInAreaError(Exception):
    pass


class RadarNotAvailableError(Exception):
    pass


class DWDRadar:
    def __init__(self):
        self.radars = None
        self.xsize = 1100
        self.ysize = 1200

    def get_radars(self):
        _LOGGER.info("get radars")
        radars = {}
        r = requests.get(API_URL)
        _LOGGER.info(r)
        tar = tarfile.open(fileobj=BytesIO(r.content))
        _LOGGER.info(tar)

        for tarmember in tar.getmembers():
            match = _MEMBER_RE.search(tarmember.name)
            if not tarmember.isfile() or match is None:
                continue
            radar_minute_delta = int(match.group(3))
            radar_time = datetime.strptime(
                match.group(1) + match.group(2), "%Y%m%d%H%M"
            ).replace(tzinfo=UTC) + timedelta(minutes=radar_minute_delta)
            f = tar.extractfile(tarmember)
            radars[radar_time] = self._read_hdf5(f.read())
        radars = dict(sorted(radars.items()))
        self.radars = radars
        _LOGGER.info("got radars")

    def _read_hdf5(self, content):
        """Read one ODIM HDF5 composite as uint16 array in 0.001 mm per 5 min."""
        with h5py.File(BytesIO(content), "r") as h5:
            data = h5["dataset1/data1/data"][()]
            what = h5["dataset1/data1/what"].attrs

            def attr(name, default):
                return np.asarray(what[name]).item() if name in what else default

            gain = attr("gain", 1.0)
            offset = attr("offset", 0.0)
            nodata = attr("nodata", None)
            undetect = attr("undetect", None)

        if data.shape != (self.ysize, self.xsize):
            raise ValueError(f"unexpected radar grid shape {data.shape}")

        # value = offset + gain * raw (mm per 5 min); saved as uint16 in
        # 0,001 mm (up to 65,5 mm per 5 min), memory usage as before
        values = (data.astype(np.float32) * gain + offset) * 1000
        invalid = ~np.isfinite(values)
        for flag in (nodata, undetect):
            if flag is not None:
                invalid |= data == flag
        values[invalid] = 0
        compact = np.clip(np.rint(values), 0, 65535).astype(np.uint16)
        # ODIM: first line = north; index get_location_index counts from south
        return compact[::-1]

    def get_location_index(self, x, y):
        if self.radars is None:
            raise RadarNotAvailableError
        k = _PROJ_SCALE / (1 + math.sin(x / 180 * math.pi)) * math.cos(x / 180 * math.pi)
        lon = (y - 10) / 180 * math.pi
        x_cart = int(k * math.sin(lon) + 543.4622)
        y_cart = int(-k * math.cos(lon) + 4808.645)
        if not (0 <= y_cart < self.ysize) or not (0 <= x_cart < self.xsize):
            raise NotInAreaError
        return (x_cart, y_cart)

    def get_precipitation_values(self, x, y):
        x_cart, y_cart = self.get_location_index(x, y)
        if self.radars is None:
            self.get_radars()
        values = {}
        for radar_time, radar in self.radars.items():
            values[radar_time] = round(float(radar[y_cart][x_cart]) / 1000 * 12, 3)
        return values

    def get_value(self, x, y, search_time: datetime):
        precipitation_values = self.get_precipitation_values(x, y)
        return np.interp(
            search_time.timestamp(),
            [x.timestamp() for x in precipitation_values],
            list(precipitation_values.values()),
        )
        current_value = None
        for radar_time, precipitation in precipitation_values.items():
            if radar_time <= datetime.now(UTC):
                current_value = precipitation
            else:
                break
        return current_value

    def get_next_precipitation(self, x, y):
        rain_start = None
        rain_end = None
        rain_max = 0
        rain_sum = 0
        for rain_time, precipitation in self.get_precipitation_values(x, y).items():
            if rain_start is None and precipitation > 0:
                rain_start = rain_time
                rain_max = precipitation
                rain_sum = precipitation
                continue
            if rain_start is not None:
                rain_max = max(rain_max, precipitation)
                rain_sum += precipitation
            if rain_start is not None and rain_end is None and precipitation == 0:
                rain_end = rain_time
                continue
            if rain_start is not None and rain_end is not None and precipitation != 0:
                rain_end = None
                continue
            if rain_start is not None and rain_end is not None and precipitation == 0:
                break

        if rain_start is not None:
            if rain_end is not None:
                rain_length = rain_end - rain_start
            else:
                rain_length = None
            rain_sum = rain_sum / 12
        else:
            rain_length = None

        return {
            "start": rain_start,
            "end": rain_end,
            "length": rain_length,
            "max": rain_max,
            "sum": rain_sum,
        }
