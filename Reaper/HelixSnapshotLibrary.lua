local HelixLib = {}

--------------------------------------------------
-- SETTINGS
--------------------------------------------------

HelixLib.RECORD_TIME  = 3.75
HelixLib.HELIX_WAIT   = 0.5
HelixLib.LUFS_SAMPLE_INTERVAL = 0.1
HelixLib.LUFS_SHORT_TERM_WINDOW = 3.0

HelixLib.HELIX_DEVICE_ID = 17

--------------------------------------------------
-- HELPERS
--------------------------------------------------

local function BusyWait(seconds)

    local start = reaper.time_precise()

    while (reaper.time_precise() - start) < seconds do

        reaper.UpdateArrange()
        reaper.TrackList_AdjustWindows(false)
        reaper.UpdateTimeline()

        reaper.defer(function() end)
    end
end

--------------------------------------------------
-- TRACK HELPERS
--------------------------------------------------

function HelixLib.GetMeasurementTrack()
    local track_count = reaper.CountTracks(0)

    for i = 0, track_count - 1 do
        local track = reaper.GetTrack(0, i)
        local _, name =
            reaper.GetTrackName(track)

        if name == "Messung" then
            return track
        end
    end

    return nil, "Spur 'Messung' wurde nicht gefunden!"
end

function HelixLib.ArmOnlyMeasurementTrack(track)
    local track_count = reaper.CountTracks(0)

    for i = 0, track_count - 1 do
        local currentTrack = reaper.GetTrack(0, i)
        local armed = currentTrack == track and 1 or 0

        reaper.SetMediaTrackInfo_Value(
            currentTrack,
            "I_RECARM",
            armed
        )
    end

    reaper.SetOnlyTrackSelected(track)
end

--------------------------------------------------
-- RECORD CONTROL
--------------------------------------------------

function HelixLib.StopRecording()
    if (reaper.GetPlayState() & 4) == 4 then
        reaper.Main_OnCommand(1013, 0)
    end

    local wait_start = reaper.time_precise()

    while (reaper.GetPlayState() & 4) == 4 do
        if (reaper.time_precise() - wait_start) > 2.0 then
            break
        end

        reaper.UpdateArrange()
    end
end

function HelixLib.ResetTransportToZero()
    HelixLib.StopRecording()

    reaper.Main_OnCommand(40042, 0)
    reaper.SetEditCurPos(0, false, false)

    reaper.UpdateTimeline()
    reaper.UpdateArrange()

    BusyWait(0.1)
end

--------------------------------------------------
-- CLEANUP
--------------------------------------------------

function HelixLib.DeleteAllTrackItems(track)
    local item_count = reaper.CountTrackMediaItems(track)

    for i = item_count - 1, 0, -1 do
        local item = reaper.GetTrackMediaItem(track, i)

        if item then
            reaper.DeleteTrackMediaItem(track, item)
        end
    end

    reaper.UpdateArrange()
end

--------------------------------------------------
-- SNAPSHOT MIDI
--------------------------------------------------

function HelixLib.ActivateSnapshot(snapshot)
    local value = snapshot - 1

    if value < 0 or value > 7 then
        return false, "Ungültiger Snapshot: " .. tostring(snapshot)
    end

    reaper.StuffMIDIMessage(
        HelixLib.HELIX_DEVICE_ID,
        0xB0,
        69,
        value
    )

    BusyWait(0.05)

    return true
end

--------------------------------------------------
-- LOUDNESS ANALYSIS
--------------------------------------------------

function HelixLib.FindLoudnessMeter(track)
    local fx_count = reaper.TrackFX_GetCount(track)

    for fx = 0, fx_count - 1 do
        local _, fx_name = reaper.TrackFX_GetFXName(track, fx, "")

        fx_name = string.lower(tostring(fx_name))

        if string.find(fx_name, "lufs")
        or string.find(fx_name, "loudness")
        or string.find(fx_name, "rms") then
            return fx
        end
    end

    return -1
end

function HelixLib.GetShortTermLUFS(track)
    local fx_index = HelixLib.FindLoudnessMeter(track)

    if fx_index < 0 then
        return nil, "LOUDNESS FX NOT FOUND"
    end

    local retval, text =
        reaper.TrackFX_GetFormattedParamValue(
            track,
            fx_index,
            19,
            ""
        )

    if not retval then
        return nil, "Could not read LUFS-S"
    end

    return tonumber(
        string.match(tostring(text), "[-%d%.]+")
    )
end

