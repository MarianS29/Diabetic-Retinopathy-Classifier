import argparse
import csv
import os
import random
import shutil
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cv2
from PIL import Image
from tqdm import tqdm


SPLITS = ("train", "val", "test")
CLASSES = ("0", "1", "2", "3", "4")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def parse_args():
    root = Path(__file__).resolve().parents[1]
    source_root = root / "datasets" / "Diabetic_Balanced_Aug"

    parser = argparse.ArgumentParser(
        description=(
            "Creeaza datasets/Diabetic_Balanced_Aug_Ben_Graham din "
            "Diabetic_Balanced_Aug, folosind transformarea din ben_graham.ipynb "
            "si organizarea ImageFolder train/val/test/0..4."
        )
    )
    parser.add_argument("--images_dir", type=Path, default=source_root / "resized_train_cropped")
    parser.add_argument("--labels_csv", type=Path, default=source_root / "trainLabels_cropped.csv")
    parser.add_argument(
        "--mode_reference_dir",
        type=Path,
        default=root / "datasets" / "Diabetic_Balanced_Data",
        help="Folder folosit ca referinta pentru pastrarea imaginilor grayscale/RGB dupa nume.",
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=root / "datasets" / "Diabetic_Balanced_Aug_Ben_Graham",
    )
    parser.add_argument("--train_ratio", type=float, default=0.70)
    parser.add_argument("--val_ratio", type=float, default=0.20)
    parser.add_argument("--test_ratio", type=float, default=0.10)
    parser.add_argument("--img_size", type=int, default=512)
    parser.add_argument("--jpeg_quality", type=int, default=95)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=max((os.cpu_count() or 2) - 1, 1))
    parser.add_argument("--no_overwrite", action="store_true")
    parser.add_argument("--no_mode_reference", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continua peste un output partial si sare peste imaginile deja generate.",
    )
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args()


def validate_ratios(args):
    total = args.train_ratio + args.val_ratio + args.test_ratio
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"Raporturile trebuie sa insumeze 1.0, dar suma este {total:.6f}")


def image_files(folder):
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def build_image_index(images_dir):
    index = {}
    duplicates = set()

    for path in image_files(images_dir):
        for key in {path.name.lower(), path.stem.lower()}:
            if key in index and index[key] != path:
                duplicates.add(key)
            index[key] = path

    for key in duplicates:
        index.pop(key, None)

    return index, duplicates


def load_labeled_images(labels_csv, image_index):
    items_by_class = defaultdict(list)
    missing = []
    invalid = []

    with labels_csv.open("r", newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            image_name = (row.get("image") or "").strip()
            level = (row.get("level") or "").strip()

            if not image_name or level not in CLASSES:
                invalid.append(row)
                continue

            key = image_name.lower()
            src_path = image_index.get(key) or image_index.get(Path(image_name).stem.lower())
            if src_path is None:
                missing.append(image_name)
                continue

            items_by_class[level].append(src_path)

    return items_by_class, missing, invalid


def split_items(items_by_class, args):
    rng = random.Random(args.seed)
    split_map = {split: [] for split in SPLITS}

    for cls in CLASSES:
        items = list(items_by_class.get(cls, []))
        rng.shuffle(items)

        total = len(items)
        train_count = round(total * args.train_ratio)
        val_count = round(total * args.val_ratio)

        split_map["train"].extend((path, cls) for path in items[:train_count])
        split_map["val"].extend((path, cls) for path in items[train_count : train_count + val_count])
        split_map["test"].extend((path, cls) for path in items[train_count + val_count :])

    return split_map


def ben_graham_transform(image, img_size):
    image = cv2.resize(image, (img_size, img_size))
    sigma = img_size / 30.0
    blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=sigma)
    return cv2.addWeighted(image, 4, blurred, -4, 128)


def build_mode_reference(reference_dir):
    if not reference_dir.exists():
        return {}

    modes_by_name = defaultdict(Counter)
    for path in image_files(reference_dir):
        try:
            with Image.open(path) as image:
                modes_by_name[path.name.lower()][image.mode] += 1
        except OSError:
            continue

    return {
        name: modes.most_common(1)[0][0]
        for name, modes in modes_by_name.items()
        if len(modes) == 1
    }


def safe_prepare_output(output_dir, overwrite):
    output_dir = output_dir.resolve()
    project_root = Path(__file__).resolve().parents[1]
    datasets_root = (project_root / "datasets").resolve()

    if datasets_root not in output_dir.parents:
        raise ValueError(f"Refuz sa scriu in afara folderului datasets: {output_dir}")
    if output_dir.name != "Diabetic_Balanced_Aug_Ben_Graham":
        raise ValueError(f"Output neasteptat: {output_dir}")

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


