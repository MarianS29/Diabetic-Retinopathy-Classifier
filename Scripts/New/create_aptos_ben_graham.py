import argparse
import os
import shutil
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cv2
from tqdm import tqdm


SPLITS = ("train", "val", "test")
CLASSES = ("0", "1", "2", "3", "4")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def parse_args():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Reface datasets/aptos/aptos_ben_graham din aptos_augmented_balanced "
            "cu transformarea Ben Graham istorica, la 512x512."
        )
    )
    parser.add_argument(
        "--input_dir",
        type=Path,
        default=root / "datasets" / "aptos" / "aptos_augmented_balanced",
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=root / "datasets" / "aptos" / "aptos_ben_graham",
    )
    parser.add_argument("--img_size", type=int, default=512)
    parser.add_argument("--jpeg_quality", type=int, default=95)
    parser.add_argument("--workers", type=int, default=max((os.cpu_count() or 2) - 1, 1))
    parser.add_argument("--no_overwrite", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args()


def image_files(folder):
    return sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def ben_graham_transform(image, img_size):
    image = cv2.resize(image, (img_size, img_size))
    sigma = img_size / 30.0
    blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=sigma)
    return cv2.addWeighted(image, 4, blurred, -4, 128)


def safe_prepare_output(output_dir, overwrite):
    output_dir = output_dir.resolve()
    project_root = Path(__file__).resolve().parents[1]
    aptos_root = (project_root / "datasets" / "aptos").resolve()

    if aptos_root not in output_dir.parents:
        raise ValueError(f"Refuz sa scriu in afara folderului datasets/aptos: {output_dir}")
    if output_dir.name != "aptos_ben_graham":
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


def build_tasks(args):
    tasks = []
    counts = {split: Counter() for split in SPLITS}
    existing = 0

    for split in SPLITS:
        for cls in CLASSES:
            src_dir = args.input_dir / split / cls
            dst_dir = args.output_dir / split / cls
            if not src_dir.exists():
                print(f"[skip] Lipseste {src_dir}")
                continue

            files = image_files(src_dir)
            counts[split][cls] = len(files)
            for src_path in files:
                dst_path = dst_dir / src_path.name
                if args.resume and dst_path.exists():
                    existing += 1
                    continue
                tasks.append((src_path, dst_path, args.img_size, args.jpeg_quality))

    return tasks, counts, existing


def process_one(task):
    src_path, dst_path, img_size, jpeg_quality = task
    image = cv2.imread(str(src_path), cv2.IMREAD_UNCHANGED)
    if image is None:
        return False, f"Nu pot citi imaginea: {src_path}"

    processed_image = ben_graham_transform(image, img_size)
    if dst_path.suffix.lower() in {".jpg", ".jpeg"}:
        ok = cv2.imwrite(str(dst_path), processed_image, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
    else:
        ok = cv2.imwrite(str(dst_path), processed_image)

    if not ok:
        return False, f"Nu pot scrie imaginea: {dst_path}"
    return True, ""


def print_counts(counts):
    for split in SPLITS:
        class_counts = [counts[split].get(cls, 0) for cls in CLASSES]
        print(f"{split:>5}: {class_counts} | total={sum(class_counts)}")


def write_dataset(tasks, args):
    processed = 0
    skipped = 0

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


def main():
    args = parse_args()
    if not args.input_dir.exists():
        raise FileNotFoundError(f"Nu exista folderul sursa: {args.input_dir}")

    safe_prepare_output(args.output_dir, overwrite=not args.no_overwrite and not args.resume)
    tasks, counts, existing = build_tasks(args)

    print(f"Transformare Ben Graham: resize {args.img_size}x{args.img_size}, sigmaX=img_size/30, addWeighted(4, -4, 128)")
    print(f"Workers: {args.workers}")
    print("\nDistributie sursa:")
    print_counts(counts)

    if existing:
        print(f"Imagini deja existente: {existing}")
    if args.dry_run:
        print("\nDry run: nu am scris datasetul.")
        return

    processed, skipped = write_dataset(tasks, args)
    print(f"\nDataset creat: {args.output_dir}")
    print(f"Imagini procesate: {processed}")
    print(f"Imagini sarite: {skipped}")


if __name__ == "__main__":
    main()
