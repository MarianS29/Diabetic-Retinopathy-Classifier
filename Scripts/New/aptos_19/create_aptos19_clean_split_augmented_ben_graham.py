import os
import random
import re
import shutil
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm


PROJECT_ROOT = Path(__file__).resolve().parents[3]
APTOS_ROOT = PROJECT_ROOT / "datasets" / "processed_by_me" / "aptos_new"

INPUT_DIR = APTOS_ROOT / "aptos19_sorted"
CLEANED_DIR = APTOS_ROOT / "cleaned_dataset"
SPLIT_DIR = APTOS_ROOT / "final_split_dataset"
OUTPUT_DIR = APTOS_ROOT / "final_aptos_augmented+ben_graham_dataset"

SPLITS = ("train", "val", "test")
CLASSES = ("0", "1", "2", "3", "4")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

TRAIN_RATIO = 0.70
VAL_RATIO = 0.20
TEST_RATIO = 0.10
IMG_SIZE = 512
SEED = 42
PNG_COMPRESSION = 3
WORKERS = max((os.cpu_count() or 2) - 1, 1)

# Creste clasa majoritara cu 40%, apoi aduce fiecare clasa la aceeasi tinta.
AUGMENT_PERCENTAGE = 0.40

THRESHOLDS = {
    "0": {
        "blur_min": 55.0,
        "bright_min": 15.0,
        "bright_max": 180.0,
        "area_min": 0.25,
        "area_max": 0.95,
        "circularity_min": 0.84,
        "glare_max_ratio": 0.005,
    },
    "minoritare": {
        "blur_min": 15.0,
        "bright_min": 8.0,
        "bright_max": 220.0,
        "area_min": 0.15,
        "area_max": 0.98,
        "circularity_min": 0.60,
        "glare_max_ratio": 0.05,
    },
}


def image_files(folder):
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def reset_dir(path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def class_from_path(path):
    relative_parts = path.relative_to(INPUT_DIR).parts
    parent_names = [part.lower() for part in relative_parts[:-1]]

    if "no_dr" in parent_names:
        return "0"

    for part in reversed(relative_parts[:-1]):
        match = re.search(r"([0-4])$", part)
        if match:
            return match.group(1)

    raise ValueError(f"Nu pot determina clasa pentru imaginea: {path}")


def evaluate_image(image_path, cls):
    image = cv2.imread(str(image_path))
    if image is None:
        return False, "Eroare_Citire"

    rules = THRESHOLDS["0"] if cls == "0" else THRESHOLDS["minoritare"]

    image_resized = cv2.resize(image, (IMG_SIZE, IMG_SIZE))
    gray = cv2.cvtColor(image_resized, cv2.COLOR_BGR2GRAY)
    total_pixels = IMG_SIZE * IMG_SIZE

    non_black_pixels = gray[gray > 10]
    if len(non_black_pixels) == 0:
        return False, "Imagine_Neagra"

    mean_brightness = np.mean(non_black_pixels)
    if mean_brightness < rules["bright_min"]:
        return False, "Prea_Intunecata"
    if mean_brightness > rules["bright_max"]:
        return False, "Supraexpusa_Total"

    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if laplacian_var < rules["blur_min"]:
        return False, "Blurata"

    _, thresh = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
    kernel_clean = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    thresh_clean = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_clean)
    contours, _ = cv2.findContours(thresh_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False, "Fara_Contur"

    eye_contour = max(contours, key=cv2.contourArea)
    eye_area = cv2.contourArea(eye_contour)
    area_ratio = eye_area / total_pixels
    if area_ratio < rules["area_min"]:
        return False, "Zoom_Prea_Mic"
    if area_ratio > rules["area_max"]:
        return False, "Zoom_Exagerat_Taiat"

    perimeter = cv2.arcLength(eye_contour, True)
    if perimeter == 0:
        return False, "Eroare_Geometrie"

    circularity = (4 * np.pi * eye_area) / (perimeter * perimeter)
    if circularity < rules["circularity_min"]:
        return False, "Forma_Taiata_Neregulata"

    glare_ratio = np.sum(gray > 245) / (eye_area + 1e-6)
    if glare_ratio > rules["glare_max_ratio"]:
        return False, "Reflexie_Blit_Lentila"

    return True, "OK"


def clean_one(task):
    src_path, dst_path, cls = task
    is_valid, reason = evaluate_image(src_path, cls)
    if is_valid:
        shutil.copy2(src_path, dst_path)
    return is_valid, reason, cls


def clean_dataset():
    reset_dir(CLEANED_DIR)
    for cls in CLASSES:
        (CLEANED_DIR / cls).mkdir(parents=True, exist_ok=True)

    tasks = []
    for src_path in image_files(INPUT_DIR):
        cls = class_from_path(src_path)
        dst_path = CLEANED_DIR / cls / src_path.name
        tasks.append((src_path, dst_path, cls))

    if not tasks:
        raise ValueError(f"Nu s-au gasit imagini in: {INPUT_DIR}")

    print(f"\n[1/3] Curatare APTOS: {len(tasks)} imagini")
    stats = {cls: Counter() for cls in CLASSES}

    with ProcessPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(clean_one, task) for task in tasks]
        for future in tqdm(as_completed(futures), total=len(futures), desc="Curatare"):
            _, reason, cls = future.result()
            stats[cls][reason] += 1

    for cls in CLASSES:
        total = sum(stats[cls].values())
        ok = stats[cls].get("OK", 0)
        print(f"  Clasa {cls}: total={total} | pastrate={ok} | eliminate={total - ok}")


