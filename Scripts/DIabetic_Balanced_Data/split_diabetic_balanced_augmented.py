from pathlib import Path
import shutil


PROJECT_ROOT = Path(__file__).resolve().parents[2]

SOURCE_DIR = PROJECT_ROOT / "datasets" / "Diabetic_Balanced_Data"
ORIGINAL_OUTPUT_DIR = PROJECT_ROOT / "datasets" / "Diabetic_Balanced_Data_original"
AUGMENTED_OUTPUT_DIR = PROJECT_ROOT / "datasets" / "Diabetic_Balanced_Data_augmented"

SPLITS = ("train", "val", "test")
CLASSES = ("0", "1", "2", "3", "4")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
AUGMENTED_MARKER = "_aug_"


def reset_output_dirs() -> None:
    for output_dir in (ORIGINAL_OUTPUT_DIR, AUGMENTED_OUTPUT_DIR):
        if output_dir.exists():
            shutil.rmtree(output_dir)

        for split in SPLITS:
            for class_name in CLASSES:
                (output_dir / split / class_name).mkdir(parents=True, exist_ok=True)


def is_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def is_augmented(path: Path) -> bool:
    return AUGMENTED_MARKER in path.stem


def copy_dataset() -> dict[str, dict[str, dict[str, int]]]:
    counts = {
        "original": {split: {class_name: 0 for class_name in CLASSES} for split in SPLITS},
        "augmented": {split: {class_name: 0 for class_name in CLASSES} for split in SPLITS},
    }

    for split in SPLITS:
        for class_name in CLASSES:
            source_class_dir = SOURCE_DIR / split / class_name
            if not source_class_dir.exists():
                raise FileNotFoundError(f"Missing source folder: {source_class_dir}")

            for image_path in source_class_dir.iterdir():
                if not is_image(image_path):
                    continue

                group_name = "augmented" if is_augmented(image_path) else "original"
                output_root = AUGMENTED_OUTPUT_DIR if group_name == "augmented" else ORIGINAL_OUTPUT_DIR
                destination = output_root / split / class_name / image_path.name
                shutil.copy2(image_path, destination)
                counts[group_name][split][class_name] += 1

    return counts


def print_counts(counts: dict[str, dict[str, dict[str, int]]]) -> None:
    for group_name in ("original", "augmented"):
        output_dir = ORIGINAL_OUTPUT_DIR if group_name == "original" else AUGMENTED_OUTPUT_DIR
        print(f"\n{group_name}: {output_dir}")

        dataset_total = 0
        for split in SPLITS:
            split_total = sum(counts[group_name][split].values())
            dataset_total += split_total
            class_counts = " | ".join(
                f"{class_name}: {counts[group_name][split][class_name]}"
                for class_name in CLASSES
            )
            print(f"  {split}: {class_counts} | total: {split_total}")

        print(f"  dataset total: {dataset_total}")


def main() -> None:
    if not SOURCE_DIR.exists():
        raise FileNotFoundError(f"Missing source dataset: {SOURCE_DIR}")

    reset_output_dirs()
    counts = copy_dataset()
    print_counts(counts)


if __name__ == "__main__":
    main()
