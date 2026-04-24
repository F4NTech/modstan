# =============================================================================
# MODSTAN - Data Converter
# Converts raw Modbus register values to engineering units
# =============================================================================

import struct
import logging

logger = logging.getLogger(__name__)


def swap_bytes(registers: list[int], byte_format: str) -> list[int]:
    """
    Reorder register bytes/words according to the specified byte format.

    Supported formats:
      ABCD  - Big Endian, no swap (default)
      CDAB  - Big Endian, word swap
      BADC  - Little Endian, byte swap
      DCBA  - Little Endian, byte + word swap
      AB    - Single register, no swap
      BA    - Single register, byte swap
    """
    fmt = byte_format.upper()

    if fmt in ('ABCD', 'AB'):
        return registers

    elif fmt == 'CDAB':
        return registers[::-1]

    elif fmt == 'BA':
        return [((r & 0xFF) << 8) | ((r >> 8) & 0xFF) for r in registers]

    elif fmt == 'BADC':
        return [((r & 0xFF) << 8) | ((r >> 8) & 0xFF) for r in registers]

    elif fmt == 'DCBA':
        swapped = [((r & 0xFF) << 8) | ((r >> 8) & 0xFF) for r in registers]
        return swapped[::-1]

    else:
        raise ValueError(f"Unknown byte format: {byte_format}")


def convert_registers(registers: list[int], data_type: str, byte_format: str) -> float | int:
    """
    Convert a list of 16-bit Modbus registers to the specified data type.

    Returns a numeric value (int or float).
    """
    regs = swap_bytes(registers, byte_format)
    dt   = data_type.lower()

    try:
        if dt == 'uint16':
            return regs[0]

        elif dt == 'int16':
            return struct.unpack('>h', struct.pack('>H', regs[0]))[0]

        elif dt == 'uint32':
            return struct.unpack('>I', struct.pack('>HH', regs[0], regs[1]))[0]

        elif dt == 'int32':
            return struct.unpack('>i', struct.pack('>HH', regs[0], regs[1]))[0]

        elif dt == 'uint64':
            return struct.unpack('>Q', struct.pack('>HHHH', regs[0], regs[1], regs[2], regs[3]))[0]

        elif dt == 'int64':
            return struct.unpack('>q', struct.pack('>HHHH', regs[0], regs[1], regs[2], regs[3]))[0]

        elif dt == 'float32':
            return struct.unpack('>f', struct.pack('>HH', regs[0], regs[1]))[0]

        elif dt == 'float64':
            return struct.unpack('>d', struct.pack('>HHHH', regs[0], regs[1], regs[2], regs[3]))[0]

        else:
            raise ValueError(f"Unknown data type: {data_type}")

    except (struct.error, IndexError) as e:
        raise ValueError(
            f"Failed to convert register (type={data_type}, format={byte_format}): {e}"
        )


def to_hex_string(registers: list[int]) -> str:
    """Return registers as a hex string. Example: '0x1234 0xABCD'"""
    return ' '.join(f'0x{r:04X}' for r in registers)


def process_register(raw_registers: list[int], data_type: str,
                     byte_format: str, scale: float) -> dict:
    """
    Full conversion pipeline: raw registers → hex string → raw value → scaled value.

    Returns a dict with all value representations.
    """
    raw_value    = convert_registers(raw_registers, data_type, byte_format)
    scaled_value = raw_value * scale
    hex_str      = to_hex_string(raw_registers)

    return {
        'hex'   : hex_str,
        'raw'   : raw_value,
        'scaled': scaled_value,
    }
