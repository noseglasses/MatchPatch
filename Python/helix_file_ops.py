"""Pure Helix preset/setlist split and join helpers."""

import base64
import binascii
import copy
import json
import os
import re
import zlib


def decode_hls_text(hls_text):
    wrapper = json.loads(hls_text)
    compressed = base64.b64decode(wrapper["encoded_data"])
    raw = zlib.decompress(compressed)
    return raw.decode("utf-8")


def build_hls_text(original_hls_text, modified_json_text):
    raw = modified_json_text.encode("utf-8")
    compressed = zlib.compress(raw, level=9)
    encoded_data = base64.b64encode(compressed).decode("ascii")
    decompressed_size = len(raw)
    crc32 = binascii.crc32(raw) & 0xFFFFFFFF
    result = original_hls_text
    result = re.sub(
        r'("encoded_data"\s*:\s*")([^"]*)(")',
        rf"\g<1>{encoded_data}\g<3>",
        result,
        flags=re.DOTALL,
    )
    result = re.sub(r'("decompressed_size"\s*:\s*)(\d+)', rf"\g<1>{decompressed_size}", result)
    return re.sub(r'("crc32"\s*:\s*)(\d+)', rf"\g<1>{crc32}", result)


def build_new_hls_text(json_text):
    raw = json_text.encode("utf-8")
    compressed = zlib.compress(raw, level=9)
    wrapper = {
        "compression": {
            "crc32": (binascii.crc32(raw) & 0xFFFFFFFF),
            "decompressed_size": len(raw),
            "type": "zlib",
        },
        "encoded_data": base64.b64encode(compressed).decode("ascii"),
    }
    return json.dumps(wrapper)


def _wrap_preset_data(data):
    if not isinstance(data, dict):
        raise ValueError(".hlx preset content must be a JSON object")
    if isinstance(data.get("data"), dict):
        preset = data["data"]
        if "tone" not in preset:
            raise ValueError(".hlx preset data does not contain a tone section")
        return {"presets": [preset]}
    if "presets" in data:
        raise ValueError(".hlx input must contain one preset, not a setlist")
    if "tone" not in data:
        raise ValueError(".hlx preset content does not contain a tone section")
    return {"presets": [data]}


def _unwrap_preset_data(data):
    presets = data.get("presets")
    if not isinstance(presets, list) or len(presets) != 1:
        raise ValueError(".hlx output requires exactly one preset")
    return presets[0]


def load_preset_file(path):
    with open(path, "r", encoding="utf-8") as f:
        original_hlx_data = json.load(f)
    data = _wrap_preset_data(original_hlx_data)
    return copy.deepcopy(_unwrap_preset_data(data)), original_hlx_data


def load_setlist_file(path):
    with open(path, "r", encoding="utf-8") as f:
        original_hls_text = f.read()
    return json.loads(decode_hls_text(original_hls_text)), original_hls_text


