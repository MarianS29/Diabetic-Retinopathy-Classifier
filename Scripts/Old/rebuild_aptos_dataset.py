import argparse
import random
import shutil
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm

from ben_graham_preprocess_dataset import apply_ben_graham_preprocessing


SPLITS = ("train", "val", "test")
CLASSES = ("0", "1", "2", "3", "4")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
DEFAULT_TARGETS = {
    "train": 1500,
    "val": 200,
    "test": 250,
}


def parse_args():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Reface datasetul APTOS balansat si preprocesat cu augmentari blande."
    )
    parser.add_argument("--input_dir", type=Path, default=root / "datasets" / "aptos" / "aptos_reorganized")
    parser.add_argument(
        "--balanced_dir",
        type=Path,
        default=root / "datasets" / "aptos" / "aptos_augmented_balanced",
    )
    parser.add_argument(
        "--processed_dir",
        type=Path,
        default=root / "datasets" / "aptos" / "aptos_ben_graham_part_4",
    )
    parser.add_argument("--train_target", type=int, default=DEFAULT_TARGETS["train"])
    parser.add_argument("--val_target", type=int, default=DEFAULT_TARGETS["val"])
    parser.add_argument("--test_target", type=int, default=DEFAULT_TARGETS["test"])
    parser.add_argument("--output_size", type=int, default=512)
    parser.add_argument("--radius", type=int, default=300)
    parser.add_argument("--contrast", type=float, default=1.35)
    parser.add_argument("--mask_ratio", type=float, default=1.0)
    parser.add_argument("--jpeg_quality", type=int, default=95)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no_overwrite", action="store_true")
    return parser.parse_args()


def image_files(folder):
    return sorted(
        path for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def is_augmented(path):
    return "_aug" in path.stem.lower()


def prepare_dir(path, overwrite):
    resolved = path.resolve()
    if path.exists() and overwrite:
        shutil.rmtree(resolved)
    for split in SPLITS:
        for cls in CLASSES:
            (path / split / cls).mkdir(parents=True, exist_ok=True)


def copy_originals(input_dir, balanced_dir):
    copied = 0
    clean_sources = {}

    for split in SPLITS:
        for cls in CLASSES:
            src_dir = input_dir / split / cls
            dst_dir = balanced_dir / split / cls
            sources = []

            if src_dir.exists():
                for src in image_files(src_dir):
                    if is_augmented(src):
                        continue
                    dst = dst_dir / src.name
                    shutil.copy2(src, dst)
                    sources.append(dst)
                    copied += 1

            clean_sources[(split, cls)] = sources

    return copied, clean_sources


def soft_augment(image, rng):
    if rng.random() < 0.5:
        image = cv2.flip(image, 1)
    if rng.random() < 0.15:
        image = cv2.flip(image, 0)

    angle = rng.uniform(-8.0, 8.0)
    scale = rng.uniform(0.97, 1.03)
    h, w = image.shape[:2]
    translate_x = rng.uniform(-0.025, 0.025) * w
    translate_y = rng.uniform(-0.025, 0.025) * h

    matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, scale)
    matrix[0, 2] += translate_x
    matrix[1, 2] += translate_y

    return cv2.warpAffine(
        image,
        matrix,
        (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(128, 128, 128),
    )


def balance_split(clean_sources, targets, rng):
    generated = 0

    for split in SPLITS:
        target = targets[split]
        for cls in CLASSES:
            originals = clean_sources[(split, cls)]
            if not originals:
                print(f"[skip] Nu exista imagini curate pentru {split}/{cls}")
                continue

            dst_dir = originals[0].parent
            existing = image_files(dst_dir)
            needed = max(target - len(existing), 0)

            for idx in tqdm(range(needed), desc=f"augment {split}/{cls}", leave=False):
                src = rng.choice(originals)
                image = cv2.imread(str(src))
                if image is None:
                    print(f"[skip] Nu pot citi imaginea: {src}")
                    continue

                dst = dst_dir / f"{src.stem}_aug_{split}_{idx:04d}{src.suffix.lower()}"
                augmented = soft_augment(image, rng)
                if dst.suffix.lower() in {".jpg", ".jpeg"}:
                    cv2.imwrite(str(dst), augmented, [cv2.IMWRITE_JPEG_QUALITY, 95])
                else:
                    cv2.imwrite(str(dst), augmented)
                generated += 1

    return generated


def preprocess_balanced_dataset(balanced_dir, processed_dir, args):
    processed = 0

    for split in SPLITS:
        for cls in CLASSES:
            src_dir = balanced_dir / split / cls
            dst_dir = processed_dir / split / cls

            for src in tqdm(image_files(src_dir), desc=f"preprocess {split}/{cls}", leave=False):
                dst = dst_dir / src.name
                if dst.exists():
                    continue

                image = cv2.imread(str(src))
                if image is None:
                    print(f"[skip] Nu pot citi imaginea: {src}")
                    continue

                output = apply_ben_graham_preprocessing(
                    image,
                    output_size=args.output_size,
                    radius=args.radius,
                    mask_ratio=args.mask_ratio,
                    grayscale=True,
                    contrast=args.contrast,
                )

                if dst.suffix.lower() in {".jpg", ".jpeg"}:
                    cv2.imwrite(str(dst), output, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
                else:
                    cv2.imwrite(str(dst), output)
                processed += 1

    return processed


def print_counts(folder):
    print(f"\n{folder}")
    for split in SPLITS:
        counts = [len(image_files(folder / split / cls)) for cls in CLASSES]
        print(f"{split:>5}: {counts} | total={sum(counts)}")


def main():
    args = parse_args()
    if not args.input_dir.exists():
        raise FileNotFoundError(f"Nu exista folderul sursa: {args.input_dir}")

    overwrite = not args.no_overwrite
    rng = random.Random(args.seed)
    targets = {
        "train": args.train_target,
        "val": args.val_target,
        "test": args.test_target,
    }

    prepare_dir(args.balanced_dir, overwrite=overwrite)
    prepare_dir(args.processed_dir, overwrite=overwrite)

    copied, clean_sources = copy_originals(args.input_dir, args.balanced_dir)
    generated = balance_split(clean_sources, targets, rng)
    processed = preprocess_balanced_dataset(args.balanced_dir, args.processed_dir, args)

    print(f"\nCopiate imagini curate: {copied}")
    print(f"Generate augmentari blande: {generated}")
    print(f"Preprocesate Ben Graham soft: {processed}")
    print_counts(args.balanced_dir)
    print_counts(args.processed_dir)


if __name__ == "__main__":
    main()
