import argparse
import json
import random
import re
import shutil
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_INPUT_DIR = (
    PROJECT_ROOT
    / "datasets"
    / "originals"
    / "Diabetic_Balanced_Data"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "datasets"
    / "originals"
    / "Diabetic_Balanced_Data_grouped_70_20_10"
)

SPLITS = ("train", "val", "test")
CLASSES = ("0", "1", "2", "3", "4")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
AUGMENT_SUFFIX_RE = re.compile(r"(?:\.?_aug_\d+)+$")


def is_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def get_base_stem(path: Path) -> str:
    return AUGMENT_SUFFIX_RE.sub("", path.stem)


def collect_groups(input_dir: Path) -> dict[str, dict[str, list[Path]]]:
    groups: dict[str, dict[str, list[Path]]] = {
        class_name: defaultdict(list) for class_name in CLASSES
    }

    for split in SPLITS:
        for class_name in CLASSES:
            class_dir = input_dir / split / class_name
            if not class_dir.exists():
                raise FileNotFoundError(f"Folder lipsa: {class_dir}")

            for image_path in class_dir.iterdir():
                if not is_image(image_path):
                    continue

                group_key = get_base_stem(image_path)
                groups[class_name][group_key].append(image_path)

    return groups


def choose_split(counts: dict[str, int], group_size: int, targets: dict[str, float]) -> str:
    best_split = SPLITS[0]
    best_score = None

    for split in SPLITS:
        simulated = counts[split] + group_size
        score = simulated - targets[split]

        # Preferam splitul cel mai sub tinta; daca toate trec peste tinta,
        # alegem depasirea cea mai mica.
        normalized_score = score if score >= 0 else score / 10
        if best_score is None or normalized_score < best_score:
            best_score = normalized_score
            best_split = split

    return best_split


def split_groups(
    groups: dict[str, dict[str, list[Path]]],
    seed: int,
    ratios: dict[str, float],
) -> tuple[dict[str, dict[str, list[tuple[str, list[Path]]]]], dict]:
    rng = random.Random(seed)
    assignments: dict[str, dict[str, list[tuple[str, list[Path]]]]] = {
        class_name: {split: [] for split in SPLITS} for class_name in CLASSES
    }
    summary = {}

    for class_name in CLASSES:
        class_groups = list(groups[class_name].items())
        rng.shuffle(class_groups)
        class_groups.sort(key=lambda item: len(item[1]), reverse=True)

        total_images = sum(len(paths) for _, paths in class_groups)
        targets = {split: total_images * ratios[split] for split in SPLITS}
        counts = {split: 0 for split in SPLITS}

        for group_key, paths in class_groups:
            split = choose_split(counts, len(paths), targets)
            assignments[class_name][split].append((group_key, paths))
            counts[split] += len(paths)

        summary[class_name] = {
            "unique_images": len(class_groups),
            "total_files": total_images,
            "splits": {
                split: {
                    "groups": len(assignments[class_name][split]),
                    "files": counts[split],
                    "percent": round((counts[split] / total_images * 100), 2)
                    if total_images
                    else 0.0,
                    "target_percent": round(ratios[split] * 100, 2),
                }
                for split in SPLITS
            },
        }

    return assignments, summary


def prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(
                f"Folderul de output exista deja: {output_dir}\n"
                "Ruleaza cu --overwrite daca vrei sa il recreezi."
            )
        shutil.rmtree(output_dir)

    for split in SPLITS:
        for class_name in CLASSES:
            (output_dir / split / class_name).mkdir(parents=True, exist_ok=True)


def copy_assignments(
    assignments: dict[str, dict[str, list[tuple[str, list[Path]]]]],
    input_dir: Path,
    output_dir: Path,
) -> int:
    copied = 0

    for class_name in CLASSES:
        for split in SPLITS:
            destination_dir = output_dir / split / class_name

            for _, paths in assignments[class_name][split]:
                for source_path in paths:
                    destination_path = destination_dir / source_path.name
                    if destination_path.exists():
                        relative_parent = source_path.relative_to(input_dir).parent
                        safe_name = "__".join(relative_parent.parts) + "__" + source_path.name
                        destination_path = destination_dir / safe_name

                    shutil.copy2(source_path, destination_path)
                    copied += 1

    return copied