function HelixLib.GetAverageShortTermLUFS(track, seconds)
    local start = reaper.time_precise()
    local nextSample =
        start + HelixLib.LUFS_SHORT_TERM_WINDOW
    local sum = 0
    local count = 0

    while (reaper.time_precise() - start) < seconds do
        local now = reaper.time_precise()

        if now >= nextSample then
            local lufs =
                HelixLib.GetShortTermLUFS(track)

            if lufs and lufs > -100 then
                sum = sum + lufs
                count = count + 1
            end

            nextSample =
                nextSample +
                HelixLib.LUFS_SAMPLE_INTERVAL
        end

        reaper.UpdateArrange()
        reaper.TrackList_AdjustWindows(false)
        reaper.UpdateTimeline()

        reaper.defer(function() end)
    end

    if count == 0 then
        return nil, "Could not collect valid LUFS-S samples"
    end

    return sum / count
end

--------------------------------------------------
-- SINGLE SNAPSHOT ANALYSIS
--------------------------------------------------

function HelixLib.AnalyzeSnapshot(track, snapshot)

    local ok, err = HelixLib.ActivateSnapshot(snapshot)

    if not ok then
        return nil, err
    end

    HelixLib.ArmOnlyMeasurementTrack(track)

    BusyWait(HelixLib.HELIX_WAIT)

    HelixLib.ResetTransportToZero()

    HelixLib.ArmOnlyMeasurementTrack(track)

    reaper.Main_OnCommand(40289, 0)

    reaper.CSurf_OnRecord()

    if (reaper.GetPlayState() & 4) ~= 4 then
        return nil,
            "RECORD wurde NICHT gestartet!"
    end

    local lufs, lufsErr =
        HelixLib.GetAverageShortTermLUFS(
            track,
            HelixLib.RECORD_TIME
        )

    HelixLib.StopRecording()

    local wait_start = reaper.time_precise()

    while reaper.CountTrackMediaItems(track) == 0 do

        if (reaper.time_precise() - wait_start) > 5.0 then
            return nil,
                "Kein aufgenommenes Item gefunden!"
        end
    end

    if not lufs then
        return nil, lufsErr
    end

    HelixLib.DeleteAllTrackItems(track)

    return {
        snapshot = snapshot,
        lufs = lufs
    }
end

--------------------------------------------------
-- PRESET ANALYSIS
--------------------------------------------------

function HelixLib.AnalyzeCurrentPreset()

    local track, err =
        HelixLib.GetMeasurementTrack()

    if not track then
        return nil, err
    end

    local results = {}

    HelixLib.DeleteAllTrackItems(track)
    HelixLib.ResetTransportToZero()

    for snapshot = 1, 4 do

        local result, analyzeErr =
            HelixLib.AnalyzeSnapshot(track, snapshot)

        if not result then
            HelixLib.StopRecording()
            HelixLib.DeleteAllTrackItems(track)

            return nil, analyzeErr
        end

        table.insert(results, result)
    end

    HelixLib.DeleteAllTrackItems(track)

    return results
end

--------------------------------------------------
-- CSV HELPERS
--------------------------------------------------

function HelixLib.CreateCSV(csvPath)

    local file = io.open(csvPath, "w")

    if not file then
        return false
    end

    file:write(
        "Preset," ..
		"HelixPreset," ..
        "LUFS1," ..
        "LUFS2," ..
        "LUFS3," ..
        "LUFS4\n"
    )

    file:close()

    return true
end

--------------------------------------------------
-- PRESET NAME HELPER
--------------------------------------------------

function HelixLib.GetHelixPresetName(patchNumber)

    --------------------------------------------------
    -- Helix:
    -- 4 Presets pro Bank:
    --
    -- 1  -> 01A
    -- 2  -> 01B
    -- 3  -> 01C
    -- 4  -> 01D
    -- 5  -> 02A
    --------------------------------------------------

    local zeroBased = patchNumber - 1

    local bank =
        math.floor(zeroBased / 4) + 1

    local slotIndex =
        zeroBased % 4

    local slots = {
        "A",
        "B",
        "C",
        "D"
    }

    return string.format(
        "%02d%s",
        bank,
        slots[slotIndex + 1]
    )
end

function HelixLib.AppendCSVRow(
    csvPath,
    patchNumber,
    results
)

    local file = io.open(csvPath, "a")

    if not file then
        return false
    end

    local helixPreset =
        HelixLib.GetHelixPresetName(
            patchNumber
        )

    local values = {
        tostring(patchNumber),
        helixPreset
    }

    for i = 1, 4 do

        local r = results[i]

        table.insert(values, tostring(r.lufs))
    end

    file:write(
        table.concat(values, ",") .. "\n"
    )

    file:close()

    return true
end

--------------------------------------------------
-- PRESET CHANGE MIDI
--------------------------------------------------

