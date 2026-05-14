from time import monotonic, sleep

from node.mixins.state import NodeState
from node.transport.peer_table import PeerTable
from node.transport.types.sequence_response import SequenceResponse
from node.transport.types.recovery_state import RecoveryState
from node.storage.persistence_manager import PersistenceManager
from node.protocol.parameters import Parameters, ControlParameters, add_parameter, add_timestamp
from node.transport.types.authorization_state import AuthorizationState

from models.packet import Packet
from models.packet_type import PacketKind
from models.model import NodeID, Frequency

try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False  # pyright: ignore[reportConstantRedefinition]

if TYPE_CHECKING:
    from typing import Optional, Tuple, Set
    from time import struct_time

    from rtc import RTC # pyright: ignore[reportMissingModuleSource] # pylint: disable=import-error
    from adafruit_rfm9x_patched import RFM9x

    from node.mac.band_airtime import WaitTime
    from node.mac.duty_cycle_tracker import DutyCycleTracker
    from node.mac.channel_selection import ChannelSelect
    from node.mac.band_airtime import BandAirtime

    from node.transport.peer import Peer

    from models.model import SpreadingFactor, CodingRate, Message, Identifier
    from models.packet_type import PacketKindType

    from node.protocol.parameters import ParametersDict

BASE_NODE_ID = NodeID(0)

