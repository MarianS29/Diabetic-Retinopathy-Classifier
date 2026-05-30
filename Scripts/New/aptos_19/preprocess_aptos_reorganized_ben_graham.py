import argparse
import os
import random
import shutil
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "datasets" / "processed_by_me" / "aptos_old" / "aptos_reorganized"
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "datasets"
    / "processed_by_me"
    / "aptos_old"
    / "aptos_reorganized_ben_graham_augmented"
)

SPLITS = ("train", "val", "test")
CLASSES = ("0", "1", "2", "3", "4")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

IMG_SIZE = 512
PNG_COMPRESSION = 3
WORKERS = max((os.cpu_count() or 2) - 1, 1)
SEED = 42
TRAIN_RATIO = 0.70
VAL_RATIO = 0.20
TEST_RATIO = 0.10


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Aplica preprocesarea halo/Ben Graham din "
            "Diabetic_Balanced_Aug/augment+ben_graham_the_split_dataset.py "
            "pe aptos_reorganized, apoi augmentari geometrice pe toate spliturile."
        )
    )
    parser.add_argument("--input_dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output_dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--img_size", type=int, default=IMG_SIZE)
    parser.add_argument("--png_compression", type=int, default=PNG_COMPRESSION)
    parser.add_argument("--augmentations_per_image", type=int, default=1)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--resume", action="store_true", help="Sari peste imaginile deja existente.")
    parser.add_argument(
        "--no_overwrite",
        action="store_true",
        help="Nu sterge output-ul existent inainte de procesare.",
    )
    parser.add_argument("--dry_run", action="store_true", help="Afiseaza cate imagini ar fi procesate.")
    return parser.parse_args()


def image_files(folder):
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def split_items_70_20_10(items, seed):
    rng = random.Random(seed)
    items = list(items)
    rng.shuffle(items)

    total = len(items)
    train_count = round(total * TRAIN_RATIO)
    val_count = round(total * VAL_RATIO)

    return {
        "train": items[:train_count],
        "val": items[train_count:train_count + val_count],
        "test": items[train_count + val_count:],
    }


def reset_or_create_output(output_dir, overwrite):
    output_dir = output_dir.resolve()
    processed_root = (PROJECT_ROOT / "datasets" / "processed_by_me").resolve()

    if processed_root not in output_dir.parents:
        raise ValueError(f"Refuz sa sterg/scriu in afara datasets/processed_by_me: {output_dir}")

    if output_dir.exists() and overwrite:
        for attempt in range(5):
            try:
                shutil.rmtree(output_dir)
                break
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(1)

    output_dir.mkdir(parents=True, exist_ok=True)


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
        borderValue=0,
    )

    if rng.random() < 0.5:
        augmented = cv2.flip(augmented, 1)
    if rng.random() < 0.5:
        augmented = cv2.flip(augmented, 0)

    return augmented


def build_tasks(args, prepare_output=True):
    tasks = []
    input_counts = Counter()
    output_counts = {split: Counter() for split in SPLITS}
    existing = 0
    seed_rng = random.Random(args.seed + 1000)

    for cls in CLASSES:
        class_files = []
        for input_split in SPLITS:
            src_dir = args.input_dir / input_split / cls
            if src_dir.exists():
                files = image_files(src_dir)
                class_files.extend(files)
                input_counts[(input_split, cls)] = len(files)
            else:
                print(f"[skip] Lipseste folderul: {src_dir}")

        if not class_files:
            continue

        split_map = split_items_70_20_10(class_files, seed=args.seed + int(cls))

        for split, files in split_map.items():
            dst_dir = args.output_dir / split / cls
            if prepare_output:
                dst_dir.mkdir(parents=True, exist_ok=True)

            for src_path in files:
                dst_path = dst_dir / f"{src_path.stem}.png"
                output_counts[split][cls] += 1
                if args.resume and dst_path.exists():
                    existing += 1
                else:
                    tasks.append(("original", src_path, dst_path, 0, args.img_size, args.png_compression))

                for aug_index in range(args.augmentations_per_image):
                    seed = seed_rng.randint(0, 2**31 - 1)
                    aug_dst_path = dst_dir / f"{src_path.stem}_aug_{aug_index:02d}.png"
                    output_counts[split][cls] += 1
                    if args.resume and aug_dst_path.exists():
                        existing += 1
                        continue
                    tasks.append(("augmented", src_path, aug_dst_path, seed, args.img_size, args.png_compression))

    return tasks, input_counts, output_counts, existing


