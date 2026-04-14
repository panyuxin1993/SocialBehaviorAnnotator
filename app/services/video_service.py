from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


class VideoService:
    def __init__(self) -> None:
        self.video_path: Path | None = None
        self.capture: cv2.VideoCapture | None = None
        self.total_frames: int = 0
        self.fps: float = 0.0
        self.current_frame_index: int = 0

        self._extracted_frames_dir: Path | None = None
        self._use_frame_files = False

    def load_video(self, video_path: str | Path) -> None:
        self.release()
        path = Path(video_path)
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise ValueError(f"Unable to open video: {path}")

        self.video_path = path
        self.capture = cap
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.current_frame_index = 0
        self._use_frame_files = False
        self._extracted_frames_dir = None

    def enable_frame_extraction_mode(self, workspace_root: str | Path, video_id: str) -> Path:
        if self.capture is None:
            raise ValueError("Load video first before extracting frames.")

        target_dir = Path(workspace_root) / video_id / "frames"
        target_dir.mkdir(parents=True, exist_ok=True)

        if any(target_dir.glob("*.jpg")):
            self._extracted_frames_dir = target_dir
            self._use_frame_files = True
            return target_dir

        for idx in range(self.total_frames):
            frame = self.get_frame(idx, prefer_extracted=False)
            out_path = target_dir / f"{idx:08d}.jpg"
            cv2.imwrite(str(out_path), frame)

        self._extracted_frames_dir = target_dir
        self._use_frame_files = True
        return target_dir

    def get_frame(self, frame_index: int, prefer_extracted: bool = True) -> np.ndarray:
        if self._use_frame_files and prefer_extracted and self._extracted_frames_dir is not None:
            frame_path = self._extracted_frames_dir / f"{max(0, min(frame_index, self.total_frames - 1)):08d}.jpg"
            frame = cv2.imread(str(frame_path))
            if frame is not None:
                self.current_frame_index = frame_index
                return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        if self.capture is None:
            raise ValueError("No video loaded.")

        index = max(0, min(frame_index, max(self.total_frames - 1, 0)))
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.capture.read()
        if not ok or frame is None:
            raise ValueError(f"Cannot read frame {index}.")

        self.current_frame_index = index
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def release(self) -> None:
        if self.capture is not None:
            self.capture.release()
        self.capture = None

