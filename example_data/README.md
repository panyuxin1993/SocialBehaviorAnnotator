# Example data

## `TQT.csv` (tracking)

Per-frame animal center positions for overlay on video.

| Column | Description |
|--------|-------------|
| `clip` | Optional clip / session id |
| `timestamp` | Frame time (unix seconds or ns, same normalization as timestamp files) |
| `{id}_center_x`, `{id}_center_y` | Pixel coordinates of each tracked subject (e.g. `rat003_center_x`) |

Load via **File → Open project inputs** (optional **Tracking** path) or **File → Load tracking CSV…**. Use the **Show tracking** checkbox on the video panel to toggle the overlay.

## `behavior_event_df.csv`

Example behavior annotation table (project-specific schema).
