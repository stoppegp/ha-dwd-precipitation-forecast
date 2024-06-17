from datetime import timedelta
import logging

import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .dwdradar import DWDRadar

_LOGGER = logging.getLogger(__name__)

type DwdPrecipitationForecastConfigEntry = ConfigEntry[
    DwdPrecipitationForecastCoordinator
]


class DwdPrecipitationForecastCoordinator(DataUpdateCoordinator):
    config_entry: DwdPrecipitationForecastConfigEntry
    api: DWDRadar

    def __init__(self, hass):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=5),
        )

    async def async_config_entry_first_refresh(self) -> None:
        """Perform first refresh."""
        self.api = DWDRadar()

        await super().async_config_entry_first_refresh()

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(60):
                # Grab active context variables to limit data required to be fetched from API
                # Note: using context is not required if there is no need or ability to limit
                # data retrieved from API.
                return await self.hass.async_add_executor_job(self.api.get_radars)
        except Exception as err:
            raise UpdateFailed(f"This Error communicating with API: {err}")
