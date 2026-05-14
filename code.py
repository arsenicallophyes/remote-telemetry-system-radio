from node.node import Node
from node.base.graph import Graph
from node.base.distribution import RoutingDistributor
from regulations.EU863.bands import BANDS

from models.model import NodeID


BASE = False # NodeID = 0
A    = False # NodeID = 1
B    = False # NodeID = 2
C    = False # NodeID = 3

roles = BASE, A, B, C
if sum(roles) != 1:
    raise SystemError(f"Only a single flag can be True. {roles=}")

if BASE:
    node = Node("Base", 0, 869.8, BANDS)
    graph = Graph()
    graph.add_node("A", NodeID(1))
    graph.add_node("B", NodeID(2))
    # graph.add_node("C", NodeID(3))
    graph.add_edge("BASE", "A", 1)
    graph.add_edge("A", "B", 1)
    # graph.add_edge("B", "C", 1)

    distributor = RoutingDistributor(node, graph)
    node.distributor = distributor
    node.run()
elif A:
    node = Node("A", 1, 869.8, BANDS)
    node.run()
elif B:
    node = Node("B", 2, 869.8, BANDS)
    node.run()
elif C:
    node = Node("C", 3, 869.8, BANDS)
    node.run()
