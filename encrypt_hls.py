import json
import base64
import zlib
import binascii

with open("setlist_unpacked.json", "r", encoding="utf-8") as f:
    text = f.read()

raw = text.encode("utf-8")

compressed = zlib.compress(raw)

wrapper = {
    "compression": {
        "crc32": binascii.crc32(raw) & 0xffffffff,
        "decompressed_size": len(raw),
        "type": "zlib"
    },
    "encoded_data": base64.b64encode(compressed).decode("ascii")
}

with open("setlist_repacked.hls", "w", encoding="utf-8") as f:
    json.dump(wrapper, f)