def preset_index_to_helix(index):
    bank = (index // 4) + 1
    slot = ["A", "B", "C", "D"][index % 4]
    return f"{bank:02d}{slot}"


def helix_to_preset_index(label):
    match = re.fullmatch(r"(?i)(\d{1,2})([A-D])", str(label).strip())
    if match is None:
        raise ValueError(f"Invalid Helix preset slot ID: {label!r}")
    bank = int(match.group(1))
    slot = "ABCD".index(match.group(2).upper())
    if bank < 1:
        raise ValueError(f"Invalid Helix preset slot ID: {label!r}")
    return (bank - 1) * 4 + slot


def _slot_indices(slot_ids, count):
    if slot_ids is None:
        return list(range(count))
    if len(slot_ids) != count:
        raise ValueError("--slot-ids count must match --join-presets count")
    return [helix_to_preset_index(slot_id) for slot_id in slot_ids]


def join_preset_files_to_setlist(preset_paths, template_setlist_path=None, slot_ids=None):
    sources = {}
    slot_indices = _slot_indices(slot_ids, len(preset_paths))
    if template_setlist_path is None:
        setlist_data = {"presets": []}
        original_hls_text = None
    else:
        setlist_data, original_hls_text = load_setlist_file(template_setlist_path)
    setlist_presets = setlist_data.setdefault("presets", [])

    for slot_index, preset_path in zip(slot_indices, preset_paths):
        preset, _ = load_preset_file(preset_path)
        while len(setlist_presets) <= slot_index:
            setlist_presets.append({"tone": {}})
        setlist_presets[slot_index] = preset
        sources[preset_index_to_helix(slot_index)] = os.path.basename(os.fspath(preset_path))

    json_text = json.dumps(setlist_data, indent=1)
    hls_text = (
        build_hls_text(original_hls_text, json_text)
        if original_hls_text is not None
        else build_new_hls_text(json_text)
    )
    return hls_text, {"source_filenames": sources}


def _selected_preset_indices(selected_ids, preset_count):
    if selected_ids is None:
        return list(range(preset_count))
    result = []
    for selected_id in selected_ids:
        if isinstance(selected_id, int):
            index = selected_id - 1
        else:
            text = str(selected_id).strip()
            index = int(text) - 1 if text.isdecimal() else helix_to_preset_index(text)
        if index < 0 or index >= preset_count:
            raise ValueError(f"Selected preset is outside the setlist: {selected_id!r}")
        result.append(index)
    return result


def _original_filename_for_preset(original_filenames, preset_index, label):
    if not original_filenames:
        return None
    keys = [label, preset_index + 1, str(preset_index + 1), preset_index, str(preset_index)]
    for key in keys:
        if key in original_filenames:
            filename = os.path.basename(os.fspath(original_filenames[key]))
            root, ext = os.path.splitext(filename)
            return filename if ext.lower() == ".hlx" else f"{root}.hlx"
    return None


def safe_preset_filename(name, fallback_label):
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(name or ""))
    safe_name = re.sub(r"\s+", " ", safe_name).strip(" .")
    if not safe_name:
        safe_name = str(fallback_label)
    if not safe_name.lower().endswith(".hlx"):
        safe_name = f"{safe_name}.hlx"
    return safe_name


def _get_preset_name(preset):
    meta = preset.get("meta", {})
    return meta.get("name") or preset.get("name") or preset.get("@name") or ""


def _preset_has_blocks(preset):
    tone = preset.get("tone", {})
    if not isinstance(tone, dict):
        return False
    for dsp_name in ["dsp0", "dsp1"]:
        dsp = tone.get(dsp_name)
        if not isinstance(dsp, dict):
            continue
        for block_name in dsp:
            if str(block_name).startswith("block"):
                return True
    return False


def _is_default_preset(preset):
    return not _preset_has_blocks(preset)


def split_setlist_to_preset_data(input_path, selected_ids=None, original_filenames=None):
    data, _ = load_setlist_file(input_path)
    presets = data.get("presets", [])
    selected_indices = _selected_preset_indices(selected_ids, len(presets))
    split_presets = []
    synthetic_names = [
        safe_preset_filename(
            _get_preset_name(presets[preset_index]), preset_index_to_helix(preset_index)
        )
        for preset_index in selected_indices
        if not _is_default_preset(presets[preset_index])
        and _original_filename_for_preset(
            original_filenames, preset_index, preset_index_to_helix(preset_index)
        )
        is None
    ]
    duplicate_synthetic_names = {
        filename for filename in synthetic_names if synthetic_names.count(filename) > 1
    }

    for preset_index in selected_indices:
        preset = presets[preset_index]
        if _is_default_preset(preset):
            continue
        label = preset_index_to_helix(preset_index)
        original_filename = _original_filename_for_preset(original_filenames, preset_index, label)
        if original_filename is not None:
            split_presets.append((original_filename, copy.deepcopy(preset)))
            continue

        filename = safe_preset_filename(_get_preset_name(preset), label)
        if filename in duplicate_synthetic_names:
            root, ext = os.path.splitext(filename)
            filename = f"{root} {label}{ext}"
        split_presets.append((filename, copy.deepcopy(preset)))

    return split_presets