def split_dataset():
    reset_dir(SPLIT_DIR)
    for split in SPLITS:
        for cls in CLASSES:
            (SPLIT_DIR / split / cls).mkdir(parents=True, exist_ok=True)

    rng = random.Random(SEED)
    print("\n[2/3] Split 70/20/10")

    for cls in CLASSES:
        class_dir = CLEANED_DIR / cls
        items = [path for path in class_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
        rng.shuffle(items)

        total = len(items)
        train_count = round(total * TRAIN_RATIO)
        val_count = round(total * VAL_RATIO)

        split_map = {
            "train": items[:train_count],
            "val": items[train_count:train_count + val_count],
            "test": items[train_count + val_count:],
        }

        print(
            f"  Clasa {cls}: total={total} -> "
            f"train={len(split_map['train'])} | val={len(split_map['val'])} | test={len(split_map['test'])}"
        )

        for split, split_items in split_map.items():
            for src_path in split_items:
                shutil.copy2(src_path, SPLIT_DIR / split / cls / src_path.name)


def apply_color_jitter(image, seed, brightness=0.2, contrast=0.2, saturation=0.2, hue=0.02):
    rng = random.Random(seed + 10)
    alpha = rng.uniform(1.0 - contrast, 1.0 + contrast)
    bright_factor = rng.uniform(1.0 - brightness, 1.0 + brightness)
    image = cv2.convertScaleAbs(image, alpha=alpha * bright_factor, beta=0)

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 0] = (hsv[:, :, 0] + rng.uniform(-hue, hue) * 180) % 180
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * rng.uniform(1.0 - saturation, 1.0 + saturation), 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def augment_geometry(image, seed, split):
    rng = random.Random(seed)
    height, width = image.shape[:2]
    angle = rng.uniform(-30.0, 30.0)
    scale = rng.uniform(0.90, 1.10) if split == "train" else 1.0
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, scale)

    augmented = cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )

    if rng.random() < 0.5:
        augmented = cv2.flip(augmented, 1)
    if rng.random() < 0.5:
        augmented = cv2.flip(augmented, 0)
    return augmented


