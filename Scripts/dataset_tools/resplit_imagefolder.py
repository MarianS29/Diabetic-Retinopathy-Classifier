from __future__ import annotations

import argparse
import math
import shutil
from pathlib import Path


SPLITS = ("train", "val", "test")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def list_images(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(
        (item for item in path.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda item: item.name.lower(),
    )


def desired_counts(total: int, train_ratio: float, val_ratio: float) -> dict[str, int]:
    train = math.floor(total * train_ratio)
    val = math.floor(total * val_ratio)
    test = total - train - val
    return {"train": train, "val": val, "test": test}


def class_names(root: Path) -> list[str]:
    names: set[str] = set()
    for split in SPLITS:
        split_path = root / split
        if split_path.exists():
            names.update(item.name for item in split_path.iterdir() if item.is_dir())
    return sorted(names, key=lambda name: int(name) if name.isdigit() else name)


def move_files(files: list[Path], target_dir: Path, dry_run: bool) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for source in files:
        destination = target_dir / source.name
        if destination.exists():
            raise FileExistsError(f"Destination already exists: {destination}")
        if not dry_run:
            shutil.move(str(source), str(destination))


def resplit_class(root: Path, cls: str, train_ratio: float, val_ratio: float, dry_run: bool) -> dict[str, int]:
    current_files = {split: list_images(root / split / cls) for split in SPLITS}
    current = {split: len(files) for split, files in current_files.items()}
    total = sum(current.values())
    desired = desired_counts(total, train_ratio, val_ratio)

    if current["train"] < desired["train"] or current["test"] < desired["test"]:
        raise ValueError(
            f"Class {cls}: cannot reach desired split by moving only train/test surplus to val. "
            f"Current={current}, desired={desired}"
        )

    train_to_val = current["train"] - desired["train"]
    test_to_val = current["test"] - desired["test"]

    move_files(current_files["train"][-train_to_val:] if train_to_val else [], root / "val" / cls, dry_run)
    move_files(current_files["test"][-test_to_val:] if test_to_val else [], root / "val" / cls, dry_run)

    return {
        "class": cls,
        "total": total,
        "old_train": current["train"],
        "old_val": current["val"],
        "old_test": current["test"],
        "new_train": desired["train"],
        "new_val": desired["val"],
        "new_test": desired["test"],
        "train_to_val": train_to_val,
        "test_to_val": test_to_val,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Resplit an ImageFolder dataset to train/val/test ratios.")
    parser.add_argument("root", type=Path)
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--apply", action="store_true", help="Move files. Without this, only prints the plan.")
    args = parser.parse_args()

    if args.train_ratio + args.val_ratio >= 1.0:
        raise ValueError("train-ratio + val-ratio must be less than 1.0")

    root = args.root.resolve()
    if not root.exists():
        raise FileNotFoundError(root)

    rows = [
        resplit_class(root, cls, args.train_ratio, args.val_ratio, dry_run=not args.apply)
        for cls in class_names(root)
    ]

    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"{mode}: {root}")
    print("class,total,old_train,old_val,old_test,new_train,new_val,new_test,train_to_val,test_to_val")
    for row in rows:
        print(
            f"{row['class']},{row['total']},{row['old_train']},{row['old_val']},{row['old_test']},"
            f"{row['new_train']},{row['new_val']},{row['new_test']},"
            f"{row['train_to_val']},{row['test_to_val']}"
        )


if __name__ == "__main__":
    main()
