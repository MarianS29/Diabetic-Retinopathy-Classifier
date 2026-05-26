import argparse
import shutil
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm


SPLITS = ("train", "val", "test")
CLASSES = ("0", "1", "2", "3", "4")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def parse_args():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Construieste un dataset ImageFolder cu preprocessing Ben Graham, apropiat de Diabetic_Balanced_Data."
    )
    parser.add_argument("--input_dir", type=Path, default=root / "datasets" / "aptos" / "aptos_augmented_balanced")
    parser.add_argument("--output_dir", type=Path, default=root / "datasets" / "aptos" / "aptos_ben_graham_matched")
    parser.add_argument("--output_size", type=int, default=512)
    parser.add_argument("--radius", type=int, default=300)
    parser.add_argument("--black_threshold", type=int, default=7)
    parser.add_argument("--mask_ratio", type=float, default=1.00)
    parser.add_argument("--contrast", type=float, default=1.35)
    parser.add_argument("--jpeg_quality", type=int, default=95)
    parser.add_argument("--color", action="store_true", help="Pastreaza imaginea color in loc de grayscale RGB.")
    parser.add_argument("--no_overwrite", action="store_true", help="Nu sterge output_dir daca exista deja.")
    args = parser.parse_args()
    args.grayscale = not args.color
    args.overwrite = not args.no_overwrite
    return args


def crop_black_border(image, threshold=7):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = gray > threshold
    coords = cv2.findNonZero(mask.astype(np.uint8))
    if coords is None:
        return image

    x, y, w, h = cv2.boundingRect(coords)
    return image[y : y + h, x : x + w]


def scale_retina_radius(image, target_radius):
    row = image[image.shape[0] // 2, :, :].sum(axis=1)
    visible = row > row.mean() / 10.0
    radius = max(visible.sum() / 2.0, 1.0)
    scale = float(target_radius) / radius
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def center_crop_or_pad(image, size, fill_value=128):
    h, w = image.shape[:2]
    canvas = np.full((size, size, 3), fill_value, dtype=np.uint8)

    src_x0 = max((w - size) // 2, 0)
    src_y0 = max((h - size) // 2, 0)
    src_x1 = min(src_x0 + size, w)
    src_y1 = min(src_y0 + size, h)

    cropped = image[src_y0:src_y1, src_x0:src_x1]
    ch, cw = cropped.shape[:2]
    dst_x0 = max((size - cw) // 2, 0)
    dst_y0 = max((size - ch) // 2, 0)
    canvas[dst_y0 : dst_y0 + ch, dst_x0 : dst_x0 + cw] = cropped
    return canvas


def apply_circular_mask(image, radius, mask_ratio=0.90, fill_value=128):
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(mask, center, int(radius * mask_ratio), 255, thickness=-1)

    background = np.full_like(image, fill_value)
    return np.where(mask[:, :, None] == 255, image, background)


def to_reference_like_grayscale(image, contrast=1.35):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray = (gray - 128.0) * contrast + 128.0
    gray = np.clip(gray, 0, 255).astype(np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def apply_ben_graham_preprocessing(
    image,
    output_size=512,
    radius=300,
    black_threshold=7,
    mask_ratio=0.90,
    grayscale=True,
    contrast=1.35,
):
    image = crop_black_border(image, threshold=black_threshold)
    image = scale_retina_radius(image, target_radius=radius)

    working_size = radius * 2
    image = center_crop_or_pad(image, size=working_size, fill_value=128)

    sigma = radius / 30.0
    blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=sigma)
    image = cv2.addWeighted(image, 2, blurred, -2, 128)
    image = apply_circular_mask(image, radius=radius, mask_ratio=mask_ratio, fill_value=128)

    image = cv2.resize(image, (output_size, output_size), interpolation=cv2.INTER_AREA)
    if grayscale:
        image = to_reference_like_grayscale(image, contrast=contrast)

    return image


def image_files(folder):
    return sorted(path for path in folder.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS)


def prepare_output(output_dir, overwrite):
    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)

    for split in SPLITS:
        for cls in CLASSES:
            (output_dir / split / cls).mkdir(parents=True, exist_ok=True)


def process_dataset(args):
    if not args.input_dir.exists():
        raise FileNotFoundError(f"Nu exista folderul sursa: {args.input_dir}")

    prepare_output(args.output_dir, overwrite=args.overwrite)

    total_processed = 0
    for split in SPLITS:
        for cls in CLASSES:
            src_dir = args.input_dir / split / cls
            dst_dir = args.output_dir / split / cls

            if not src_dir.exists():
                print(f"[skip] Lipseste {src_dir}")
                continue

            files = image_files(src_dir)
            for src_path in tqdm(files, desc=f"{split}/{cls}", leave=False):
                image = cv2.imread(str(src_path))
                if image is None:
                    print(f"[skip] Nu pot citi imaginea: {src_path}")
                    continue

                processed = apply_ben_graham_preprocessing(
                    image,
                    output_size=args.output_size,
                    radius=args.radius,
                    black_threshold=args.black_threshold,
                    mask_ratio=args.mask_ratio,
                    grayscale=args.grayscale,
                    contrast=args.contrast,
                )

                dst_path = dst_dir / src_path.name
                if dst_path.suffix.lower() in {".jpg", ".jpeg"}:
                    cv2.imwrite(str(dst_path), processed, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
                else:
                    cv2.imwrite(str(dst_path), processed)
                total_processed += 1

    return total_processed


def print_counts(output_dir):
    print(f"\nDataset creat: {output_dir}")
    for split in SPLITS:
        counts = []
        for cls in CLASSES:
            counts.append(len(image_files(output_dir / split / cls)))
        print(f"{split:>5}: {counts} | total={sum(counts)}")


if __name__ == "__main__":
    arguments = parse_args()
    processed_count = process_dataset(arguments)
    print(f"\nProcesate {processed_count} imagini.")
    print_counts(arguments.output_dir)
