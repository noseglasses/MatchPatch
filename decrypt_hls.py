import json
import base64
import zlib

with open("setlist.hls", "r", encoding="utf-8") as f:
    wrapper = json.load(f)

compressed = base64.b64decode(wrapper["encoded_data"])
raw = zlib.decompress(compressed)

text = raw.decode("utf-8")

with open("setlist_unpacked.json", "w", encoding="utf-8") as f:
    f.write(text)