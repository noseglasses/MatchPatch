-- Get directory of current script
local script_path = debug.getinfo(1, "S").source:sub(2)
local script_dir = script_path:match("^(.*[\\/])")

-- Load library from same directory
local HelixLib = 
	dofile(script_dir .. "HelixSnapshotLibrary.lua")

local START_PATCH = 1
local END_PATCH   = 2

local CSV_PATH =
    script_dir .. "gain_correction.csv"

HelixLib.RunPresetRangeAnalysis(
    START_PATCH,
    END_PATCH,
    CSV_PATH
)