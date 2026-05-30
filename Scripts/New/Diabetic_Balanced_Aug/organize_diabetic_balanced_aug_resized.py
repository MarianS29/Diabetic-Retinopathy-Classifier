from csv import DictReader
from pathlib import Path
import shutil


PROJECT_ROOT = Path(__file__).resolve().parents[2]

SOURCE_ROOT = PROJECT_ROOT / "datasets" / "Diabetic_Balanced_Aug"

DATASETS = (
    {
        "name": "resized_train",
        "image_dir": SOURCE_ROOT / "resized_train" / "resized_train",
        "labels_csv": SOURCE_ROOT / "trainLabels.csv",
        "output_dir": PROJECT_ROOT / "datasets" / "Diabetic_Balanced_Aug_resized_train",
    },
    {
        "name": "resized_train_cropped",
        "image_dir": SOURCE_ROOT / "resized_train_cropped" / "resized_train_cropped",
        "labels_csv": SOURCE_ROOT / "trainLabels_cropped.csv",
        "output_dir": PROJECT_ROOT / "datasets" / "Diabetic_Balanced_Aug_resized_train_cropped",
    },
)

SPLITS = ("train", "val", "test")
CLASSES = ("0", "1", "2", "3", "4")
IMAGE_EXTENSIONS = (".jpeg", ".jpg", ".png", ".bmp", ".tif", ".tiff")


def reset_dataset(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)

    for split in SPLITS:
        for class_name in CLASSES:
            (output_dir / split / class_name).mkdir(parents=True, exist_ok=True)


def load_labels(labels_csv: Path) -> dict[str, str]:
    if not labels_csv.exists():
        raise FileNotFoundError(f"Missing labels CSV: {labels_csv}")

    labels = {}
    with labels_csv.open("r", newline="", encoding="utf-8-sig") as csv_file:
        reader = DictReader(csv_file)
        if "image" not in reader.fieldnames or "level" not in reader.fieldnames:
            raise ValueError(f"CSV must contain 'image' and 'level' columns: {labels_csv}")

        for row in reader:
            image_id = row["image"].strip()
            level = row["level"].strip()
            if image_id and level in CLASSES:
                labels[image_id] = level

    return labels


def get_image_id(image_path: Path) -> str:
    return image_path.stem


def is_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def organize_dataset(config: dict[str, Path | str]) -> dict[str, int | dict[str, int]]:
    image_dir = Path(config["image_dir"])
    labels_csv = Path(config["labels_csv"])
    output_dir = Path(config["output_dir"])

    if not image_dir.exists():
        raise FileNotFoundError(f"Missing image folder: {image_dir}")

    reset_dataset(output_dir)
    labels = load_labels(labels_csv)

    counts = {class_name: 0 for class_name in CLASSES}
    copied_image_ids = set()
    skipped_without_label = 0

    for image_path in sorted(image_dir.iterdir()):
        if not is_image(image_path):
            continue

        image_id = get_image_id(image_path)
        level = labels.get(image_id)
        if level is None:
            skipped_without_label += 1
            continue

        destination = output_dir / "train" / level / image_path.name
        shutil.copy2(image_path, destination)
        counts[level] += 1
        copied_image_ids.add(image_id)

    missing_images = len(set(labels) - copied_image_ids)

    return {
        "counts": counts,
        "total": sum(counts.values()),
        "skipped_without_label": skipped_without_label,
        "missing_images": missing_images,
    }


def main() -> None:
    for config in DATASETS:
        result = organize_dataset(config)
        counts = result["counts"]
        class_counts = " | ".join(f"{class_name}: {counts[class_name]}" for class_name in CLASSES)

        print(f"\n{config['name']}")
        print(f"  output: {config['output_dir']}")
        print(f"  train: {class_counts} | total: {result['total']}")
        print("  val/test: empty class folders created")
        print(f"  skipped images without label: {result['skipped_without_label']}")
        print(f"  labels without image: {result['missing_images']}")


if __name__ == "__main__":
    main()
