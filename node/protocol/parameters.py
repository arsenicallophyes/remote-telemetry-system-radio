from time import struct_time
from models.model import Message, NodeID
from node.base.routing_table import RoutingTable

try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False # pyright: ignore[reportConstantRedefinition]


if TYPE_CHECKING:
    from typing import NewType, Dict, Tuple, Optional, Callable, Any, TypedDict, List, Union, TypeAlias
    ParametersType = NewType("ParametersType", str)
    ValidatorType: TypeAlias = Callable[[Tuple[Union[str, None], ...]], Optional[Any]]

    class ParameterRule(TypedDict):
        argc: int
        validator: ValidatorType

    ParametersDict: TypeAlias = Dict[ParametersType, Any]
else:
    ParametersType = str

class Separator:
    FIELD = ";"
    KEY_VALUE = "="
    ARGS = "|"

class Parameters:
    """
    @enum
    """
    TIMESTAMP         = ParametersType("TS")
    DATA              = ParametersType("DT")
    LINK_FAILURE      = ParametersType("LF")
    ORIGIN_ID         = ParametersType("OR")
    ORIGIN_SEQ        = ParametersType("OS")
    DESTINATION       = ParametersType("DS")

class ControlParameters:
    """
    @enum
    """
    FREQUENCY_SWITCH  = ParametersType("FS")
    NETWORK_JOIN      = ParametersType("NJ")
    NETWORK_ACCEPT    = ParametersType("NA")
    NETWORK_REJOIN    = ParametersType("RJ")
    START_ETX_TX      = ParametersType("ET")
    START_ETX_RX      = ParametersType("ER")
    ETX_COUNT         = ParametersType("EC")

class RoutingParameters:
    """
    @enum
    """
    PATH_UPDATE       = ParametersType("PU")


# Function used to validate parameters must either return a value
# or return None if the parameter is invalid. If an empty or None value is valid
# the function should return a different type output other than None.

def validate_timestamp(args: "Tuple[Union[str, None], ...]") -> "Optional[struct_time]":
    stamp = args[0]

    if not stamp:
        return

    if len(stamp) != 14 or not stamp.isdigit():
        return

    try:
        y  = int(stamp[0:4])
        mo = int(stamp[4:6])
        d  = int(stamp[6:8])
        h  = int(stamp[8:10])
        mi = int(stamp[10:12])
        s  = int(stamp[12:14])
    except ValueError:
        return

    return struct_time((y, mo, d, h, mi, s, 0, 0, -1))

def validate_frequency_switch(
        args: "Tuple[Union[str, None], ...]",
    ) -> "Optional[Tuple[float, float]]":
    frequency, packet_time = args

    if not (frequency and packet_time):
        return

    try:
        frequency = float(frequency)
        packet_time = float(packet_time)
    except ValueError:
        return

    if not 863.0 <= frequency <= 870.0:
        return

    if packet_time <= 0:
        return

    return frequency, packet_time

def validate_etx_count(args: "Tuple[Union[str, None], ...]") -> "Optional[int]":
    etx_count = args[0]

    if not etx_count:
        return

    if not etx_count.isdigit():
        return

    try:
        return int(etx_count)
    except ValueError:
        return

def validate_network_join(args: "Tuple[Union[str, None], ...]") -> "Optional[bytes]":

    network_id = args[0]

    if not network_id:
        return

    try:
        network_id = bytes.fromhex(network_id)
    except ValueError:
        return

    if len(network_id) != 4:
        return

    return network_id

def validate_network_accept(args: "Tuple[Union[str, None], ...]") -> "Optional[int]":
    seq = args[0]

    if seq is None or seq == "":
        return

    if not seq.isdigit():
        return

    try:
        seq = int(seq)
    except ValueError:
        return

    if not 0 <= seq <= 255:
        return

    return seq

def validate_data(args: "Tuple[Union[str, None], ...]") -> "Optional[str]":
    data = args[0]

    if not data:
        return

    return data

def _validate_node_id_arg(raw: "Optional[str]") -> "Optional[int]":
    if raw is None:
        return

    if not raw.isdigit():
        return

    try:
        value = int(raw)
    except ValueError:
        return

    if not 0 <= value <= 255:
        return

    return value

def validate_link_failure(args: "Tuple[Union[str, None], ...]") -> "Optional[int]":
    return _validate_node_id_arg(args[0])

def validate_origin_id(args: "Tuple[Union[str, None], ...]") -> "Optional[int]":
    return _validate_node_id_arg(args[0])

