# Frequency scan

Phase 1 implements a backend-owned continuous sequential center-frequency
scan. The browser edits an ordered list of stable entry IDs, enabled flags,
canonical center frequencies in Hz, and dwell durations in seconds.

The frontend may display each frequency in GHz or MHz. Unit selection is
display-only; API configuration remains in Hz.

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
      "duration_seconds": 2.0
    }
  ]
}
```

The regular analyzer status payload also contains `frequency_scan`, including
controller state, active entry ID and enabled-entry index, verified center
frequency, dwell duration, remaining dwell time, and last error.

## Scheduler behavior

The controller states are `idle`, `tuning`, `dwelling`, `stopping`, and
`error`. Enabled entries run in list order and loop continuously. Disabled
entries remain configured but are skipped.

Each tune uses the normal serialized analyzer reconfiguration transaction.
Dwell timing begins only after applied-state readback matches the requested
center frequency. Manual center-frequency requests are rejected while the scan
owns tuning. Stop leaves the analyzer at the most recently verified scan
frequency.

The initial UI list contains six enabled entries, each with a 5.0-second dwell:
400 MHz, 900 MHz, 2.44 GHz, 3.3 GHz, 5 GHz, and 5775 MHz. Newly added entries
also default to a 5.0-second dwell. The minimum and UI step are both 0.5
seconds.
Loss of analyzer availability or a failed/mismatched tune ends the scan in the
error state; it never dwells on an unverified frequency.

Phase 1 deliberately excludes pause/resume, reordering, presets, finite cycle
counts, settle-time configuration, skip actions, conditional stopping, and
AI-specific metadata.
