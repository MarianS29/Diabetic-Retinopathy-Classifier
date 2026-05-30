import os
import random
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm

# ==========================================
# CONFIGURARE CAI SI PARAMETRI
# ==========================================
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Folderul unde ai facut impartirea anterioara (curatat si impartit 70/20/10)
INPUT_DIR = PROJECT_ROOT / "datasets" / "processed_by_me" / "balanced_aug_new" / "final_split_dataset"

# Noul folder in care vom salva varianta finala (Ben Graham + Augmentare)
OUTPUT_DIR = PROJECT_ROOT / "datasets" / "processed_by_me" / "balanced_aug_new" / "final_balanced_augmented+ben_graham_dataset"

SPLITS = ("train", "val", "test")
CLASSES = ("0", "1", "2", "3", "4")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

IMG_SIZE = 512
SEED = 42
PNG_COMPRESSION = 3
WORKERS = max((os.cpu_count() or 2) - 1, 1)

# ==========================================
# TINTE DE ECHILIBRARE
# ==========================================
TARGET_COUNTS = {
    "train": 7418,
    "val": 2066,
    "test": 1054
}

def image_files(folder):
    return sorted(
        path for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )

def augment_geometry(image, seed):
    rng = random.Random(seed)
    height, width = image.shape[:2]

    angle = rng.uniform(-30.0, 30.0)
    scale = rng.uniform(0.90, 1.10)
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, scale)

    augmented = cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0
    )

    if rng.random() < 0.5:
        augmented = cv2.flip(augmented, 1)
    if rng.random() < 0.5:
        augmented = cv2.flip(augmented, 0)

    return augmented

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

def process_one(task):
    task_type, src_path, dst_path, seed, split = task
    
    # 1. Citim imaginea color originala
    image = cv2.imread(str(src_path), cv2.IMREAD_COLOR)
    if image is None:
        return False, f"Nu pot citi imaginea: {src_path}"

    # 2. Procesare matematica (Ochiul devine gri, cu halo, pe fundal 128)
    processed = preprocess_testam_chestii(image)
    
    # 3. Augmentare geometrica dupa Ben Graham, identica pentru train/val/test.
    if task_type == "augmented":
        processed = augment_geometry(processed, seed)
    
    # 4. Salvare pe disk
    ok = cv2.imwrite(str(dst_path), processed, [cv2.IMWRITE_PNG_COMPRESSION, PNG_COMPRESSION])
    if not ok:
        return False, f"Nu pot scrie imaginea: {dst_path}"

    return True, ""

def main():
    if not INPUT_DIR.exists():
        raise FileNotFoundError(f"Folderul sursa nu exista: {INPUT_DIR}")

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
        
    for split in SPLITS:
        for cls in CLASSES:
            (OUTPUT_DIR / split / cls).mkdir(parents=True, exist_ok=True)

    tasks = []
    rng = random.Random(SEED + 1000)

    print(f"\nGeneram task-urile de preprocesare + augmentare...")
    print(f"Sursa: {INPUT_DIR}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Tinte finale calculate: Train={TARGET_COUNTS['train']}, Val={TARGET_COUNTS['val']}, Test={TARGET_COUNTS['test']}\n")

    for split in SPLITS:
        target_count = TARGET_COUNTS[split]
        
        for cls in CLASSES:
            class_dir = INPUT_DIR / split / cls
            if not class_dir.exists():
                continue
                
            source_items = image_files(class_dir)
            if not source_items:
                continue

            # 1. Adaugam imaginile originale
            for src_path in source_items:
                dst_path = OUTPUT_DIR / split / cls / f"{src_path.stem}.png"
                tasks.append(("original", src_path, dst_path, 0, split))

            # 2. Adaugam imaginile augmentate pana la target
            missing = target_count - len(source_items)
            if missing > 0:
                for index in range(missing):
                    src_path = source_items[index % len(source_items)]
                    seed = rng.randint(0, 2**31 - 1)
                    dst_path = OUTPUT_DIR / split / cls / f"{src_path.stem}_aug_{index:04d}.png"
                    tasks.append(("augmented", src_path, dst_path, seed, split))

    print(f"Avem de procesat in total {len(tasks)} imagini.")
    
    processed = 0
    skipped = 0

    with ProcessPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(process_one, task) for task in tasks]
        for future in tqdm(as_completed(futures), total=len(futures), desc=f"Pipeline Final ({WORKERS} workers)"):
            ok, message = future.result()
            if ok:
                processed += 1
            else:
                skipped += 1
                print(f"\n[skip] {message}")

    print(f"\nDataset creat cu succes in: {OUTPUT_DIR}")
    print(f"Imagini salvate: {processed} | Sarite: {skipped}")

if __name__ == "__main__":
    main()
