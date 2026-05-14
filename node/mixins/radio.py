from time import struct_time, sleep, monotonic
from math import log

import rtc # pyright: ignore[reportMissingModuleSource] # pylint: disable=import-error
import board
import busio
import digitalio
from adafruit_rfm9x_patched import RFM9x

from models.packet import Packet
from models.packet_type import PacketKind

from node.mac.duty_cycle_tracker import DutyCycleTracker
from node.mac.channel_selection import ChannelSelect
from node.mac.airtime import Airtime
from node.mac.band_selection import BandSelect

from regulations.types.model import BandsSeq


try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False  # pyright: ignore[reportConstantRedefinition]

if TYPE_CHECKING:
    from typing import Tuple, Optional
    from models.model import SpreadingFactor, CodingRate, Frequency
    from node.mac.types.models import WaitTime
    from node.mac.band_airtime import BandAirtime
    from regulations.band import Band
    from models.model import NodeID


# Adafruit RFM9X library does not support implicit header mode,
# so spreading factor 6 is unavailable (it requires an implicit header).
IMPLICIT_HEADER_MODE = False


class RadioMixin:
    node_id : "NodeID"
    dc_tracker: DutyCycleTracker
    channels: ChannelSelect


    time_scale:              float
    formula_weights:         "Tuple[float, float]"
    temp:                    float
    min_control_reserve_ratio: float
    allow_wait_candidates:   bool
    wait_horizon_sec:        "WaitTime"
    ack_wait:                float
    spreading_factor:        "SpreadingFactor"
    bandwidth:               int
    coding_rate:             "CodingRate"

    control_band: "Band"
    control_frequency:       float

    def __init_rtc__(self):
        self.rtc = rtc.RTC()
        # Year, Month, Day, Hour, Minute, Second
        # Day of week, day of year, daylight saving flag: Last 3 fields ignored
        self.rtc.datetime = struct_time((2026, 1, 1, 0, 0, 0, 0, 0, -1))

    def __init_radio__(self, freq: float, bands: BandsSeq) -> None:
        """
        Initialize radio pins for Challenger RP2040 868 MHz
        
        :param self: Description
        """
        cs      = digitalio. DigitalInOut(board.GP9)
        reset   = digitalio.DigitalInOut(board.GP13)
        spi     = busio.SPI(board.GP10, MOSI=board.GP11, MISO=board.GP12)
        rfm9x   = RFM9x(spi, cs, reset, freq)

        setattr(rfm9x, "node", self.node_id)

        self.rfm9x = rfm9x

        for b in bands:
            self.dc_tracker.register_band(b.name, b.duty_cycle)


    def apply_link_profile(
        self,
        sf: "SpreadingFactor",
        bw: int,
        cr: "CodingRate",
        tx_power_dbm: int,
        crc: bool = True,
        preamble: int = 8,
    ) -> None:

        r = self.rfm9x
        r.spreading_factor = sf
        r.signal_bandwidth = bw
        r.coding_rate = cr
        r.tx_power = round(10 * log(tx_power_dbm, 10))
        r.enable_crc = crc
        r.preamble_length = preamble

    def acquire_channel(
        self,
        packet: Packet,
        now: "Optional[float]" = None,
    ) -> "Tuple[Frequency, BandAirtime, float]":
        # Additional 4 bytes added by the RFM9x library due to explicit header mode
        # Maximum payload size 252 + 4 bytes header = 256 bytes
        r = self.rfm9x
        now = monotonic() if now is None else now
        packet_bytes = len(packet.to_byte()) + 4
        packet_time = Airtime.total_time(
            r.signal_bandwidth,
            r.spreading_factor,
            r.preamble_length,
            packet_bytes,
            IMPLICIT_HEADER_MODE,
            r.low_datarate_optimize,
            r.coding_rate,
            r.enable_crc
        )
        if packet.p_type == PacketKind.CONTROL:
            bands = (self.dc_tracker.bands_airtime[self.control_band.name],)
        else:
            bands = self.dc_tracker.get_registered_bands()
        band, wait_time = BandSelect.select_band(
            bands,
            packet_time,
            packet.p_type,
            self.time_scale,
            self.formula_weights,
            self.temp,
            self.min_control_reserve_ratio,
            self.allow_wait_candidates,
            self.wait_horizon_sec,
            now,
        )
        sleep(wait_time)
        self.dc_tracker.validate_can_transmit(band.name, packet_time)
        frequency = self.channels.select_channel(band.name)

        return frequency, band, packet_time

    def send_packet(
        self,
        packet: Packet,
        channel_info: "Optional[Tuple[Frequency, BandAirtime, float]]" = None,
        show_usage : bool = False,
    ) -> None:
        r = self.rfm9x
        if not channel_info:
            _, band, packet_time = self.acquire_channel(packet)
        else:
            _, band, packet_time = channel_info

        r.send(
            packet.to_byte(),
            destination=packet.target,
            node=packet.source,
            identifier=packet.identifier,
            flags=packet.p_type
        )

        self.dc_tracker.commit_airtime(band.name, packet_time)
        if show_usage:
            bands = self.dc_tracker.get_registered_bands()
            print("Bands Airtime Usage")
            print("=" * 30)
            for b in bands:
                used = b.used()
                print(
                    f"Band {b.name}",
                    f"Hourly Budget: {b.hourly_budget}s | Duty Cycle: {b.dc}%",
                    f"Raw Usage: {used}",
                    f"Percent Usage: {round(used * 100/b.hourly_budget, 2)}%",
                    "=" * 30,
                    sep="\n",
                )
