import cv2
import numpy as np
from threading import Thread, Lock
import time

class VideoCamera:
    def __init__(self, src=0):
        self.cap = cv2.VideoCapture(src)

        if not self.cap.isOpened():
            raise RuntimeError("Camera failed to open")
        self.lock = Lock()
        self.running = True
        self.frame = None
        self._running_luma = None
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(6, 6))

        self._configure_capture()

        self.thread = Thread(target=self.update_frame, daemon=True)
        self.thread.start()

    def _configure_capture(self):
        # Reduce buffering to drop stale frames and let camera auto-adjust when possible.
        for prop, value in (
            (cv2.CAP_PROP_BUFFERSIZE, 1),
            (cv2.CAP_PROP_FPS, 30),
        ):
            try:
                self.cap.set(prop, value)
            except Exception:
                pass

        # Auto exposure constants differ between backends; ignore failures silently.
        for value in (0.75, 1.0):
            try:
                if self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, value):
                    break
            except Exception:
                continue

        try:
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
        except Exception:
            pass

    def _preprocess_frame(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        luma = float(np.mean(gray))

        if self._running_luma is None:
            self._running_luma = luma
        else:
            self._running_luma = 0.8 * self._running_luma + 0.2 * luma

        # Adaptive histogram equalization for low-light frames.
        if self._running_luma < 95:
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            l = self._clahe.apply(l)
            lab = cv2.merge((l, a, b))
            frame = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        elif self._running_luma > 175:
            frame = cv2.convertScaleAbs(frame, alpha=0.85, beta=-12)

        # Gentle denoise to stabilise embeddings without blurring edges heavily.
        frame = cv2.bilateralFilter(frame, d=5, sigmaColor=40, sigmaSpace=40)
        return frame

    def update_frame(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                try:
                    frame = self._preprocess_frame(frame)
                except Exception:
                    # If preprocessing fails keep raw frame.
                    pass
                with self.lock:
                    self.frame = frame
            time.sleep(0.01)

    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def release(self):
        self.running = False
        self.thread.join()
        self.cap.release()

    def stop(self):
        self.running = False
        if self.cap is not None:
            self.cap.release()
            self.cap = None