def make_unique_name(src_path, used_names):
    name = src_path.name
    if name.lower() not in used_names:
        used_names.add(name.lower())
        return name

    index = 1
    while True:
        candidate = f"{src_path.stem}_{index:03d}{src_path.suffix}"
        if candidate.lower() not in used_names:
            used_names.add(candidate.lower())
            return candidate
        index += 1


def process_one(task):
    src_path, dst_path, img_size, jpeg_quality, output_mode = task
    image = cv2.imread(str(src_path), cv2.IMREAD_UNCHANGED)
    if image is None:
        return False, f"Nu pot citi imaginea: {src_path}"

    processed_image = ben_graham_transform(image, img_size)
    if output_mode == "L" and len(processed_image.shape) == 3:
        processed_image = cv2.cvtColor(processed_image, cv2.COLOR_BGR2GRAY)

    if dst_path.suffix.lower() in {".jpg", ".jpeg"}:
        ok = cv2.imwrite(str(dst_path), processed_image, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
    else:
        ok = cv2.imwrite(str(dst_path), processed_image)

    if not ok:
        return False, f"Nu pot scrie imaginea: {dst_path}"
    return True, ""


def write_dataset(split_map, args):
    safe_prepare_output(args.output_dir, overwrite=not args.no_overwrite and not args.resume)

    used_names = {split: {cls: set() for cls in CLASSES} for split in SPLITS}
    mode_reference = {} if args.no_mode_reference else build_mode_reference(args.mode_reference_dir)
    tasks = []
    existing = 0
    for split in SPLITS:
        for src_path, cls in split_map[split]:
            output_name = make_unique_name(src_path, used_names[split][cls])
            dst_path = args.output_dir / split / cls / output_name
            if args.resume and dst_path.exists():
                existing += 1
                continue
            output_mode = mode_reference.get(output_name.lower())
            tasks.append((src_path, dst_path, args.img_size, args.jpeg_quality, output_mode))

    processed = 0
    skipped = 0

    if existing:
        print(f"Imagini deja existente: {existing}")
    if not tasks:
        return processed, skipped

    if args.workers <= 1:
        for task in tqdm(tasks, desc="process"):
            ok, message = process_one(task)
            if ok:
                processed += 1
            else:
                skipped += 1
                print(f"[skip] {message}")
        return processed, skipped

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(process_one, task) for task in tasks]
        for future in tqdm(as_completed(futures), total=len(futures), desc=f"process ({args.workers} workers)"):
            ok, message = future.result()
            if ok:
                processed += 1
            else:
                skipped += 1
                print(f"[skip] {message}")

    return processed, skipped


def print_distribution(split_map):
    for split in SPLITS:
        counts = Counter(cls for _, cls in split_map[split])
        class_counts = [counts.get(cls, 0) for cls in CLASSES]
        print(f"{split:>5}: {class_counts} | total={sum(class_counts)}")


def main():
    args = parse_args()
    validate_ratios(args)

    if not args.images_dir.exists():
        raise FileNotFoundError(f"Nu exista folderul cu imagini: {args.images_dir}")
    if not args.labels_csv.exists():
        raise FileNotFoundError(f"Nu exista CSV-ul cu etichete: {args.labels_csv}")

    image_index, duplicates = build_image_index(args.images_dir)
    items_by_class, missing, invalid = load_labeled_images(args.labels_csv, image_index)
    split_map = split_items(items_by_class, args)

    print(f"Imagini gasite pe disc: {len(image_index)}")
    print(f"Chei duplicate ignorate in index: {len(duplicates)}")
    print(f"Randuri fara imagine pe disc: {len(missing)}")
    print(f"Randuri invalide in CSV: {len(invalid)}")
    print(f"Transformare Ben Graham: resize {args.img_size}x{args.img_size}, sigmaX=img_size/30, addWeighted(4, -4, 128)")
    print(f"Workers: {args.workers}")
    print("\nDistributie split:")
    print_distribution(split_map)

    if args.dry_run:
        print("\nDry run: nu am scris datasetul.")
        return

    processed, skipped = write_dataset(split_map, args)
    print(f"\nDataset creat: {args.output_dir}")
    print(f"Imagini procesate: {processed}")
    print(f"Imagini sarite: {skipped}")


if __name__ == "__main__":
    main()
