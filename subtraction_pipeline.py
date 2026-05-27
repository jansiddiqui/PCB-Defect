import cv2
import numpy as np
from align_images import align_images  # FIX: now actually used

def process_image(template_path, test_path, save_path):

    template = cv2.imread(template_path)
    test = cv2.imread(test_path)

    if template is None or test is None:
        print(f"[ERROR] Could not load image(s):\n  template: {template_path}\n  test:     {test_path}")
        return False

    # FIX: Align test image to template using ORB feature matching + homography
    # (previously only resized — misalignment caused false-positive diffs)
    test = align_images(template, test)

    # Convert to grayscale
    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    test_gray = cv2.cvtColor(test, cv2.COLOR_BGR2GRAY)

    # Blur
    template_gray = cv2.GaussianBlur(template_gray, (7,7), 0)
    test_gray = cv2.GaussianBlur(test_gray, (7,7), 0)

    # Normalize brightness
    template_gray = cv2.equalizeHist(template_gray)
    test_gray = cv2.equalizeHist(test_gray)

    # Subtract
    diff = cv2.absdiff(template_gray, test_gray)

    # Controlled threshold
    _, thresh = cv2.threshold(diff, 35, 255, cv2.THRESH_BINARY)

    # Morphology
    kernel = np.ones((5,5), np.uint8)
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)

    # Contour filtering
    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    mask = np.zeros_like(cleaned)

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if 50 < area < 5000:  # Balanced filter
            cv2.drawContours(mask, [cnt], -1, 255, -1)

    cv2.imwrite(save_path, mask)
    return True