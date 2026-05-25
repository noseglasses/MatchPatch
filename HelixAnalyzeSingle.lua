-- Get directory of current script
local script_path = debug.getinfo(1, "S").source:sub(2)
local script_dir = script_path:match("^(.*[\\/])")

-- Load library from same directory
local HelixLib = 
	dofile(script_dir .. "HelixSnapshotLibrary.lua")

HelixLib.RunSinglePresetAnalysis()