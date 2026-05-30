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
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "datasets" / "processed_by_me" / "aptos_old" / "aptos_reorganized_augmented_only"

SPLITS = ("train", "val", "test")
CLASSES = ("0", "1", "2", "3", "4")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
SEED = 42
JPEG_QUALITY = 95
PNG_COMPRESSION = 3
WORKERS = max((os.cpu_count() or 2) - 1, 1)
TRAIN_RATIO = 0.70
VAL_RATIO = 0.20
TEST_RATIO = 0.10


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Copiaza aptos_reorganized intr-un dataset separat si completeaza clasele "
            "prin augmentari simple, fara resize, crop, Ben Graham sau alte preprocesari."
        )
    )
    parser.add_argument("--input_dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output_dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--jpeg_quality", type=int, default=JPEG_QUALITY)
    parser.add_argument("--png_compression", type=int, default=PNG_COMPRESSION)
    parser.add_argument(
        "--target_mode",
        choices=("preprocess_match", "split_max", "custom"),
        default="preprocess_match",
        help=(
            "preprocess_match reproduce distributia din preprocess_aptos_reorganized_ben_graham: "
            "re-split 70/20/10 pe clasa si cate o augmentare per imagine."
        ),
    )
    parser.add_argument("--augmentations_per_image", type=int, default=1)
    parser.add_argument("--train_target", type=int, default=None)
    parser.add_argument("--val_target", type=int, default=None)
    parser.add_argument("--test_target", type=int, default=None)
    parser.add_argument("--resume", action="store_true", help="Sari peste fisierele deja existente.")
    parser.add_argument(
        "--no_overwrite",
        action="store_true",
        help="Nu sterge output-ul existent inainte de rulare.",
    )
    parser.add_argument("--dry_run", action="store_true", help="Afiseaza planul fara sa scrie fisiere.")
    return parser.parse_args()


def image_files(folder):
    return sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def reset_or_create_output(output_dir, overwrite):
    output_dir = output_dir.resolve()
    processed_root = (PROJECT_ROOT / "datasets" / "processed_by_me").resolve()

    if processed_root not in output_dir.parents:
        raise ValueError(f"Refuz sa scriu/sterg in afara datasets/processed_by_me: {output_dir}")

    if output_dir.exists() and overwrite:
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
            (output_dir / split / cls).mkdir(parents=True, exist_ok=True)


def collect_sources(input_dir):
    sources = {split: {cls: [] for cls in CLASSES} for split in SPLITS}

    for split in SPLITS:
        for cls in CLASSES:
            class_dir = input_dir / split / cls
            if not class_dir.exists():
                print(f"[skip] Lipseste folderul: {class_dir}")
                continue
            sources[split][cls] = image_files(class_dir)

    return sources


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


def get_targets(args, sources):
    if args.target_mode == "custom":
        targets = {
            "train": args.train_target,
            "val": args.val_target,
            "test": args.test_target,
        }
        missing = [split for split, target in targets.items() if target is None]
        if missing:
            raise ValueError(
                "Pentru --target_mode custom trebuie setate: --train_target, --val_target si --test_target"
            )
        return targets

    return {
        split: max((len(sources[split][cls]) for cls in CLASSES), default=0)
        for split in SPLITS
    }


def border_value_for(image):
    if image.ndim == 2:
        return 0
    channels = image.shape[2]
    if channels == 4:
        return (0, 0, 0, 255)
    return (0, 0, 0)


def apply_color_jitter(image, rng):
    if image.ndim == 2:
        alpha = rng.uniform(0.90, 1.10)
        beta = rng.uniform(-10.0, 10.0)
        return cv2.convertScaleAbs(image, alpha=alpha, beta=beta)

    has_alpha = image.shape[2] == 4
    alpha_channel = image[:, :, 3].copy() if has_alpha else None
    bgr = image[:, :, :3].copy() if has_alpha else image.copy()

    alpha = rng.uniform(0.90, 1.10)
    beta = rng.uniform(-10.0, 10.0)
    bgr = cv2.convertScaleAbs(bgr, alpha=alpha, beta=beta)

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 0] = (hsv[:, :, 0] + rng.uniform(-3.0, 3.0)) % 180
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * rng.uniform(0.90, 1.10), 0, 255)
    bgr = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    if has_alpha:
        return np.dstack((bgr, alpha_channel))
    return bgr