def validate_no_group_leakage(output_dir: Path) -> list[dict[str, str]]:
    locations: dict[tuple[str, str], set[str]] = defaultdict(set)

    for split in SPLITS:
        for class_name in CLASSES:
            class_dir = output_dir / split / class_name
            for image_path in class_dir.iterdir():
                if is_image(image_path):
                    locations[(class_name, get_base_stem(image_path))].add(split)

    leaks = []
    for (class_name, group_key), splits in locations.items():
        if len(splits) > 1:
            leaks.append(
                {
                    "class": class_name,
                    "group": group_key,
                    "splits": ", ".join(sorted(splits)),
                }
            )

    return leaks


def write_reports(output_dir: Path, summary: dict, leaks: list[dict[str, str]]) -> None:
    report = {
        "output_dir": str(output_dir),
        "splits": SPLITS,
        "classes": CLASSES,
        "summary": summary,
        "group_leaks": leaks,
    }
    (output_dir / "grouped_split_report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )


def print_summary(summary: dict, copied: int | None = None, dry_run: bool = False) -> None:
    title = "Rezumat dry-run" if dry_run else "Rezumat dataset nou"
    print(f"\n{title}")
    print("-" * 72)

    for class_name in CLASSES:
        class_summary = summary[class_name]
        print(
            f"Clasa {class_name}: "
            f"{class_summary['unique_images']} imagini unice, "
            f"{class_summary['total_files']} fisiere"
        )
        for split in SPLITS:
            split_summary = class_summary["splits"][split]
            print(
                f"  {split:<5} "
                f"grupuri={split_summary['groups']:<5} "
                f"fisiere={split_summary['files']:<5} "
                f"{split_summary['percent']:>6.2f}% "
                f"(tinta {split_summary['target_percent']:>5.1f}%)"
            )

    if copied is not None:
        print("-" * 72)
        print(f"Fisiere copiate: {copied}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Creeaza un split nou train/val/test in care fiecare imagine unica "
            "si augmentarile ei stau in acelasi subset."
        )
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--val-ratio", type=float, default=0.20)
    parser.add_argument("--test-ratio", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Sterge si recreeaza output-dir daca exista deja.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculeaza splitul si afiseaza raportul fara sa copieze fisiere.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    ratios = {
        "train": args.train_ratio,
        "val": args.val_ratio,
        "test": args.test_ratio,
    }

    if abs(sum(ratios.values()) - 1.0) > 1e-6:
        raise ValueError("Ratios train/val/test trebuie sa insumeze 1.0.")
    if not input_dir.exists():
        raise FileNotFoundError(f"Datasetul sursa nu exista: {input_dir}")

    groups = collect_groups(input_dir)
    assignments, summary = split_groups(groups, args.seed, ratios)

    if args.dry_run:
        print_summary(summary, dry_run=True)
        print(f"\nOutput planificat: {output_dir}")
        return

    prepare_output_dir(output_dir, args.overwrite)
    copied = copy_assignments(assignments, input_dir, output_dir)
    leaks = validate_no_group_leakage(output_dir)
    write_reports(output_dir, summary, leaks)
    print_summary(summary, copied=copied)

    if leaks:
        print(f"\nAtentie: au fost gasite {len(leaks)} grupuri impartite intre subseturi.")
        print(f"Detalii in: {output_dir / 'grouped_split_report.json'}")
    else:
        print("\nValidare OK: niciun grup original+augmentari nu este impartit intre subseturi.")
        print(f"Raport salvat in: {output_dir / 'grouped_split_report.json'}")


if __name__ == "__main__":
    main()
