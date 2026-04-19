# Social Behavior Annotator

Desktop toolbox for manual social-behavior annotation from video and timestamps.

## Features
- Load a video file (`.mp4`, `.avi`, `.mov`, `.mkv`)
- Load timestamps from `.npy` or `.json`
- Load or create annotation table in `.csv` / `.xlsx`
- GUI layout:
  - **Left:** video (top) and navigator + ethogram (bottom)
  - **Right:** full-height event controls, role table, and a bottom **Console** log
- Save event annotations back to the table format
- Optional full-frame extraction fallback for slow random video access

## Requirements
- Python 3.10+
- PySide6
- opencv-python
- numpy
- pandas
- openpyxl

Install:

```bash
pip install PySide6 opencv-python numpy pandas openpyxl
```

## Launch

```bash
python -m app
```

## Quick Start
1. Launch app.
2. `File -> Open project inputs`.
3. In the dialog, set or browse to:
   - video file
   - timestamp file (`.npy` or `.json`)
   - annotation table (use **Open…** for an existing `.csv`/`.xlsx`, or **Save as new…** for a new file)
4. If a new table is created, enter comma-separated animal names when prompted.
5. Navigate frames with slider or jump box.
6. In right panel:
   - set event start/end
   - choose event type
   - select roles per animal (then click frame to capture role coordinate)
   - add notes
   - submit event
7. Save anytime via `File -> Save annotations`.

## Timestamp JSON Format
Supported JSON payloads:

```json
[1712499000.123, 1712499000.156, 1712499000.189]
```

or

```json
{"timestamps": [1712499000.123, 1712499000.156]}
```

## Notes
- `winner` and `loser` are only valid for rows where `initiator` or `victim` is checked.
- Saved table stores both datetime and unix timestamp fields.
- Use `File -> Extract all frames (fallback mode)` when direct frame seeking is too slow.

