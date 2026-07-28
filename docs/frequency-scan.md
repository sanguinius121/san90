# Frequency scan

The Frequency Scan feature implements a backend-owned continuous sequential
center-frequency scan. The browser edits an ordered list of stable entry IDs,
enabled flags, canonical center frequencies and steps in Hz, dwell durations
in milliseconds, and display-unit preferences.

The frontend may display each center frequency and step in GHz or MHz. Unit
selection is display-only; API configuration remains in Hz.

## API

- `GET /api/analyzer/frequency-scan/status`
- `PUT /api/analyzer/frequency-scan/config`
- `POST /api/analyzer/frequency-scan/start`
- `POST /api/analyzer/frequency-scan/stop`

Configuration payload:

```json
{
  "entries": [
    {
      "id": "frequency-scan-1",
      "enabled": true,
      "center_frequency_hz": 2450000000,
      "duration_ms": 2000,
      "step_hz": 10000000,
      "display_unit": "MHz",
      "step_unit": "MHz"
    }
  ]
}
```

Validated configuration is stored at `config/frequency-scan.json` with schema
version 1. The backend writes a complete temporary file in the same directory,
flushes and fsyncs it, then atomically replaces the destination. The file
contains only ordered entry configuration; running state, active entry,
remaining dwell, cycle state, errors, and hardware state are never persisted.
Missing files create the six defaults. Malformed or unsupported files produce
a warning and safe in-memory defaults without overwriting the bad file until a
valid user change is committed.

The regular analyzer status payload also contains `frequency_scan`, including
controller state, active entry ID and enabled-entry index, verified center
frequency, dwell duration, remaining dwell time, last error, and any
configuration load/save warning.

## Scheduler behavior

The controller states are `idle`, `tuning`, `dwelling`, `stopping`, and
`error`. Enabled entries run in list order and loop continuously. Disabled
entries remain configured but are skipped.

Each tune uses the normal serialized analyzer reconfiguration transaction.
Dwell timing begins only after applied-state readback matches the requested
center frequency. Manual center-frequency requests are rejected while the scan
owns tuning. Stop leaves the analyzer at the most recently verified scan
frequency.

Configuration commits are allowed while scanning. They never interrupt the
active tune or dwell; the loop reads the current ordered entry snapshot before
selecting the next entry, so an edit applies on that entry's next visit.
Deleting or disabling the active entry lets its current dwell finish. If no
enabled entries remain, the loop returns safely to idle after that dwell.

The initial UI list contains six enabled entries, each with a 5.0-second dwell:
400 MHz, 900 MHz, 2.44 GHz, 3.3 GHz, 5 GHz, and 5775 MHz. Newly added entries
also default to a 5.0-second dwell and an independent 10 MHz frequency step.
The duration minimum and UI step are both 0.5 seconds. The compact entry layout
keeps enable/delete on the first row, center/unit and minus/plus on the second,
and step/unit with duration on the third.
Loss of analyzer availability or a failed/mismatched tune ends the scan in the
error state; it never dwells on an unverified frequency.

The feature deliberately excludes pause/resume, reordering, presets, finite
cycle counts, settle-time configuration, skip actions, conditional stopping,
and AI-specific metadata.
