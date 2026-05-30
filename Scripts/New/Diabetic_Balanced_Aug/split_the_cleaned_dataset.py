import os
import random
import shutil
from pathlib import Path
from tqdm import tqdm

# ==========================================
# CONFIGURARE CAI SI PARAMETRI
# ==========================================
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Folderul de unde luam imaginile TOATE la un loc (ex: dataset-ul curatat)
INPUT_DIR = PROJECT_ROOT / "datasets" / "cleaned_dataset"

# Noul folder unde va fi impartit dataset-ul
OUTPUT_DIR = PROJECT_ROOT / "datasets" / "final_split_dataset"

TRAIN_RATIO = 0.70
VAL_RATIO = 0.20
TEST_RATIO = 0.10
SEED = 42 # Pentru reproductibilitate

CLASSES = ["0", "1", "2", "3", "4"]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

def main():
    # Validam matematica procentelor
    if abs((TRAIN_RATIO + VAL_RATIO + TEST_RATIO) - 1.0) > 1e-6:
        raise ValueError("Procentele (train/val/test) trebuie sa insumeze 1.0 (100%)!")

    if not INPUT_DIR.exists():
        print(f"Eroare: Folderul sursa {INPUT_DIR} nu exista!")
        return

    # Pregatim folderul nou (stergem varianta veche daca exista ca sa nu amestecam fisiere)
    if OUTPUT_DIR.exists():
        print(f"Curatam folderul vechi de output: {OUTPUT_DIR} ...")
        shutil.rmtree(OUTPUT_DIR)
    
    # Cream arhitectura folderelelor goale
    for split in ["train", "val", "test"]:
        for cls in CLASSES:
            (OUTPUT_DIR / split / cls).mkdir(parents=True, exist_ok=True)

    # Initializam generatorul de numere aleatoare cu seed fix
    rng = random.Random(SEED)
    total_copied = 0
    
    print("\nIncepem Impartirea Datasetului (70% Train | 20% Val | 10% Test)\n" + "-"*60)

    for cls in CLASSES:
        class_dir = INPUT_DIR / cls
        if not class_dir.exists():
            print(f"Avertisment: Clasa {cls} nu a fost gasita in {INPUT_DIR}.")
            continue
            
        # Culegem toate fisierele imagine
        images = [p for p in class_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
        
        if not images:
            continue
            
        # Amestecam imaginile (ca sa nu avem toate pozele dintr-o clinica pe un singur split)
        rng.shuffle(images)
        
        # Calculam taierile
        total_images = len(images)
        train_count = round(total_images * TRAIN_RATIO)
        val_count = round(total_images * VAL_RATIO)
        
        # Impartim lista mare in 3 liste mici
        train_images = images[:train_count]
        val_images = images[train_count:train_count + val_count]
        test_images = images[train_count + val_count:]
        
        splits_dict = {
            "train": train_images,
            "val": val_images,
            "test": test_images
        }
        
        print(f"Clasa {cls:2}: Total={total_images:<5} -> Train: {len(train_images):<5} | Val: {len(val_images):<4} | Test: {len(test_images)}")
        
        # Copiem efectiv fisierele in noile lor foldere
        for split_name, file_list in splits_dict.items():
            # tqdm ne arata bara de progres pentru copiere
            for file_path in tqdm(file_list, desc=f"  Copiere {split_name}/{cls}", leave=False, unit="img"):
                dest_path = OUTPUT_DIR / split_name / cls / file_path.name
                shutil.copy2(file_path, dest_path)
                total_copied += 1
                
    print("-" * 60)
    print(f"Gata! Am transferat {total_copied} imagini in formatul corect de retea neurala in folderul:")
    print(f"📂 {OUTPUT_DIR}")

if __name__ == "__main__":
    main()