def augment_image(image, seed):
    rng = random.Random(seed)
    augmented = image.copy()

    if rng.random() < 0.5:
        augmented = cv2.flip(augmented, 1)
    if rng.random() < 0.15:
        augmented = cv2.flip(augmented, 0)

    height, width = augmented.shape[:2]
    angle = rng.uniform(-15.0, 15.0)
    scale = rng.uniform(0.95, 1.05)
    translate_x = rng.uniform(-0.03, 0.03) * width
    translate_y = rng.uniform(-0.03, 0.03) * height

    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, scale)
    matrix[0, 2] += translate_x
    matrix[1, 2] += translate_y

    augmented = cv2.warpAffine(
        augmented,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border_value_for(augmented),
    )

    if rng.random() < 0.8:
        augmented = apply_color_jitter(augmented, rng)

    return augmented


def make_tasks(args, sources, targets):
    tasks = []
    planned_counts = {split: Counter() for split in SPLITS}
    existing = 0
    rng = random.Random(args.seed + 1000)

    for split in SPLITS:
        target = targets[split]
        for cls in CLASSES:
            src_files = sources[split][cls]
            if not src_files:
                continue

            dst_dir = args.output_dir / split / cls

            for src_path in src_files:
                dst_path = dst_dir / src_path.name
                planned_counts[split][cls] += 1
                if args.resume and dst_path.exists():
                    existing += 1
                else:
                    tasks.append(("copy", src_path, dst_path, 0, args.jpeg_quality, args.png_compression))

            missing = max(target - len(src_files), 0)
            for index in range(missing):
                src_path = src_files[index % len(src_files)]
                seed = rng.randint(0, 2**31 - 1)
                dst_path = dst_dir / f"{src_path.stem}_aug_{index:04d}{src_path.suffix.lower()}"
                planned_counts[split][cls] += 1
                if args.resume and dst_path.exists():
                    existing += 1
                else:
                    tasks.append(("augment", src_path, dst_path, seed, args.jpeg_quality, args.png_compression))

    return tasks, planned_counts, existing


def make_preprocess_match_tasks(args, sources):
    tasks = []
    planned_counts = {split: Counter() for split in SPLITS}
    existing = 0
    rng = random.Random(args.seed + 1000)

    for cls in CLASSES:
        class_files = []
        for input_split in SPLITS:
            class_files.extend(sources[input_split][cls])

        if not class_files:
            continue

        split_map = split_items_70_20_10(class_files, seed=args.seed + int(cls))

        for split, files in split_map.items():
            dst_dir = args.output_dir / split / cls
            for src_path in files:
                dst_path = dst_dir / src_path.name
                planned_counts[split][cls] += 1
                if args.resume and dst_path.exists():
                    existing += 1
                else:
                    tasks.append(("copy", src_path, dst_path, 0, args.jpeg_quality, args.png_compression))

                for aug_index in range(args.augmentations_per_image):
                    seed = rng.randint(0, 2**31 - 1)
                    dst_path = dst_dir / f"{src_path.stem}_aug_{aug_index:02d}{src_path.suffix.lower()}"
                    planned_counts[split][cls] += 1
                    if args.resume and dst_path.exists():
                        existing += 1
                    else:
                        tasks.append(("augment", src_path, dst_path, seed, args.jpeg_quality, args.png_compression))

    return tasks, planned_counts, existing


def write_image(path, image, jpeg_quality, png_compression):
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
    if suffix == ".png":
        return cv2.imwrite(str(path), image, [cv2.IMWRITE_PNG_COMPRESSION, png_compression])
    return cv2.imwrite(str(path), image)


