from time import monotonic, sleep

from node.protocol.formula.etx import ETX

from models.packet import Packet
from models.packet_type import PacketKind
from models.model import NodeID

try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False  # pyright: ignore[reportConstantRedefinition]

if TYPE_CHECKING:
    from typing import Optional, Tuple
    from adafruit_rfm9x_patched import RFM9x
    from node.mac.band_airtime import WaitTime
    from node.transport.peer import Peer
    from node.transport.peer_table import PeerTable
    from node.mac.band_airtime import BandAirtime
    from models.model import SpreadingFactor, CodingRate, Message, Identifier, Frequency
    from models.packet_type import PacketKindType
    from regulations.types.model import Band


ETX_MESSAGE = 0

class EtxMixin:
    rfm9x: "RFM9x"
    node_id: NodeID
    peer_table: "PeerTable"

    etx_packets_count: int = 20
    spreading_factor: "SpreadingFactor"
    bandwidth: int
    coding_rate: "CodingRate"
    control_band: "Band"
    control_frequency: float
    wait_horizon_sec: "WaitTime"

    if TYPE_CHECKING:
        # pylint: disable=unused-argument
        def apply_link_profile(
            self,
            sf: SpreadingFactor,
            bw: int,
            cr: CodingRate,
            tx_power_dbm: int,
            crc: bool = True,
            preamble: int = 8,
        ) -> None: ...

        def decode_packet(
                self,
                packet_bytes: bytearray,
            ) -> Tuple[Message, NodeID, Identifier, PacketKindType]: ...

        def control_transmit_await_ack(
            self,
            packet: Packet,
            peer: Peer,
            now: Optional[float] = None,
        ) -> Optional[bool]: ...

        def send_packet(
            self,
            packet: Packet,
            channel_info: Optional[Tuple[Frequency, BandAirtime, float]] = None,
            show_usage : bool = False,
        ) -> None: ...

    def etx_transmit(
        self,
        target: NodeID,
        now: "Optional[float]" = None,
    ) -> None:
        now = monotonic() if now is None else now
        r = self.rfm9x

        self.apply_link_profile(
            self.spreading_factor,
            self.bandwidth,
            self.coding_rate,
            self.control_band.erp,
            True,
        )
        if round(r.frequency_mhz, 1) != self.control_frequency:
            r.frequency_mhz = self.control_frequency

        packet = Packet(self.node_id, target, PacketKind.CONTROL, 0, str(ETX_MESSAGE))
        for i in range(self.etx_packets_count):
            packet.identifier = i
            self.send_packet(packet)
            sleep(0.25)

    def etx_complete(self, peer: "Peer", successfully_transmitted_packet: int) -> None:
        if not peer.etx_rx_count:
            return

        etx_score = ETX.calculate_etx(
            self.etx_packets_count,
            peer.etx_rx_count,
            successfully_transmitted_packet,
        )

        peer.etx_score    = etx_score
        print(f"Peer ID: {peer.node_id} -> {etx_score=}")

    def etx_receive(
            self,
            expected_source: NodeID,
            listen_window: "Optional[float]",
            now: "Optional[float]" = None,
        ) -> None:
        now = monotonic() if now is None else now
        r = self.rfm9x

        self.apply_link_profile(
            self.spreading_factor,
            self.bandwidth,
            self.coding_rate,
            self.control_band.erp,
            True,
        )

        if round(r.frequency_mhz, 1) != self.control_frequency:
            r.frequency_mhz = self.control_frequency

        peer = self.peer_table.get_peer(expected_source)

        if not peer:
            return

        n = 0
        rssi_avg = 0
        last_received = None
        deadline = monotonic() + (listen_window if listen_window else float(self.wait_horizon_sec))

        while n < self.etx_packets_count and monotonic() < deadline:
            packet_bytes = r.receive(with_header=True)

            if not packet_bytes:
                continue

            message, source, identifier, packet_kind = self.decode_packet(packet_bytes) # pylint: disable=assignment-from-no-return

            if source != expected_source:
                continue

            if packet_kind != PacketKind.CONTROL:
                continue

            if message != str(ETX_MESSAGE):
                continue

            rssi_avg += r.last_rssi
            n += 1
            last_received = identifier
            if last_received >= self.etx_packets_count:
                break

        peer.etx_rx_count = n
        peer.rssi_average = rssi_avg / n if n != 0 else None
