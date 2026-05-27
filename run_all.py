import os
from subtraction_pipeline import process_image
from tqdm import tqdm

DATASET_PATH  = "PCB_DATASET"
TEMPLATE_PATH = os.path.join(DATASET_PATH, "PCB_USED")
IMAGES_PATH   = os.path.join(DATASET_PATH, "images")
OUTPUT_PATH   = "output_masks"

os.makedirs(OUTPUT_PATH, exist_ok=True)

total_processed = 0
total_skipped   = 0

for defect_class in os.listdir(IMAGES_PATH):

    class_path = os.path.join(IMAGES_PATH, defect_class)

    if not os.path.isdir(class_path):
        continue

    output_class_path = os.path.join(OUTPUT_PATH, defect_class)
    os.makedirs(output_class_path, exist_ok=True)

    for filename in tqdm(os.listdir(class_path), desc=defect_class):

        # Accept both .jpg and .JPG (FIX: was only accepting .jpg)
        if not filename.lower().endswith(".jpg"):
            continue

        board_id = filename.split("_")[0]

        # FIX: Check both .JPG and .jpg casing for the template file
        template_file = None
        for ext in (".JPG", ".jpg", ".png", ".PNG"):
            candidate = os.path.join(TEMPLATE_PATH, board_id + ext)
            if os.path.exists(candidate):
                template_file = candidate
                break

        test_full_path = os.path.join(class_path, filename)
        save_path      = os.path.join(output_class_path, filename)

        if template_file is not None:
            result = process_image(template_file, test_full_path, save_path)
            if result:
                total_processed += 1
            else:
                total_skipped += 1
        else:
            # FIX: was silently skipping — now warns the user
            print(f"[WARNING] No template found for board ID '{board_id}' "
                  f"(image: {filename}) — skipping.")
            total_skipped += 1

print(f"\nDone. Processed: {total_processed} | Skipped: {total_skipped}")