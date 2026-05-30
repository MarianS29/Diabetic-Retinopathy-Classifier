import os
import random
import re
import shutil
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = PROJECT_ROOT / "datasets" / "aptos19_sorted"
OUTPUT_DIR = PROJECT_ROOT / "datasets" / "my_dataset"

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

# Pastreaza comportamentul datasetului curent: balansare prin augmentare
AUGMENT_DATASET = True
AUGMENT_SPLITS = ("train", "val", "test")

# Procentul de crestere dorit fata de cea mai mare clasa (ex: 0.40 inseamna +40%)
# Scriptul va gasi clasa majoritara (uzual 0), o va creste cu acest procent, 
# si va echilibra toate celelalte clase pana la noua valoare tinta.
AUGMENT_PERCENTAGE = 0.40 

# Folderele locale sunt Proliferative3 si Severe4; pastram cifra din numele folderului.
SWAP_SEVERE_PROLIFERATIVE = False


def validate_ratios():
    total = TRAIN_RATIO + VAL_RATIO + TEST_RATIO
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"Raporturile trebuie sa insumeze 1.0, dar suma este {total:.6f}")


def image_files(folder):
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def class_from_path(path):
    relative_parts = path.relative_to(INPUT_DIR).parts
    parent_names = [part.lower() for part in relative_parts[:-1]]

    if "no_dr" in parent_names:
        return "0"

    for part in reversed(relative_parts[:-1]):
        match = re.search(r"([0-4])$", part)
        if match:
            cls = match.group(1)
            if SWAP_SEVERE_PROLIFERATIVE:
                return {"3": "4", "4": "3"}.get(cls, cls)
            return cls

    match = re.search(r"_([0-4])$", path.stem)
    if match:
        cls = match.group(1)
        if SWAP_SEVERE_PROLIFERATIVE:
            return {"3": "4", "4": "3"}.get(cls, cls)
        return cls

    raise ValueError(f"Nu pot determina clasa pentru imaginea: {path}")


def collect_items():
    items_by_class = defaultdict(list)
    for path in image_files(INPUT_DIR):
        cls = class_from_path(path)
        items_by_class[cls].append(path)
    return items_by_class


def split_items(items_by_class):
    rng = random.Random(SEED)
    split_map = {split: defaultdict(list) for split in SPLITS}

    for cls in CLASSES:
        items = list(items_by_class.get(cls, []))
        rng.shuffle(items)

        total = len(items)
        train_count = round(total * TRAIN_RATIO)
        val_count = round(total * VAL_RATIO)

        split_map["train"][cls].extend(items[:train_count])
        split_map["val"][cls].extend(items[train_count : train_count + val_count])
        split_map["test"][cls].extend(items[train_count + val_count :])

    return split_map


def preprocess_testam_chestii(image, size=IMG_SIZE):
    img_resized = cv2.resize(image, (size, size))
    gray = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)

    _, thresh = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)

    kernel_clean = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    thresh_clean = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_clean)

    contours, _ = cv2.findContours(thresh_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return gray

    contur_ochi = max(contours, key=cv2.contourArea)
    masca_ochi = np.zeros((size, size), dtype=np.uint8)
    cv2.drawContours(masca_ochi, [contur_ochi], -1, 255, thickness=cv2.FILLED)

    kernel_eroziune = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    masca_ochi = cv2.erode(masca_ochi, kernel_eroziune, iterations=1)

    sigma_x = size / 30.0
    blur = cv2.GaussianBlur(gray, (0, 0), sigma_x)
    ben_graham_gray = cv2.addWeighted(gray, 4, blur, -4, 128)

    masca_exterior = cv2.bitwise_not(masca_ochi)
    dist = cv2.distanceTransform(masca_exterior, cv2.DIST_L2, 5)
    halo_width = 35.0

    rezultat_final = np.full((size, size), 128.0, dtype=np.float32)
    halo_mask = (dist > 0) & (dist <= halo_width)
    fraction = dist[halo_mask] / halo_width
    rezultat_final[halo_mask] = 128.0 * fraction

    interior_mask = masca_ochi == 255
    rezultat_final[interior_mask] = ben_graham_gray[interior_mask]

    return rezultat_final.astype(np.uint8)


def apply_color_jitter(image, rng, brightness=0.2, contrast=0.2, saturation=0.2, hue=0.02):
    # Simuleaza T.ColorJitter
    alpha = rng.uniform(1.0 - contrast, 1.0 + contrast)
    bright_factor = rng.uniform(1.0 - brightness, 1.0 + brightness)
    
    image = cv2.convertScaleAbs(image, alpha=alpha * bright_factor, beta=0)
    
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    hue_shift = rng.uniform(-hue, hue) * 180
    hsv[:, :, 0] = (hsv[:, :, 0] + hue_shift) % 180
    
    sat_factor = rng.uniform(1.0 - saturation, 1.0 + saturation)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * sat_factor, 0, 255)
    
    hsv = hsv.astype(np.uint8)
    
    # Aici era eroarea: folosim cv2.COLOR_HSV2BGR
    image = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    return image