def preprocess_testam_chestii(image, size=IMG_SIZE):
    image_resized = cv2.resize(image, (size, size))
    gray = cv2.cvtColor(image_resized, cv2.COLOR_BGR2GRAY)

    _, thresh = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
    kernel_clean = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    thresh_clean = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_clean)
    contours, _ = cv2.findContours(thresh_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return gray

    eye_contour = max(contours, key=cv2.contourArea)
    eye_mask = np.zeros((size, size), dtype=np.uint8)
    cv2.drawContours(eye_mask, [eye_contour], -1, 255, thickness=cv2.FILLED)

    erode_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    eye_mask = cv2.erode(eye_mask, erode_kernel, iterations=1)

    sigma_x = size / 30.0
    blur = cv2.GaussianBlur(gray, (0, 0), sigma_x)
    ben_graham_gray = cv2.addWeighted(gray, 4, blur, -4, 128)

    exterior_mask = cv2.bitwise_not(eye_mask)
    dist = cv2.distanceTransform(exterior_mask, cv2.DIST_L2, 5)
    halo_width = 35.0

    final_image = np.full((size, size), 128.0, dtype=np.float32)
    halo_mask = (dist > 0) & (dist <= halo_width)
    final_image[halo_mask] = 128.0 * (dist[halo_mask] / halo_width)
    final_image[eye_mask == 255] = ben_graham_gray[eye_mask == 255]

    return final_image.astype(np.uint8)


def process_final_one(task):
    task_type, src_path, dst_path, seed, split = task
    image = cv2.imread(str(src_path), cv2.IMREAD_COLOR)
    if image is None:
        return False, f"Nu pot citi imaginea: {src_path}"

    if task_type == "augmented" and split == "train":
        image = apply_color_jitter(image, seed)

    processed = preprocess_testam_chestii(image)

    if task_type == "augmented":
        processed = augment_geometry(processed, seed, split)

    ok = cv2.imwrite(str(dst_path), processed, [cv2.IMWRITE_PNG_COMPRESSION, PNG_COMPRESSION])
    if not ok:
        return False, f"Nu pot scrie imaginea: {dst_path}"
    return True, ""


def split_counts():
    counts = {}
    for split in SPLITS:
        counts[split] = {
            cls: len(image_files(SPLIT_DIR / split / cls))
            for cls in CLASSES
        }
    return counts


def build_targets(counts):
    return {
        split: int(max(counts[split].values(), default=0) * (1.0 + AUGMENT_PERCENTAGE))
        for split in SPLITS
    }


def augment_and_preprocess_dataset():
    reset_dir(OUTPUT_DIR)
    for split in SPLITS:
        for cls in CLASSES:
            (OUTPUT_DIR / split / cls).mkdir(parents=True, exist_ok=True)

    counts = split_counts()
    targets = build_targets(counts)
    tasks = []
    rng = random.Random(SEED + 1000)

    print("\n[3/3] Augmentare + preprocess halo/Ben Graham")
    print(f"  Tinte pe clasa: {targets}")

    for split in SPLITS:
        for cls in CLASSES:
            source_items = image_files(SPLIT_DIR / split / cls)
            for src_path in source_items:
                dst_path = OUTPUT_DIR / split / cls / f"{src_path.stem}.png"
                tasks.append(("original", src_path, dst_path, 0, split))

            missing = targets[split] - len(source_items)
            if missing <= 0 or not source_items:
                continue

            for index in range(missing):
                src_path = source_items[index % len(source_items)]
                seed = rng.randint(0, 2**31 - 1)
                dst_path = OUTPUT_DIR / split / cls / f"{src_path.stem}_aug_{index:04d}.png"
                tasks.append(("augmented", src_path, dst_path, seed, split))

    processed = 0
    skipped = 0
    with ProcessPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(process_final_one, task) for task in tasks]
        for future in tqdm(as_completed(futures), total=len(futures), desc=f"Final ({WORKERS} workers)"):
            ok, message = future.result()
            if ok:
                processed += 1
            else:
                skipped += 1
                print(f"[skip] {message}")

    print(f"\nDataset final creat: {OUTPUT_DIR}")
    print(f"Imagini salvate: {processed} | Sarite: {skipped}")


def print_final_counts():
    print("\nDistributie finala:")
    for split in SPLITS:
        counts = [len(image_files(OUTPUT_DIR / split / cls)) for cls in CLASSES]
        print(f"  {split}: {counts} | total={sum(counts)}")


def main():
    if abs(TRAIN_RATIO + VAL_RATIO + TEST_RATIO - 1.0) > 1e-6:
        raise ValueError("Procentele train/val/test trebuie sa insumeze 1.0.")
    if not INPUT_DIR.exists():
        raise FileNotFoundError(f"Folderul sursa nu exista: {INPUT_DIR}")

    print(f"Sursa: {INPUT_DIR}")
    print(f"Output final: {OUTPUT_DIR}")
    clean_dataset()
    split_dataset()
    augment_and_preprocess_dataset()
    print_final_counts()


if __name__ == "__main__":
    main()
