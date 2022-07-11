import enum
import math
import struct
import typing

HEADER_FORMAT = '!IIHH'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def pack_header(sequence_number: int = 0, ack_number: int = 0, ack=False, syn=False, fin=False,
                receive_window: int = 0, data: bytes = None) -> bytes:
    flags = to_ASF(ack, syn, fin)
    header = struct.pack(HEADER_FORMAT, sequence_number, ack_number, flags, receive_window)
    return header if data is None else header + data


def unpack_header(data: bytes) -> typing.Tuple[int, int, bool, bool, bool, int, bytes]:
    sequence_number, ack_number, flags, receive_window = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    ack, syn, fin = from_ASF(flags)
    return sequence_number, ack_number, ack, syn, fin, receive_window, data[HEADER_SIZE:]


def to_ASF(ack=False, syn=False, fin=False) -> int:
    return (bool(ack) << 7) | (bool(syn) << 6) | (bool(fin) << 5)


def from_ASF(flags: int) -> typing.Tuple[bool, bool, bool]:
    return bool(flags & (1 << 7)), bool(flags & (1 << 6)), bool(flags & (1 << 5))


def convert_size(size_bytes: float) -> tuple[float, str]:
    if size_bytes == 0:
        return 0, "B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    unit_idx = int(math.floor(math.log(size_bytes, 1024)))
    power_base = math.pow(1024, unit_idx)
    frac_pa = round(size_bytes / power_base, 2)
    return frac_pa, size_name[unit_idx]


class CCStatus(enum.Enum):
    SLOW_START = 0
    CONGESTION_AVOIDANCE = 1
    FAST_RECOVERY = 2


class CCEvent(enum.Enum):
    DUP_ACK = 0
    TIMEOUT = 1
    ACK = 2
