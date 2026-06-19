from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
GRAFICE = ROOT / "Notebooks" / "Rezultate" / "New" / "grafice"
FIGURI = ROOT / "Latex" / "Figuri"


EXPERIMENTS = [
    [
        ("APTOS", "Baseline", "aptos_reorganized_to_aptos_reorganized_resnet50_adamw_g1.5"),
        ("EyePACS", "Baseline", "eyepacs_split_to_eyepacs_split_resnet50_adamw_g1.5"),
        ("Balanced_Aug", "Baseline", "balanced_aug_split_to_balanced_aug_split_resnet50_adamw_g1.5"),
    ],
    [
        ("APTOS", "Augmentari", "aptos_augmented_to_aptos_augmented_resnet50_adamw_g1.5"),
        ("EyePACS", "Augmentari", "eyepacs_augmented_to_eyepacs_augmented_resnet50_adamw_g1.5"),
        ("Balanced_Aug", "Augmentari", "balanced_augmented_to_balanced_augmented_resnet50_adamw_g1.5"),
    ],
    [
        ("APTOS", "Aug. + Ben Graham", "aptos_augmented_bengraham_v2_to_aptos_augmented_bengraham_v2_resnet50_adamw_g1.5"),
        ("EyePACS", "Aug. + Ben Graham", "eyepacs_augmented_bengraham_to_eyepacs_augmented_bengraham_resnet50_adamw_g1.5"),
        ("Balanced_Aug", "Aug. + Ben Graham", "balanced_augmented_bengraham_to_balanced_augmented_bengraham_resnet50_adamw_g1.5"),
    ],
]


def history_crop(slug: str, metric: str) -> Image.Image:
    path = GRAFICE / "istoric" / f"istoric_combinat_{slug}.png"
    img = Image.open(path).convert("RGB")
    w, h = img.size
    panel_w = w // 3
    panel_h = h // 2
    boxes = {
        "loss": (0, 0, panel_w, panel_h),
        "accuracy": (panel_w, 0, 2 * panel_w, panel_h),
        "qwk": (0, panel_h, panel_w, h),
    }
    return img.crop(boxes[metric])


def combined_confusion_abs(slug: str) -> Image.Image:
    path = GRAFICE / "matrici_confuzie" / f"cm_combined_{slug}.png"
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return img.crop((0, 0, int(w * 0.49), h))


def plot_image_grid(output_name: str, loader, panel_size=(760, 520), suptitle: str | None = None) -> None:
    fig, axes = plt.subplots(3, 3, figsize=(18, 13), dpi=220)
    if suptitle:
        fig.suptitle(suptitle, fontsize=24, fontweight="bold", y=0.995)

    for r, row in enumerate(EXPERIMENTS):
        for c, (dataset, stage, slug) in enumerate(row):
            ax = axes[r][c]
            img = loader(slug).resize(panel_size, Image.Resampling.LANCZOS)
            ax.imshow(img)
            ax.set_title(f"{dataset} - {stage}", fontsize=17, fontweight="bold", pad=10)
            ax.axis("off")

    plt.tight_layout(rect=(0, 0, 1, 0.97) if suptitle else None, h_pad=1.2, w_pad=0.8)
    fig.savefig(FIGURI / output_name, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def read_prf(slug: str) -> list[dict[str, float]]:
    path = GRAFICE / "precision_recall_f1" / f"prf1_{slug}.csv"
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [
        {
            "class": int(row["class"]),
            "precision": float(row["precision"]),
            "recall": float(row["recall"]),
            "f1": float(row["f1"]),
            "support": int(row["support"]),
        }
        for row in rows
    ]


def plot_prf_grid() -> None:
    fig, axes = plt.subplots(3, 3, figsize=(18, 13), dpi=220, sharey=True)
    colors = ["#2563eb", "#f97316", "#16a34a"]
    labels = ["Precision", "Recall", "F1"]

    for r, row in enumerate(EXPERIMENTS):
        for c, (dataset, stage, slug) in enumerate(row):
            ax = axes[r][c]
            data = read_prf(slug)
            xs = [item["class"] for item in data]
            for offset, metric, color, label in zip([-0.24, 0, 0.24], ["precision", "recall", "f1"], colors, labels):
                ax.bar([x + offset for x in xs], [item[metric] for item in data], width=0.22, color=color, label=label)
            ax.set_title(f"{dataset} - {stage}", fontsize=16, fontweight="bold", pad=9)
            ax.set_xticks(xs)
            ax.set_ylim(0, 1.05)
            ax.grid(axis="y", alpha=0.25)
            ax.tick_params(axis="both", labelsize=12)
            if c == 0:
                ax.set_ylabel("Scor", fontsize=13)
            if r == 2:
                ax.set_xlabel("Clasa", fontsize=13)
            if r == 0 and c == 2:
                ax.legend(fontsize=12, loc="lower right")

    fig.suptitle("Precision, Recall si F1 pe clase - ResNet50 AdamW", fontsize=24, fontweight="bold", y=0.995)
    plt.tight_layout(rect=(0, 0, 1, 0.97), h_pad=1.4, w_pad=1.0)
    fig.savefig(FIGURI / "cap6_prf1_grid.png", bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def report_summary() -> None:
    print("Experiment,Accuracy,Macro F1,Weighted F1,Class1 F1,Class2 F1")
    for row in EXPERIMENTS:
        for dataset, stage, slug in row:
            report = GRAFICE / "rapoarte_clasificare" / f"classification_report_{slug}.txt"
            lines = report.read_text(encoding="utf-8").splitlines()
            acc = macro_f1 = weighted_f1 = class1_f1 = class2_f1 = None
            for line in lines:
                parts = line.split()
                if not parts:
                    continue
                if parts[0] == "1":
                    class1_f1 = float(parts[3])
                elif parts[0] == "2":
                    class2_f1 = float(parts[3])
                elif parts[0] == "accuracy":
                    acc = float(parts[1])
                elif parts[:2] == ["macro", "avg"]:
                    macro_f1 = float(parts[4])
                elif parts[:2] == ["weighted", "avg"]:
                    weighted_f1 = float(parts[4])
            print(f"{dataset} {stage},{acc:.2f},{macro_f1:.2f},{weighted_f1:.2f},{class1_f1:.2f},{class2_f1:.2f}")


def main() -> None:
    plot_image_grid(
        "cap6_loss_resnet50_grid.png",
        lambda slug: history_crop(slug, "loss"),
        suptitle="Istoric Loss - ResNet50 AdamW",
    )
    plot_image_grid(
        "cap6_accuracy_resnet50_grid.png",
        lambda slug: history_crop(slug, "accuracy"),
        suptitle="Istoric Acuratete - ResNet50 AdamW",
    )
    plot_image_grid(
        "cap6_qwk_resnet50_grid.png",
        lambda slug: history_crop(slug, "qwk"),
        suptitle="Istoric QWK - ResNet50 AdamW",
    )
    plot_image_grid(
        "cap6_confusion_grid_abs.png",
        combined_confusion_abs,
        panel_size=(720, 560),
        suptitle="Matrice de confuzie absoluta - ResNet50 AdamW",
    )
    plot_image_grid(
        "cap6_roc_grid.png",
        lambda slug: Image.open(GRAFICE / "roc" / f"roc_{slug}.png").convert("RGB"),
        panel_size=(760, 520),
        suptitle="Curbe ROC multiclasă - ResNet50 AdamW",
    )
    plot_prf_grid()
    report_summary()


if __name__ == "__main__":
    main()
