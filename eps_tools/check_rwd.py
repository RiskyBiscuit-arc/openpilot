#!/usr/bin/env python3
# Usage: python3 check_rwd.py <file.rwd> [file2.rwd ...]

import struct
import sys

DECRYPT_LOOKUP = {144: 72, 218: 55, 255: 255, 164: 1, 195: 26, 99: 2, 28: 178, 205: 158, 125: 138, 45: 118, 222: 98, 142: 78, 62: 58, 243: 38, 163: 18, 83: 254, 3: 234, 172: 214, 92: 194, 12: 174, 189: 154, 109: 134, 29: 114, 206: 94, 126: 74, 46: 54, 227: 34, 147: 14, 113: 0, 67: 250, 236: 230, 156: 210, 76: 190, 252: 170, 173: 150, 93: 130, 13: 110, 148: 253, 120: 159, 199: 148, 198: 137, 77: 126, 23: 104, 73: 83, 203: 73, 78: 62, 123: 53, 254: 42, 43: 33, 90: 23, 161: 12, 10: 3, 132: 249, 191: 239, 226: 220, 197: 201, 248: 191, 117: 181, 34: 172, 37: 161, 88: 151, 141: 142, 8: 131, 134: 121, 185: 111, 54: 101, 190: 90, 57: 79, 128: 68, 139: 57, 14: 46, 138: 35, 131: 10, 100: 241, 1: 228, 146: 200, 133: 185, 168: 171, 104: 155, 40: 139, 251: 85, 94: 66, 91: 45, 103: 124, 55: 112, 231: 156, 80: 56, 224: 92, 102: 113, 96: 60, 98: 188, 97: 252, 140: 206, 122: 31, 232: 187, 16: 40, 202: 51, 26: 7, 239: 251, 5: 153, 219: 77, 119: 128, 21: 157, 238: 102, 180: 5, 217: 119, 30: 50, 7: 100, 32: 44, 183: 144, 50: 176, 110: 70, 157: 146, 2: 164, 44: 182, 145: 8, 58: 15, 27: 29, 64: 52, 9: 67, 31: 199, 179: 22, 42: 11, 193: 20, 211: 30, 129: 4, 241: 32, 74: 19, 178: 208, 247: 160, 112: 64, 242: 224, 114: 192, 165: 193, 0: 36, 59: 37, 196: 9, 154: 39, 75: 41, 72: 147, 249: 127, 162: 204, 130: 196, 229: 209, 182: 133, 48: 48, 86: 109, 240: 96, 137: 99, 151: 136, 209: 24, 108: 198, 181: 197, 212: 13, 244: 21, 11: 25, 118: 117, 228: 17, 214: 141, 52: 229, 160: 76, 115: 6, 106: 27, 56: 143, 25: 71, 36: 225, 194: 212, 208: 88, 187: 69, 171: 65, 153: 103, 38: 97, 207: 243, 82: 184, 184: 175, 188: 218, 213: 205, 121: 95, 15: 195, 81: 248, 24: 135, 70: 105, 150: 125, 174: 86, 158: 82, 220: 226, 201: 115, 71: 116, 51: 246, 177: 16, 176: 80, 22: 93, 39: 108, 159: 231, 223: 247, 186: 47, 169: 107, 245: 213, 235: 81, 192: 84, 124: 202, 175: 235, 84: 237, 79: 211, 234: 59, 143: 227, 237: 166, 33: 236, 253: 106, 65: 244, 111: 219, 200: 179, 101: 177, 17: 232, 20: 221, 166: 129, 60: 186, 61: 122, 167: 140, 204: 222, 87: 120, 41: 75, 135: 132, 136: 163, 49: 240, 250: 63, 107: 49, 170: 43, 18: 168, 221: 162, 35: 242, 225: 28, 149: 189, 85: 173, 152: 167, 95: 215, 53: 165, 89: 87, 66: 180, 6: 89, 47: 203, 210: 216, 215: 152, 233: 123, 116: 245, 127: 223, 19: 238, 69: 169, 105: 91, 4: 217, 216: 183, 68: 233, 63: 207, 155: 61, 246: 149, 230: 145}

FIRMWARE_CHECKSUMS = {
    0x6c000: [(0, 0x6bf80, "sum"), (1, 0x6bffe, "negative-sum")],
    0x4c000: [(0, 0x4bf80, "sum"), (1, 0x4bffe, "negative-sum")],
}


def validate_firmware(fw):
    """Validate supported firmware checksums; unknown coverage is not a pass."""
    if len(fw.firmware_blocks) != 1:
        raise ValueError("exactly one firmware block is required")
    length = fw.firmware_blocks[0]["length"]
    encrypted = fw.firmware_encrypted[0]
    if len(encrypted) != length:
        raise ValueError("firmware length incorrect")
    definitions = FIRMWARE_CHECKSUMS.get(length)
    if definitions is None:
        raise ValueError(f"not fully validated: unknown firmware checksum coverage (0x{length:x})")
    try:
        decrypted = bytes(DECRYPT_LOOKUP[b] for b in encrypted)
    except KeyError as e:
        raise ValueError(f"unknown encrypted byte: {e.args[0]:02x}") from e
    for func, offset, label in definitions:
        stored = struct.unpack('!H', decrypted[offset:offset + 2])[0]
        words = struct.unpack(f'!{offset // 2}H', decrypted[:offset])
        calculated = (sum(words) * (-1 if func else 1)) & 0xffff
        if stored != calculated:
            raise ValueError(f"firmware checksum failed: {label} at 0x{offset:x}")
        print(f"  Firmware {label} checksum: PASS")


def check(path):
    from rwd_format.x5a import x5a
    print(f"\nChecking {path}")
    try:
        with open(path, 'rb') as stream:
            fw = x5a(stream.read())
        print("  Container and file checksum: PASS")
        validate_firmware(fw)
    except (OSError, ValueError) as e:
        print(f"  NOT VALIDATED: {e}")
        return False
    print("  Fully validated: PASS")
    return True


def main(argv=None):
    paths = sys.argv[1:] if argv is None else argv
    if not paths:
        print("Usage: python3 check_rwd.py <file.rwd> [file2.rwd ...]")
        return 1
    results = [check(path) for path in paths]
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
