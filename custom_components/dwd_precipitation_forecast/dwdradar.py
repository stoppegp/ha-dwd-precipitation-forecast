from datetime import UTC, datetime, timedelta
from io import BytesIO
import math
import tarfile

import numpy as np
import requests
import logging

API_URL = "https://opendata.dwd.de/weather/radar/composite/rv/DE1200_RV_LATEST.tar.bz2"

_LOGGER = logging.getLogger(__name__)


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
            radar_minute_delta = int(tarmember.name[-3:])
            radar_time = datetime.strptime(
                tarmember.name[-14:-4], "%y%m%d%H%M"
            ).replace(tzinfo=UTC) + timedelta(minutes=radar_minute_delta)
            f = tar.extractfile(tarmember)
            content = f.read().split(b"\x03", 1)[1]
            radars[radar_time] = np.frombuffer(content, dtype="uint16").reshape(
                self.ysize, self.xsize
            )
        self.radars = radars
        _LOGGER.info("got radars")

    def get_location_index(self, x, y):
        if self.radars is None:
            raise RadarNotAvailableError
        x_cart = int(
            6370.04
            * (1 + math.sin(60 / 180 * math.pi))
            / (1 + math.sin(x / 180 * math.pi))
            * math.cos(x / 180 * math.pi)
            * math.sin((y - 10) / 180 * math.pi)
            + 543.4622
        )
        y_cart = int(
            -6370.04
            * (1 + math.sin(60 / 180 * math.pi))
            / (1 + math.sin(x / 180 * math.pi))
            * math.cos(x / 180 * math.pi)
            * math.cos((y - 10) / 180 * math.pi)
            + 4808.645
        )
        if not (0 <= y_cart < self.ysize) or not (0 <= x_cart < self.xsize):
            raise NotInAreaError
        return (x_cart, y_cart)

    def get_precipitation_values(self, x, y):
        x_cart, y_cart = self.get_location_index(x, y)
        if self.radars is None:
            self.get_radars()
        values = {}
        for radar_time, radar in self.radars.items():
            value_raw = radar[y_cart][x_cart]
            value = (
                value_raw & 0b0000111111111111
                if not (value_raw & 0b0010000000000000)
                else 0
            )
            values[radar_time] = float(value) / 100 * 12
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