def augment_image(image, seed, split):
    rng = random.Random(seed)
    height, width = image.shape[:2]

    # Ambele split-uri primesc RandomRotation(degrees=30)
    angle = rng.uniform(-30.0, 30.0)
    scale = 1.0

    # Daca e 'train', adaugam RandomAffine (scale/zoom) si ColorJitter
    if split == "train":
        scale = rng.uniform(0.90, 1.10)
        image = apply_color_jitter(image, rng)

    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, scale)

    augmented = cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0)
    )

    # Ambele split-uri primesc RandomHorizontalFlip(p=0.5) si RandomVerticalFlip(p=0.5)
    if rng.random() < 0.5:
        augmented = cv2.flip(augmented, 1)
    if rng.random() < 0.5:
        augmented = cv2.flip(augmented, 0)

    return augmented


def safe_prepare_output():
    output_dir = OUTPUT_DIR.resolve()
    datasets_root = (PROJECT_ROOT / "datasets").resolve()

    if datasets_root not in output_dir.parents:
        raise ValueError(f"Refuz sa scriu in afara folderului datasets: {output_dir}")
    if output_dir.name != "my_dataset":
        raise ValueError(f"Output neasteptat: {output_dir}")

    if output_dir.exists():
        for attempt in range(5):
            try:
                shutil.rmtree(output_dir)
                break
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(1)

    for split in SPLITS:
        for cls in CLASSES:
            (OUTPUT_DIR / split / cls).mkdir(parents=True, exist_ok=True)


def make_original_tasks(split_map):
    tasks = []
    for split in SPLITS:
        for cls in CLASSES:
            for src_path in split_map[split][cls]:
                dst_path = OUTPUT_DIR / split / cls / f"{src_path.stem}.png"
                tasks.append(("original", src_path, dst_path, 0, split))
    return tasks


def make_augmented_tasks(split_map):
    tasks = []
    rng = random.Random(SEED + 1000)

    for split in SPLITS:
        if split not in AUGMENT_SPLITS:
            continue
            
        # Calculam valoarea tinta dinamic: clasa maxima din acest split + procentul ales
        counts = {cls: len(split_map[split][cls]) for cls in CLASSES}
        max_count = max(counts.values(), default=0)
        target_count = int(max_count * (1.0 + AUGMENT_PERCENTAGE))

        for cls in CLASSES:
            source_items = split_map[split][cls]
            missing = target_count - len(source_items)
            if missing <= 0 or not source_items:
                continue

            for index in range(missing):
                src_path = source_items[index % len(source_items)]
                seed = rng.randint(0, 2**31 - 1)
                dst_path = OUTPUT_DIR / split / cls / f"{src_path.stem}_aug_{index:04d}.png"
                tasks.append(("augmented", src_path, dst_path, seed, split))

    return tasks


def process_one(task):
    task_type, src_path, dst_path, seed, split = task
    
    image = cv2.imread(str(src_path), cv2.IMREAD_COLOR)
    if image is None:
        return False, f"Nu pot citi imaginea: {src_path}"

    if task_type == "augmented":
        image = augment_image(image, seed, split)

    processed = preprocess_testam_chestii(image)
    
    ok = cv2.imwrite(str(dst_path), processed, [cv2.IMWRITE_PNG_COMPRESSION, PNG_COMPRESSION])
    if not ok:
        return False, f"Nu pot scrie imaginea: {dst_path}"

    return True, ""