def process_one(task):
    task_type, src_path, dst_path, seed, jpeg_quality, png_compression = task

    if task_type == "copy":
        shutil.copy2(src_path, dst_path)
        return True, ""

    image = cv2.imread(str(src_path), cv2.IMREAD_UNCHANGED)
    if image is None:
        return False, f"Nu pot citi imaginea: {src_path}"

    augmented = augment_image(image, seed)
    if not write_image(dst_path, augmented, jpeg_quality, png_compression):
        return False, f"Nu pot scrie imaginea: {dst_path}"

    return True, ""


def write_dataset(tasks, workers):
    processed = 0
    skipped = 0

    if workers <= 1:
        for task in tqdm(tasks, desc="Augmentare"):
            ok, message = process_one(task)
            if ok:
                processed += 1
            else:
                skipped += 1
                print(f"[skip] {message}")
        return processed, skipped

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(process_one, task) for task in tasks]
        for future in tqdm(as_completed(futures), total=len(futures), desc=f"Augmentare ({workers} workers)"):
            ok, message = future.result()
            if ok:
                processed += 1
            else:
                skipped += 1
                print(f"[skip] {message}")

    return processed, skipped


def count_output(output_dir):
    counts = {split: Counter() for split in SPLITS}
    for split in SPLITS:
        for cls in CLASSES:
            class_dir = output_dir / split / cls
            counts[split][cls] = len(image_files(class_dir)) if class_dir.exists() else 0
    return counts


def print_counts(title, counts):
    print(f"\n{title}:")
    for split in SPLITS:
        values = [counts[split].get(cls, 0) for cls in CLASSES]
        print(f"  {split}: {values} | total={sum(values)}")


def main():
    args = parse_args()

    if not args.input_dir.exists():
        raise FileNotFoundError(f"Folderul sursa nu exista: {args.input_dir}")
    if args.output_dir.resolve() == args.input_dir.resolve():
        raise ValueError("Output-ul nu poate fi acelasi cu input-ul.")

    sources = collect_sources(args.input_dir)
    source_counts = {
        split: Counter({cls: len(sources[split][cls]) for cls in CLASSES})
        for split in SPLITS
    }
    targets = None if args.target_mode == "preprocess_match" else get_targets(args, sources)

    overwrite = not args.no_overwrite and not args.resume
    if not args.dry_run:
        reset_or_create_output(args.output_dir, overwrite=overwrite)

    if args.target_mode == "preprocess_match":
        tasks, planned_counts, existing = make_preprocess_match_tasks(args, sources)
    else:
        tasks, planned_counts, existing = make_tasks(args, sources, targets)

    print("Pipeline: copy originale + augmentari simple. Fara resize, crop, Ben Graham sau normalizare.")
    print("Augmentari: flip H 50%, flip V 15%, rotatie [-15, 15], scale [0.95, 1.05], translatie +/-3%, color jitter bland.")
    print(f"Sursa: {args.input_dir}")
    print(f"Output: {args.output_dir}")
    print(f"Target mode: {args.target_mode}")
    if args.target_mode == "preprocess_match":
        print(f"Split nou: {TRAIN_RATIO:.0%}/{VAL_RATIO:.0%}/{TEST_RATIO:.0%}")
        print(f"Augmentari per imagine: {args.augmentations_per_image}")
    else:
        print(f"Targets per clasa: train={targets['train']}, val={targets['val']}, test={targets['test']}")
    print(f"Workers: {args.workers}")
    print_counts("Distributie sursa", source_counts)
    print_counts("Distributie planificata output", planned_counts)
    print(f"\nFisiere de scris/copiat: {len(tasks)}")

    if existing:
        print(f"Fisiere deja existente, sarite prin --resume: {existing}")
    if args.dry_run:
        print("Dry run: nu am scris fisiere.")
        return

    processed, skipped = write_dataset(tasks, args.workers)
    final_counts = count_output(args.output_dir)

    print_counts("Distributie finala output", final_counts)
    print(f"\nDataset creat: {args.output_dir}")
    print(f"Fisiere scrise/copiate: {processed}")
    print(f"Fisiere sarite: {skipped}")


if __name__ == "__main__":
    main()
