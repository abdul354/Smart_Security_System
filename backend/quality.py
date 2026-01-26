import cv2
import numpy as np

def face_quality(face):
    return face_quality_details(face)["score"]


def face_quality_details(face):
    """Return simple quality metrics for a face crop.

    - blur: Laplacian variance (higher is sharper)
    - brightness: mean grayscale (0-255)
    - area: pixel area of the crop
    - score: 0..3 heuristic score
    """
    gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray))
    area = int(face.shape[0] * face.shape[1])

    score = 0
    if blur > 80:
        score += 1
    if 70 < brightness < 180:
        score += 1
    if area > 8000:
        score += 1

    return {
        "blur": blur,
        "brightness": brightness,
        "area": area,
        "score": score,
    }
