"""Camera abstraction — UVCCamera (OpenCV), RealCamera (gphoto2), MockCamera."""

from __future__ import annotations

import logging
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .types import CardImage

logger = logging.getLogger(__name__)


class BaseCamera(ABC):
    @abstractmethod
    def capture(self) -> CardImage:
        """Capture a single full-resolution frame and return a CardImage."""

    def live_frame(self) -> np.ndarray | None:
        """Return a low-res preview frame (RGB), or None if unsupported."""
        return None

    def close(self) -> None:
        pass


class UVCCamera(BaseCamera):
    """
    USB/UVC camera via OpenCV (works with any webcam or USB camera on macOS/Linux).
    This is the primary path for the 48MP USB camera — no gphoto2 needed.
    """

    def __init__(
        self,
        camera_index: int = 1,
        save_dir: str | Path = "captures",
        rotate_90_cw: bool = False,
    ) -> None:
        self.camera_index = camera_index
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.rotate_90_cw = rotate_90_cw

        self._cap = cv2.VideoCapture(camera_index)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"Cannot open camera index {camera_index}. "
                "Check that the camera is connected and not in use by another app."
            )

        # Request maximum resolution from the camera
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  9999)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 9999)

        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logger.info("UVCCamera %d: %dx%d", camera_index, w, h)

    def live_frame(self) -> np.ndarray | None:
        """Grab a preview frame (used by the UI live preview)."""
        ret, bgr = self._cap.read()
        if not ret or bgr is None:
            return None
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if self.rotate_90_cw:
            rgb = cv2.rotate(rgb, cv2.ROTATE_90_CLOCKWISE)
        return rgb

    def capture(self) -> CardImage:
        """
        Capture a full-resolution still.
        Discards a few warm-up frames to let the sensor stabilise,
        then saves as JPEG.
        """
        # Discard warm-up frames (auto-exposure / auto-white-balance settle)
        for _ in range(5):
            self._cap.read()

        ret, bgr = self._cap.read()
        if not ret or bgr is None:
            raise RuntimeError("UVCCamera: failed to read frame from camera.")

        # Apply rotation if needed
        if self.rotate_90_cw:
            bgr = cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE)

        captured_at = datetime.now()
        dest = self.save_dir / captured_at.strftime("%Y%m%d_%H%M%S.jpg")
        cv2.imwrite(str(dest), bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
        logger.info("UVCCamera: saved %s  (%dx%d)", dest.name, bgr.shape[1], bgr.shape[0])

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        return CardImage(
            path=dest,
            rgb=rgb,
            captured_at=captured_at,
            camera_settings={
                "source": "uvc",
                "index": self.camera_index,
                "resolution": f"{bgr.shape[1]}x{bgr.shape[0]}",
            },
        )

    def close(self) -> None:
        if self._cap.isOpened():
            self._cap.release()

    @staticmethod
    def list_cameras() -> list[dict]:
        """Return list of available UVC cameras as [{"index": i, "resolution": "WxH"}]."""
        cameras = []
        for i in range(8):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cameras.append({"index": i, "resolution": f"{w}x{h}"})
            cap.release()
        return cameras


class MockCamera(BaseCamera):
    """Loads images from a fixtures directory in round-robin order."""

    SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

    def __init__(self, fixtures_dir: str | Path) -> None:
        self.fixtures_dir = Path(fixtures_dir)
        self._files: list[Path] = sorted(
            p for p in self.fixtures_dir.iterdir()
            if p.suffix.lower() in self.SUPPORTED_EXTENSIONS
        )
        if not self._files:
            raise FileNotFoundError(
                f"No image files found in fixtures directory: {self.fixtures_dir}"
            )
        self._index = 0
        logger.info("MockCamera: %d fixture(s) in %s", len(self._files), self.fixtures_dir)

    def capture(self) -> CardImage:
        path = self._files[self._index % len(self._files)]
        self._index += 1
        bgr = cv2.imread(str(path))
        if bgr is None:
            raise RuntimeError(f"MockCamera: failed to load: {path}")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        logger.debug("MockCamera: %s (%dx%d)", path.name, rgb.shape[1], rgb.shape[0])
        return CardImage(
            path=path, rgb=rgb, captured_at=datetime.now(),
            camera_settings={"source": "mock", "fixture": str(path)},
        )


class RealCamera(BaseCamera):
    """Tethered DSLR/mirrorless via gphoto2 (for future use with high-end cameras)."""

    def __init__(self, save_dir: str | Path = "captures") -> None:
        try:
            import gphoto2 as gp  # type: ignore
            self._gp = gp
        except ImportError as exc:
            raise ImportError(
                "gphoto2 Python bindings not installed. "
                "Run: conda install gphoto2 -c conda-forge"
            ) from exc
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self._camera = self._gp.Camera()
        self._camera.init()
        logger.info("RealCamera: connected via gphoto2")

    def capture(self) -> CardImage:
        import gphoto2 as gp  # type: ignore
        captured_at = datetime.now()
        file_path = self._camera.capture(gp.GP_CAPTURE_IMAGE)
        dest = self.save_dir / captured_at.strftime("%Y%m%d_%H%M%S_%f.jpg")
        camera_file = self._camera.file_get(
            file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL
        )
        camera_file.save(str(dest))
        logger.info("RealCamera: saved %s", dest)
        bgr = cv2.imread(str(dest))
        if bgr is None:
            raise RuntimeError(f"RealCamera: failed to read {dest}")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        return CardImage(
            path=dest, rgb=rgb, captured_at=captured_at,
            camera_settings={"source": "gphoto2", "file": file_path.name},
        )

    def close(self) -> None:
        try:
            self._camera.exit()
        except Exception:
            pass