def write_tasks(tasks):
    processed = 0
    skipped = 0

    if WORKERS <= 1:
        for task in tqdm(tasks, desc="write"):
            ok, message = process_one(task)
            if ok:
                processed += 1
            else:
                skipped += 1
                print(f"[skip] {message}")
        return processed, skipped

    with ProcessPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(process_one, task) for task in tasks]
        for future in tqdm(as_completed(futures), total=len(futures), desc=f"write ({WORKERS} workers)"):
            ok, message = future.result()
            if ok:
                processed += 1
            else:
                skipped += 1
                print(f"[skip] {message}")

    return processed, skipped


def count_split_map(split_map):
    return {
        split: Counter({cls: len(split_map[split][cls]) for cls in CLASSES})
        for split in SPLITS
    }


def count_output():
    counts = {split: Counter() for split in SPLITS}
    for split in SPLITS:
        for cls in CLASSES:
            folder = OUTPUT_DIR / split / cls
            counts[split][cls] = len(image_files(folder)) if folder.exists() else 0
    return counts


def print_counts(title, counts):
    print(f"\n{title}:")
    for split in SPLITS:
        values = [counts[split].get(cls, 0) for cls in CLASSES]
        print(f"{split:>5}: {values} | total={sum(values)}")


def main():
    validate_ratios()

    if not INPUT_DIR.exists():
        raise FileNotFoundError(f"Nu exista folderul sursa: {INPUT_DIR}")

    items_by_class = collect_items()
    source_counts = Counter({cls: len(items_by_class.get(cls, [])) for cls in CLASSES})
    if sum(source_counts.values()) == 0:
        raise ValueError(f"Nu am gasit imagini in: {INPUT_DIR}")

    split_map = split_items(items_by_class)
    split_counts = count_split_map(split_map)
    original_tasks = make_original_tasks(split_map)
    augmented_tasks = make_augmented_tasks(split_map) if AUGMENT_DATASET else []
    all_tasks = original_tasks + augmented_tasks

    print(f"Sursa: {INPUT_DIR}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Resize: {IMG_SIZE}x{IMG_SIZE}")
    print("Pipeline: Augmentare -> Ben Graham grayscale + contour-fitted black halo + gray exterior")
    print(f"Split: train={TRAIN_RATIO:.2f}, val={VAL_RATIO:.2f}, test={TEST_RATIO:.2f}")
    
    print(f"\nLogica Augmentare: Oversampling cu target +{int(AUGMENT_PERCENTAGE * 100)}% fata de clasa majoritara")
    print("\nAugmentari Train:")
    print(" - RandomHorizontalFlip(p=0.5)\n - RandomVerticalFlip(p=0.5)\n - RandomRotation(30)\n - RandomZoom/Affine(0.9, 1.1)\n - ColorJitter(0.2, 0.2, 0.2, 0.02)")
    
    print("\nAugmentari Test/Val:")
    print(" - RandomHorizontalFlip(p=0.5)\n - RandomVerticalFlip(p=0.5)\n - RandomRotation(30)")
    
    print(f"\nWorkers: {WORKERS}")
    print(f"\nDistributie sursa 0..4: {[source_counts.get(cls, 0) for cls in CLASSES]}")
    print_counts("Dupa split, inainte de augmentare", split_counts)
    print(f"\nImagini originale de scris: {len(original_tasks)}")
    print(f"Imagini augmentate de scris: {len(augmented_tasks)}")

    safe_prepare_output()
    processed, skipped = write_tasks(all_tasks)
    output_counts = count_output()

    print_counts("Distributie finala output (Echilibrata dinamic)", output_counts)
    print(f"\nDataset creat: {OUTPUT_DIR}")
    print(f"Imagini scrise: {processed}")
    print(f"Imagini sarite: {skipped}")


if __name__ == "__main__":
    main()