function HelixLib.ActivatePreset(patchNumber)

    if not patchNumber then
        return false, "Ungültige Presetnummer"
    end

    --------------------------------------------------
    -- HELIX:
    -- Program Change ist 0-basiert
    -- Preset 1 = PC 0
    --------------------------------------------------

    local value = patchNumber - 1

    if value < 0 or value > 127 then
        return false,
            "Ungültige Presetnummer: " ..
            tostring(patchNumber)
    end

    reaper.StuffMIDIMessage(
        HelixLib.HELIX_DEVICE_ID,
        0xC0,
        value,
        0
    )

    --------------------------------------------------
    -- Helix braucht etwas Zeit
    -- um das Preset zu laden
    --------------------------------------------------

    BusyWait(HelixLib.HELIX_WAIT)

    return true
end

--------------------------------------------------
-- WRAPPER: PRESET RANGE
--------------------------------------------------
local function RunPresetListAnalysis(
    presetIds,
    csvPath
)

    reaper.ClearConsole()

    local ok =
        HelixLib.CreateCSV(csvPath)

    if not ok then

        reaper.ShowMessageBox(
            "CSV konnte nicht erstellt werden!",
            "Fehler",
            0
        )

        return
    end

    local currentIndex = 1

    local function ProcessNextPreset()

        --------------------------------------------------
        -- Fertig?
        --------------------------------------------------

        if currentIndex > #presetIds then

            local donePath =
                os.getenv("HELIX_DONE_PATH")

            if donePath and donePath ~= "" then
                local doneFile =
                    io.open(donePath, "w")

                if doneFile then
                    doneFile:write("done\n")
                    doneFile:close()
                end
            end

            local quitWhenDone =
                os.getenv("HELIX_QUIT_WHEN_DONE")

            if quitWhenDone == "1" then
                reaper.defer(
                    function()
                        reaper.Main_OnCommand(40004, 0)
                    end
                )
            else
                reaper.ShowMessageBox(
                    "Preset-Analyse abgeschlossen!",
                    "Fertig",
                    0
                )
            end

            return
        end

        --------------------------------------------------
        -- WICHTIG:
        -- NÄCHSTEN defer SOFORT registrieren
        --------------------------------------------------

        local presetToProcess = presetIds[currentIndex]
        currentIndex = currentIndex + 1

        reaper.defer(ProcessNextPreset)

        --------------------------------------------------
        -- GUI refresh
        --------------------------------------------------

        reaper.UpdateArrange()
        reaper.TrackList_AdjustWindows(false)
        reaper.UpdateTimeline()

        --------------------------------------------------
        -- Logging
        --------------------------------------------------

        reaper.ShowConsoleMsg(
            "================================\n"
        )

        reaper.ShowConsoleMsg(
            "PRESET " ..
            tostring(presetToProcess) ..
            "\n"
        )

        --------------------------------------------------
        -- Preset aktivieren
        --------------------------------------------------

        local patchOk, patchErr =
            HelixLib.ActivatePreset(
                presetToProcess
            )

        if not patchOk then

            reaper.ShowConsoleMsg(
                "Preset konnte nicht geladen werden: " ..
                tostring(patchErr) ..
                "\n"
            )

            return
        end

        --------------------------------------------------
        -- Analyse
        --------------------------------------------------

        local results, err =
            HelixLib.AnalyzeCurrentPreset()

        if not results then

            reaper.ShowConsoleMsg(
                "Fehler: " ..
                tostring(err) ..
                "\n"
            )

            return
        end

        --------------------------------------------------
        -- CSV schreiben
        --------------------------------------------------

        local csvOk =
            HelixLib.AppendCSVRow(
                csvPath,
                presetToProcess,
                results
            )

        if csvOk then

            reaper.ShowConsoleMsg(
                "CSV geschrieben\n"
            )

        else

            reaper.ShowConsoleMsg(
                "CSV FEHLER\n"
            )
        end

        --------------------------------------------------
        -- Cleanup
        --------------------------------------------------

        HelixLib.ResetTransportToZero()

        reaper.UpdateArrange()
        reaper.UpdateTimeline()
    end

    reaper.defer(ProcessNextPreset)
end

function HelixLib.RunPresetRangeAnalysis(
    startPreset,
    endPreset,
    csvPath
)

    local presetIds = {}

    for presetId = startPreset, endPreset do
        table.insert(presetIds, presetId)
    end

    RunPresetListAnalysis(
        presetIds,
        csvPath
    )
end

function HelixLib.RunPresetSetAnalysis(
    presetIds,
    csvPath
)

    if type(presetIds) ~= "table" or #presetIds == 0 then

        reaper.ShowMessageBox(
            "Keine Presets angegeben!",
            "Fehler",
            0
        )

        return
    end

    for _, presetId in ipairs(presetIds) do
        if type(presetId) ~= "number" or presetId % 1 ~= 0 then

            reaper.ShowMessageBox(
                "Ungültige Presetnummer: " ..
                tostring(presetId),
                "Fehler",
                0
            )

            return
        end
    end

    RunPresetListAnalysis(
        presetIds,
        csvPath
    )
end

return HelixLib