class DataMixin(NodeState):
    rfm9x:     "RFM9x"
    node_id:   NodeID
    rtc:       "RTC"

    peer_table:          PeerTable
    persistence_manager: PersistenceManager
    dc_tracker:          "DutyCycleTracker"
    channels:            "ChannelSelect"

    ack_wait:                float
    control_frequency:       float
    bandwidth:               int
    coding_rate:             "CodingRate"
    spreading_factor:        "SpreadingFactor"
    wait_horizon_sec:        "WaitTime"
    dropped  = False


    if TYPE_CHECKING:
        # pylint: disable=unused-argument
        def _control_transmit_nack(
            self,
            packet: Packet,
            peer: Peer,
            now: Optional[float] = None,
        ) -> Optional[Set[int]]: ...

        def control_transmit_await_ack(
            self,
            packet: Packet,
            peer: Peer,
            now: Optional[float] = None,
        ) -> Optional[bool]: ...

        def control_send_NACK(
            self,
            source: NodeID,
            now: Optional[float] = None
        ) -> Optional[Set[int]]: ...

        def control_listen_NACK(
            self,
            expected_source: NodeID,
            now: Optional[float] = None,
        ) -> None: ...

        def control_send_ack(
            self,
            target: NodeID,
            peer: Optional[Peer] = None,
        ) -> None: ...

        def control_receive(
            self,
            deadline: float,
            timeout: Optional[float] = None,
            packet_kind: PacketKindType = PacketKind.CONTROL,
        ) -> Optional[Tuple[ParametersDict, NodeID, Identifier, Optional[Peer]]]: ...

        def send_packet(
            self,
            packet: Packet,
            channel_info: Optional[Tuple[Frequency, BandAirtime, float]] = None,
            show_usage : bool = False,
        ) -> None: ...

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

        def extract_timestamp(
            self,
            message: Message,
        ) -> Optional[struct_time]: ...

        def log_peer_activity(
            self,
            peer: Peer,
            identifier: int,
        ) -> None: ...

        def acquire_channel(
            self,
            packet: Packet,
            now: Optional[float] = None,
        ) -> Tuple[Frequency, BandAirtime, float]: ...

        def network_rejoin(
            self,
            peer: Peer,
        ) -> None: ...

        def transmit_upstream(
            self,
            message: Message,
            now: Optional[float] = None,
        ) -> bool: ...

    def data_transmit(self, packet: Packet, now: "Optional[float]" = None) -> bool:
        now = monotonic() if now is None else now
        r = self.rfm9x
        packet.validate_packet()

        # Packet.validate_packet() handles the verification process
        # This if statement is done for the IDE type checker
        # Thus, this statement never returns
        if packet.target is None:
            return False

        peer = self.peer_table.get_peer(packet.target)
        if not peer:
            print("Peer Unregistered")
            return False

        if peer.state == AuthorizationState.PENDING:
            self.network_rejoin(peer)
            return False

        channel_info = self.acquire_channel(packet, now) # pylint: disable=assignment-from-no-return
        frequency, _, packet_time = channel_info

        arguments = str(frequency), str(packet_time)
        message = add_parameter(None, ControlParameters.FREQUENCY_SWITCH, *arguments)
        message = add_timestamp(self.rtc.datetime, message)

        control_packet = Packet(
            self.node_id,
            packet.target,
            PacketKind.CONTROL,
            peer.transmit.next_seq,
            message,
        )

        if not self.control_transmit_await_ack(control_packet, peer, now):
            print("Receiver unresponsive")
            return False

        print("Base switched frequency")
        r.frequency_mhz = frequency

        self.apply_link_profile(
            self.spreading_factor,
            self.bandwidth,
            self.coding_rate,
            25,
            True,
        )
        sleep(self.ack_wait)
        # if packet.identifier == 2 and not self.dropped:
        #     print(f"Dropping packet ID:2, {packet.message}")
        #     r.frequency_mhz = self.control_frequency
        #     self.dropped = True
        #     peer.transmit.increment_data_sequence()
        #     return True

        self.send_packet(packet, channel_info, True)
        if not self.retransmit:
            peer.transmit.increment_data_sequence()

        r.frequency_mhz = self.control_frequency

        if not self.retransmit:
            self.control_listen_NACK(packet.target, now)
        else:
            print("Done with retansmitting")

        return True

    def _reconstruct_forward_message(self, parameters: "ParametersDict") -> "Optional[Message]":
        data = parameters.get(Parameters.DATA)
        if not isinstance(data, str):
            return

        message = add_parameter(None, Parameters.DATA, data)

        timestamp = parameters.get(Parameters.TIMESTAMP)
        if timestamp is not None:
            message = add_timestamp(timestamp, message)

        origin_id = parameters.get(Parameters.ORIGIN_ID)
        if origin_id is not None:
            message = add_parameter(message, Parameters.ORIGIN_ID, str(origin_id))

        origin_seq = parameters.get(Parameters.ORIGIN_SEQ)
        if origin_seq is not None:
            message = add_parameter(message, Parameters.ORIGIN_SEQ, str(origin_seq))

        link_failure = parameters.get(Parameters.LINK_FAILURE)
        if link_failure is not None:
            message = add_parameter(message, Parameters.LINK_FAILURE, str(link_failure))

        return message

    def _handle_upstream_data(
        self,
        parameters: "ParametersDict",
        data: str,
        now: float,
    ) -> None:
        origin_id = parameters.get(Parameters.ORIGIN_ID)
        origin_seq = parameters.get(Parameters.ORIGIN_SEQ)

        if self.node_id == BASE_NODE_ID:
            print(f"Saving data -> '{data=}' | {origin_id=} | {origin_seq=}")
            return

        if origin_id is None:
            print(f"Saving data -> '{data=}' | No origin id, dumping parameters | {parameters=}")
            return

        if origin_id == self.node_id:
            print(f"Loop detected: dropping, dumping parameters | {parameters=}")
            return

        forward_message = self._reconstruct_forward_message(parameters)
        if forward_message is None:
            print(
                "Unable to forward: "
                "packet does not contain data parameter, dumping parameters  | "
                f"{parameters=}"
            )
            return

        response = self.transmit_upstream(forward_message, now) # pylint: disable=assignment-from-no-return
        if response:
            print(f"Packet forwarded from {origin_id=} {origin_seq=}")
        else:
            print(f"Failed to forward for {origin_id=} {origin_seq=}")

    def data_receive(
            self,
            frequency: Frequency,
            packet_time: float,
            recovery_source: "Optional[NodeID]" = None,
            now: "Optional[float]" = None,
        ) -> None:
        now = monotonic() if now is None else now
        r = self.rfm9x

        r.frequency_mhz = frequency
        self.apply_link_profile(
            self.spreading_factor,
            self.bandwidth,
            self.coding_rate,
            25,
            True,
        )
        timeout = 2 * packet_time + self.ack_wait
        print(f"Switched to {round(r.frequency_mhz, 1)} MHz, {timeout=}")

        try:
            deadline = monotonic() + timeout + 1
            response = self.control_receive(deadline, timeout, PacketKind.DATA) # pylint: disable=assignment-from-no-return

            if not response:
                print("Timed out")
                return

            parameters, source, identifier, _ = response

            data = parameters.get(Parameters.DATA)
            if not isinstance(data, str):
                print("Invalid Data")
                return

            failed_node = parameters.get(Parameters.LINK_FAILURE)
            if failed_node is not None:
                print(
                    f"Received failover packet: "
                    f"{source=} reports {failed_node=} to be unresponsive"
                )

            if recovery_source and recovery_source != source:
                print("Unexpected Source")
                return

            if not self.recovery:
                response = self.peer_table.handle_sequence(source, identifier)
            else:
                response = self.peer_table.handle_sequence_recovery(
                    source,
                    identifier,
                    self.recovery,
                )

                if response == SequenceResponse.ABORT:
                    print("Aborting Recovery")
                    return

            if response == SequenceResponse.UNREGISTERED:
                print("Unregistered")
                return

            peer = self.peer_table.get_peer(source)
            if not peer:
                return

            if response == SequenceResponse.PENDING:
                print("Node is pending registration")
                self.network_rejoin(peer)
                return

            if response == SequenceResponse.DUPLICATE:
                self.log_peer_activity(peer, identifier)
                print("Duplicate packet")
                return

            if response == SequenceResponse.SUCCESS:
                self.log_peer_activity(peer, identifier)
                self._handle_upstream_data(parameters, data, now)

            if response == SequenceResponse.AHEAD:
                nack_response = self.control_send_NACK(source, now) # pylint: disable=assignment-from-no-return
                if nack_response is not None:
                    if len(nack_response) == 0:
                        peer.receive.set_sequence(identifier)
                        peer.receive.increment_sequence()
                    else:
                        self.recovery = RecoveryState(source, nack_response, identifier)
                self.log_peer_activity(peer, identifier)

                self._handle_upstream_data(parameters, data, now)

        finally:
            r.frequency_mhz = self.control_frequency

    def data_recovery(self, listen_window: float, now: "Optional[float]" = None):
        if not self.recovery:
            return

        now = monotonic() if now is None else now

        source = self.recovery.source
        deadline = monotonic() + (listen_window if listen_window else float(self.wait_horizon_sec))
        while self.recovery.queued_packets and monotonic() < deadline:
            response = self.control_receive(deadline) # pylint: disable=assignment-from-no-return
            if not response:
                continue
            parameters, rx_source, _, peer = response
            if rx_source != source:
                continue

            if result := parameters.get(ControlParameters.FREQUENCY_SWITCH):
                frequency, packet_time = result
                if not (isinstance(frequency, float) and isinstance(packet_time, float)):
                    return
                frequency = Frequency(frequency)
                self.control_send_ack(source)
                self.data_receive(frequency, packet_time, now=now)


        if not self.recovery.queued_packets:
            peer = self.peer_table.get_peer(source)

            if not peer:
                self.recovery = None
                return

            peer.receive.complete_recovery(self.recovery.ahead_seq)
        else:
            peer = self.peer_table.get_peer(source)
            if peer:
                print(f"Recovery failed: {self.recovery.queued_packets} unrecovered. Advancing sequence.")
                peer.receive.complete_recovery(self.recovery.ahead_seq)

        self.recovery = None

    def data_retransmission(self):
        if not self.retransmit:
            return

        for packet in self.retransmit.queued_packets:
            now = monotonic()
            self.data_transmit(packet, now)
            sleep(0.15)

        self.retransmit = None