def process_one(task):
    task_type, src_path, dst_path, seed, img_size, png_compression = task
    image = cv2.imread(str(src_path), cv2.IMREAD_COLOR)
    if image is None:
        return False, f"Nu pot citi imaginea: {src_path}"

    processed = preprocess_testam_chestii(image, size=img_size)
    if task_type == "augmented":
        processed = augment_geometry(processed, seed)

    ok = cv2.imwrite(str(dst_path), processed, [cv2.IMWRITE_PNG_COMPRESSION, png_compression])
    if not ok:
        return False, f"Nu pot scrie imaginea: {dst_path}"

    return True, ""


def print_split_counts(counts):
    for split in SPLITS:
        class_counts = [counts[split].get(cls, 0) for cls in CLASSES]
        print(f"  {split}: {class_counts} | total={sum(class_counts)}")


def print_input_counts(input_counts):
    for split in SPLITS:
        class_counts = [input_counts.get((split, cls), 0) for cls in CLASSES]
        print(f"  {split}: {class_counts} | total={sum(class_counts)}")


def write_dataset(tasks, workers):
    processed = 0
    skipped = 0

    if workers <= 1:
        for task in tqdm(tasks, desc="Preprocesare"):
            ok, message = process_one(task)
            if ok:
                processed += 1
            else:
                skipped += 1
                print(f"[skip] {message}")
        return processed, skipped

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(process_one, task) for task in tasks]
        for future in tqdm(as_completed(futures), total=len(futures), desc=f"Preprocesare ({workers} workers)"):
            ok, message = future.result()
            if ok:
                processed += 1
            else:
                skipped += 1
                print(f"[skip] {message}")

    return processed, skipped


def main():
    args = parse_args()

    if not args.input_dir.exists():
        raise FileNotFoundError(f"Folderul sursa nu exista: {args.input_dir}")
    if args.output_dir.resolve() == args.input_dir.resolve():
        raise ValueError("Output-ul nu poate fi acelasi cu input-ul.")

    overwrite = not args.no_overwrite and not args.resume
    if not args.dry_run:
        reset_or_create_output(args.output_dir, overwrite=overwrite)
    tasks, input_counts, output_counts, existing = build_tasks(args, prepare_output=not args.dry_run)

    print("Preprocesare folosita: resize -> grayscale -> masca ochi -> Ben Graham grayscale -> halo")
    print("Augmentari dupa Ben Graham: rotatie [-30, 30], scale [0.90, 1.10], flip H/V 50%")
    print(f"Sursa: {args.input_dir}")
    print(f"Output: {args.output_dir}")
    print(f"Dimensiune imagine: {args.img_size}x{args.img_size}")
    print(f"Augmentari per imagine: {args.augmentations_per_image}")
    print(f"Split nou: {TRAIN_RATIO:.0%}/{VAL_RATIO:.0%}/{TEST_RATIO:.0%}")
    print(f"Workers: {args.workers}")
    print("\nDistributie sursa:")
    print_input_counts(input_counts)
    print("\nDistributie output planificata:")
    print_split_counts(output_counts)
    print(f"\nImagini de procesat: {len(tasks)}")

    if existing:
        print(f"Imagini deja existente, sarite prin --resume: {existing}")
    if args.dry_run:
        print("Dry run: nu am scris imagini.")
        return

    processed, skipped = write_dataset(tasks, args.workers)
    print(f"\nDataset creat: {args.output_dir}")
    print(f"Imagini procesate: {processed}")
    print(f"Imagini sarite: {skipped}")


if __name__ == "__main__":
    main()
