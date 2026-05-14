from models.packet import Packet
from models.packet_type import PacketKind

from node.protocol.parameters import RoutingParameters, Parameters, add_parameter, add_timestamp

try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False  # pyright: ignore[reportConstantRedefinition]

if TYPE_CHECKING:
    from typing import Dict, List
    from models.model import NodeID, Message
    from node.node import Node
    from node.base.graph import Graph
    from node.base.routing_table import RoutingTable

class RoutingDistributor:

    def __init__(self, base_node: "Node", graph: "Graph") -> None:
        self.base_node = base_node
        self.graph = graph
        self.tables: "Dict[NodeID, RoutingTable]" = {}

    def compute(self) -> "Dict[NodeID, RoutingTable]":
        self.tables = self.graph.build_routing_table()
        return self.tables

    def install_local(self):
        base_id = self.base_node.node_id
        table = self.tables.get(base_id)
        if not table:
            raise RuntimeError(f"Routing Table for BASE={base_id} has not been computed.")

        self.base_node.install_routing_table(table)
        print(f"BASE installed routing table {repr(table)}")

    def _bfs_order(self):
        base_id = self.base_node.node_id

        # Build parent -> NodeID - key is the parent
        # value - Contains all of the parent's  children

        children_of: "Dict[NodeID, List[NodeID]]" = {}
        for node_id, table in self.tables.items():
            if table.parent is not None:
                children_of.setdefault(table.parent, []).append(node_id)

        order: "List[NodeID]" = []
        queue: "List[NodeID]" = [base_id]

        # We start from the base then expalnd to its direct children.
        # The direct children are added to the `queue`,
        # we select the base's child and add the child's sub-children
        # to the end of the `queue`. While moving the child to `order`.
        # This is then repeated with all children, essentially BFS.
        while queue:
            current = queue.pop(0)
            if current != base_id:
                order.append(current)

            for child in sorted(children_of.get(current, []),  key=int):
                queue.append(child)

        return order

    def _build_path_update_message(
        self,
        destination: "NodeID",
        table: "RoutingTable"
    ) -> "Message":
        hex_payload = table.serialize().hex()
        message = add_parameter(None, RoutingParameters.PATH_UPDATE, hex_payload)
        message = add_parameter(message, Parameters.DESTINATION, str(int(destination)))
        message = add_timestamp(self.base_node.rtc.datetime, message)
        return message

    def _send_path_update(self, destination: "NodeID", table: "RoutingTable") -> bool:
        message = self._build_path_update_message(destination, table)

        base_table = self.base_node.routing_table
        if base_table is None:
            raise RuntimeError(
                f"Routing Table for BASE={self.base_node.node_id} "
               "has not been installed."
            )

        next_hop = base_table.next_hop(destination)
        if next_hop is None:
            print(f"Route from BASE to {destination=} is unavailable, skipping.")
            return False

        peer = self.base_node.peer_table.get_peer(next_hop)
        if peer is None:
            print(
                f"Next hop {{{next_hop}}} is not a registered peer in BASE"
                f"Skipping {destination=}"
            )
            return False

        packet = Packet(
            self.base_node.node_id,
            next_hop,
            PacketKind.CONTROL,
            peer.transmit.next_seq,
            message,
        )

        print(f"PATH_UPDATE -> {destination=} via {next_hop=}")
        response = self.base_node.control_transmit_await_ack(packet, peer)

        if not response:
            return False

        return True

    def distribute(self):
        self.compute()
        self.install_local()

        results: "Dict[NodeID, bool]" = {}

        for destination in self._bfs_order():
            table = self.tables[destination]
            response = self._send_path_update(destination, table)
            results[destination] = response

            if not response:
                print(f"PATH_UPDATE for {destination} was not ACKed, ignoring.")

        return results
