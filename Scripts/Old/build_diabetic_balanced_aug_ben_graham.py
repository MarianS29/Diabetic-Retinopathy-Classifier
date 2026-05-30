import argparse
import csv
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import cv2
from tqdm import tqdm

from ben_graham_preprocess_dataset import apply_ben_graham_preprocessing


SPLITS = ("train", "test", "val")
CLASSES = ("0", "1", "2", "3", "4")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def parse_args():
    root = Path(__file__).resolve().parents[1]
    source_root = root / "datasets" / "Diabetic_Balanced_Aug"

    parser = argparse.ArgumentParser(
        description=(
            "Construieste un dataset ImageFolder din Diabetic_Balanced_Aug, "
            "cu split stratificat 80% train, 15% test, 5% val si preprocessing Ben Graham."
        )
    )
    parser.add_argument(
        "--images_dir",
        type=Path,
        default=source_root / "resized_train_cropped",
        help="Folderul cu imaginile cropped. Poate contine si subfoldere.",
    )
    parser.add_argument(
        "--labels_csv",
        type=Path,
        default=source_root / "trainLabels_cropped.csv",
        help="CSV cu coloanele image si level.",
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=root / "datasets" / "Diabetic_Balanced_Aug_Ben_Graham_part_2",
    )
    parser.add_argument("--train_ratio", type=float, default=0.80)
    parser.add_argument("--test_ratio", type=float, default=0.15)
    parser.add_argument("--val_ratio", type=float, default=0.05)
    parser.add_argument("--output_size", type=int, default=512)
    parser.add_argument("--radius", type=int, default=300)
    parser.add_argument("--black_threshold", type=int, default=7)
    parser.add_argument("--mask_ratio", type=float, default=1.0)
    parser.add_argument("--contrast", type=float, default=1.35)
    parser.add_argument("--jpeg_quality", type=int, default=95)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no_overwrite", action="store_true")
    parser.add_argument("--dry_run", action="store_true", help="Afiseaza distributia fara sa scrie imaginile.")
    return parser.parse_args()


def validate_ratios(args):
    total = args.train_ratio + args.test_ratio + args.val_ratio
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
        keys = {path.name.lower(), path.stem.lower()}
        for key in keys:
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

            if level not in CLASSES or not image_name:
                invalid.append(row)
                continue

            key = image_name.lower()
            src_path = image_index.get(key) or image_index.get(Path(image_name).stem.lower())
            if src_path is None:
                missing.append(image_name)
                continue

            items_by_class[level].append((src_path, level))

    return items_by_class, missing, invalid


def split_items(items_by_class, args):
    rng = random.Random(args.seed)
    split_map = {split: [] for split in SPLITS}

    for cls in CLASSES:
        items = list(items_by_class.get(cls, []))
        rng.shuffle(items)

        total = len(items)
        train_count = round(total * args.train_ratio)
        test_count = round(total * args.test_ratio)

        train_items = items[:train_count]
        test_items = items[train_count : train_count + test_count]
        val_items = items[train_count + test_count :]

        split_map["train"].extend(train_items)
        split_map["test"].extend(test_items)
        split_map["val"].extend(val_items)

    return split_map


def prepare_output(output_dir, overwrite):
    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)

    for split in SPLITS:
        for cls in CLASSES:
            (output_dir / split / cls).mkdir(parents=True, exist_ok=True)


def make_output_name(src_path, used_names):
    base_name = src_path.name
    if base_name.lower() not in used_names:
        used_names.add(base_name.lower())
        return base_name

    candidate_index = 1
    while True:
        candidate = f"{src_path.stem}_{candidate_index:03d}{src_path.suffix}"
        if candidate.lower() not in used_names:
            used_names.add(candidate.lower())
            return candidate
        candidate_index += 1


def write_dataset(split_map, args):
    used_names = {split: {cls: set() for cls in CLASSES} for split in SPLITS}
    processed = 0
    skipped = 0

    for split in SPLITS:
        for src_path, label in tqdm(split_map[split], desc=f"process {split}", leave=False):
            output_name = make_output_name(src_path, used_names[split][label])
            dst_path = args.output_dir / split / label / output_name

            image = cv2.imread(str(src_path))
            if image is None:
                skipped += 1
                print(f"[skip] Nu pot citi imaginea: {src_path}")
                continue

            processed_image = apply_ben_graham_preprocessing(
                image,
                output_size=args.output_size,
                radius=args.radius,
                black_threshold=args.black_threshold,
                mask_ratio=args.mask_ratio,
                grayscale=True,
                contrast=args.contrast,
            )

            if dst_path.suffix.lower() in {".jpg", ".jpeg"}:
                cv2.imwrite(str(dst_path), processed_image, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
            else:
                cv2.imwrite(str(dst_path), processed_image)

            processed += 1

    return processed, skipped


def print_counts(split_map):
    for split in SPLITS:
        counts = Counter(label for _, label in split_map[split])
        class_counts = [counts.get(cls, 0) for cls in CLASSES]
        total = sum(class_counts)
        print(f"{split:>5}: {class_counts} | total={total}")


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
    print("\nDistributie split:")
    print_counts(split_map)

    if args.dry_run:
        print("\nDry run: nu am scris datasetul.")
        return

    prepare_output(args.output_dir, overwrite=not args.no_overwrite)
    processed, skipped = write_dataset(split_map, args)

    print(f"\nDataset creat: {args.output_dir}")
    print(f"Imagini procesate: {processed}")
    print(f"Imagini sarite: {skipped}")


if __name__ == "__main__":
    main()
