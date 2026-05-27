import cv2
import numpy as np

def align_images(template_img, test_img):

    template_gray = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
    test_gray = cv2.cvtColor(test_img, cv2.COLOR_BGR2GRAY)

    orb = cv2.ORB_create(5000)

    kp1, des1 = orb.detectAndCompute(template_gray, None)
    kp2, des2 = orb.detectAndCompute(test_gray, None)

    # Safety check
    if des1 is None or des2 is None:
        return test_img

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = matcher.match(des1, des2)

    matches = sorted(matches, key=lambda x: x.distance)

    # FIX: Guard against too few matches (crashes findHomography)
    MIN_MATCH_COUNT = 10
    if len(matches) < MIN_MATCH_COUNT:
        print(f"[WARNING] align_images: only {len(matches)} matches found "
              f"(need {MIN_MATCH_COUNT}) — returning unaligned image.")
        return test_img

    pts1 = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1,1,2)
    pts2 = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1,1,2)

    H, mask = cv2.findHomography(pts2, pts1, cv2.RANSAC)

    if H is None:
        return test_img

    height, width = template_img.shape[:2]
    aligned = cv2.warpPerspective(test_img, H, (width, height))

    return aligned