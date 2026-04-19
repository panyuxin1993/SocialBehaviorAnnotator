# GUI Manual

This manual describes each GUI component in the Social Behavior Annotator.

## Main Window Layout

The window is split into two columns:

1. **Left column (full height)** — **Video panel** on top and **Navigator + Ethogram** along the bottom of that column.
2. **Right column (full height)** — **Control panel** (annotation UI) from top to bottom, with a **Console** at the bottom of the column.

---

## 1) Video Panel (left, upper area)

### Status bar
Shows current frame time and position:
- datetime string
- unix timestamp
- frame index

### Main video frame
- Displays current frame.
- Clicking the frame sends normalized coordinates to the annotation workflow.
- Role points can be overlaid with role labels.

---

## 2) Control Panel (right, full height)

### Zoom view
- Shows a zoomed crop centered at the last click location.
- Zoom factor is user configurable.

### Event timing
- **Set event start time**: stores current frame/time as event start.
- **Set event end time**: stores current frame/time as event end.
- Read-only text fields show captured values.

### Event type
- Editable dropdown with predefined values (`fighting`, `chasing`, `mounting`, `other`).
- You can type custom event labels.

### Animal role table
Columns:
- `name`
- `initiator`
- `victim`
- `intervenor`
- `observer`
- `winner`
- `loser`

Behavior:
- Animal rows use distinct background colors.
- Checking a role requests a frame click to capture that animal-role center coordinate.
- `winner` and `loser` can only be checked when the same row has `initiator` or `victim`.

### Other notes
- Free-text notes for event context.

### Submit new event
Validation:
- start time must be set
- event type must be provided
- at least one initiator must be selected

If valid, event is appended and persisted.

### Console
- Read-only log at the bottom of the right column (load/save, events, errors).

---

## 3) Navigator + Ethogram (left, lower area)

### Navigator row
- Slider to scrub through frames.
- Text input:
  - frame number (integer), or
  - datetime (`YYYY-MM-DD HH:MM:SS[.ffffff]`) to jump to nearest timestamped frame.
- `Previous event` / `Next event` buttons jump to neighboring event starts.
- Frame status indicator.

### Ethogram panel
- Displays event spans over the full video timeline.
- Red vertical cursor marks current frame.

---

## File Menu Actions

- **Open project inputs**
  - opens a single dialog with three fields (video, timestamps, annotation table); type paths or use **Browse…** / **Open…** / **Save as new…**
  - if the annotation path does not exist yet, you are prompted for animal names when loading
- **Extract all frames (fallback mode)**
  - saves frames to `workspace/<video_id>/frames`
  - enables frame-file based seeking
- **Save annotations**
  - writes annotation table to disk

---

## Annotation Table Fields

Per event-animal row includes:
- event metadata: `event_id`, `event_type`, `start/end_frame`
- time metadata: `start/end_datetime`, `start/end_unix`
- notes + animal name
- role boolean columns
- role coordinate columns (`<role>_point_xy`, as `x,y`)