def validate_origin_seq(args: "Tuple[Union[str, None], ...]") -> "Optional[int]":
    return _validate_node_id_arg(args[0])

def validate_destination(args: "Tuple[Union[str, None], ...]") -> "Optional[int]":
    return _validate_node_id_arg(args[0])

def validate_path_update(args: "Tuple[Union[str, None], ...]") -> "Optional[RoutingTable]":
    raw = args[0]
    if not raw:
        return
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return
    try:
        # Placeholder node_id and base_id
        # Receiver must overwrite it.
        table = RoutingTable.deserialize(NodeID(0), NodeID(0), data)
    except ValueError:
        return
    return table

PARAMETERS_RULES: "Dict[ParametersType, ParameterRule]" = {
    Parameters.TIMESTAMP : {
        "argc" : 1,
        "validator": validate_timestamp
    },
    Parameters.DATA : {
        "argc": 1,
        "validator" : validate_data
    },
    Parameters.LINK_FAILURE : {
        "argc": 1,
        "validator": validate_link_failure
    },
    Parameters.ORIGIN_ID : {
        "argc": 1,
        "validator": validate_origin_id
    },
    Parameters.ORIGIN_SEQ : {
        "argc": 1,
        "validator": validate_origin_seq
    },
    Parameters.DESTINATION : {
        "argc": 1,
        "validator" : validate_destination
    },
}

CONTROL_RULES: "Dict[ParametersType, ParameterRule]" = {
    ControlParameters.FREQUENCY_SWITCH : {
        "argc": 2,
        "validator" : validate_frequency_switch
    },
    ControlParameters.NETWORK_JOIN : {
        "argc" : 1,
        "validator": validate_network_join
    },
    ControlParameters.NETWORK_ACCEPT : {
        "argc" : 1,
        "validator": validate_network_accept
    },
    ControlParameters.NETWORK_REJOIN: {
        "argc": 1,
        "validator": lambda x: True
    },
    ControlParameters.ETX_COUNT: {
        "argc": 1,
        "validator": validate_etx_count
    },
    ControlParameters.START_ETX_TX: {
        "argc": 1,
        "validator": lambda x: True
    },
    ControlParameters.START_ETX_RX: {
        "argc": 1,
        "validator": lambda x: True
    },
}

ROUTING_RULES: "Dict[ParametersType, ParameterRule]" = {
    RoutingParameters.PATH_UPDATE : {
        "argc": 1,
        "validator": validate_path_update
    },
}

ALL_RULES: "Dict[ParametersType, ParameterRule]" = {}
ALL_RULES.update(PARAMETERS_RULES)
ALL_RULES.update(CONTROL_RULES)
ALL_RULES.update(ROUTING_RULES)

def extract_parameters(
    message: "Message",
) -> "Dict[ParametersType, Tuple[Optional[str], ...]]":
    fields = message.split(Separator.FIELD)

    parameters: "Dict[ParametersType, Tuple[Optional[str], ...]]" = {}
    for field in fields:
        try:
            keyword, value = field.split(Separator.KEY_VALUE, 1)
        except ValueError:
            continue

        raw_args = value.split(Separator.ARGS)
        args: "List[Optional[str]]" = []
        for arg in raw_args:
            args.append(arg if arg else None)

        parameter = ParametersType(keyword)
        parameters[parameter] = tuple(args)

    return parameters

def validate_parameters(message: "Message") -> "ParametersDict":
    parameters = extract_parameters(message)
    validated: "Dict[ParametersType, Any]" = {}

    for keyword, args in parameters.items():
        rule = ALL_RULES.get(keyword)

        if not rule:
            continue

        argc = rule["argc"]
        validator = rule["validator"]

        if len(args) != argc:
            continue

        value = validator(args)

        if value is None:
            continue

        validated[keyword] = value

    return validated

def add_parameter(
    message: "Optional[Message]",
    parameter: ParametersType,
    *args: str
) -> Message:
    arguments = Separator.ARGS.join(args)
    field = parameter + Separator.KEY_VALUE + arguments

    if message:
        return Message(message + Separator.FIELD + field)

    return Message(field)


def add_timestamp(now: struct_time, message: Message) -> Message:
    timestamp = (
        f"{now.tm_year:04}"
        f"{now.tm_mon:02}"
        f"{now.tm_mday:02}"
        f"{now.tm_hour:02}"
        f"{now.tm_min:02}"
        f"{now.tm_sec:02}"
    )

    return add_parameter(message, Parameters.TIMESTAMP, timestamp)
