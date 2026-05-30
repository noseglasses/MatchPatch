-- Get directory of current script
local script_path = debug.getinfo(1, "S").source:sub(2)
local script_dir = script_path:match("^(.*[\\/])")

-- Load library from same directory
local HelixLib =
    dofile(script_dir .. "HelixSnapshotLibrary.lua")

local CSV_PATH =
    script_dir .. "lufs_analysis.csv"

local csv_path =
    os.getenv("HELIX_CSV_PATH") or CSV_PATH

local function ShowError(message)
    reaper.ShowMessageBox(
        message,
        "Fehler",
        0
    )
end

local function ParsePresetSet(value)
    local presetIds = {}

    if not value or value:match("^%s*$") then
        return nil,
            "HELIX_PRESET_SET ist nicht gesetzt!"
    end

    for token in (value .. ","):gmatch("(.-),") do
        local trimmed =
            token:match("^%s*(.-)%s*$")

        if trimmed == "" then
            return nil,
                "Leerer Eintrag in HELIX_PRESET_SET"
        end

        local presetId =
            tonumber(trimmed)

        if not presetId or presetId % 1 ~= 0 then
            return nil,
                "Ungültige Presetnummer in HELIX_PRESET_SET: " ..
                tostring(trimmed)
        end

        table.insert(presetIds, presetId)
    end

    if #presetIds == 0 then
        return nil,
            "HELIX_PRESET_SET enthält keine Presets!"
    end

    return presetIds
end

local presetIds, err =
    ParsePresetSet(
        os.getenv("HELIX_PRESET_SET")
    )

if not presetIds then
    ShowError(tostring(err))
    return
end

HelixLib.RunPresetSetAnalysis(
    presetIds,
    csv_path
)
