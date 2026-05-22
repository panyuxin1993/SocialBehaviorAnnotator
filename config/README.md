# Configuration

Shipped defaults and examples for the Social Behavior Annotator. Edit copies for your lab or point the app at project-specific files via **Annotation → Event types…** (CSV import).

## Event types (`event_types.csv`)

Columns (header row required):

| Column | Description |
|--------|-------------|
| `abbr` | Short token stored in the annotation table `type` column (e.g. `FT`). Leave empty to store the full type name. |
| `type` | Full label shown in the event-type combo box (e.g. `fight`). |
| `color` | Ethogram / legend color: `#RRGGBB`, 6-digit hex, or a Qt color name. |

- **`event_types.csv`** — loaded at startup as the default type list and colors.
- **`event_types.example.csv`** — extra example rows (e.g. `mounting`, `other`) you can merge or copy from.

Reload the app after editing `event_types.csv`, or use **Load CSV…** in the Event types dialog without restarting.

## Animal colors (`animal_colors.example.json`)

Example palette for role-table row backgrounds. The app currently uses the built-in list in `control_panel.py`; this file documents the default palette for reference or future use.
