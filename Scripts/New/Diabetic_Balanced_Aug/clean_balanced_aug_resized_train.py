import os
import shutil
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm

# ==========================================
# CONFIGURARE CAI SI PARAMETRI
# ==========================================
PROJECT_ROOT = Path(__file__).resolve().parents[3]
INPUT_DIR = PROJECT_ROOT / "datasets" / "Diabetic_Balanced_Aug_resized_train" / "train"
OUTPUT_DIR = PROJECT_ROOT / "datasets" / "cleaned_dataset"

CLASSES = ("0", "1", "2", "3", "4")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif"}
WORKERS = max((os.cpu_count() or 2) - 1, 1)

# ==========================================
# PRAGURI DINAMICE (Extrem de Agresiv pt 0)
# ==========================================
THRESHOLDS = {
    "0": {
        "blur_min": 55.0,        # Acceptă imagini o idee mai puțin clare
        "bright_min": 15.0,      # Acceptă imagini puțin mai întunecate
        "bright_max": 180.0,     # Acceptă imagini global mai luminoase
        "area_min": 0.25,        # Acceptă ochi fotografiați de un pic mai departe
        "area_max": 0.95,        # Acceptă ochi tăiați puțin mai mult de marginile pozei
        "circularity_min": 0.84, # Permite ochi ovali sau tăiați pe o latură (nu trebuie să mai fie cercuri perfecte)
        "glare_max_ratio": 0.005 # Permite ca blițul camerei să ocupe până la 0.5% din ochi
    },
    "minoritare": {
        "blur_min": 15.0,       
        "bright_min": 8.0,      
        "bright_max": 220.0,    
        "area_min": 0.15,       
        "area_max": 0.98,       
        "circularity_min": 0.60,  # Acceptam ochi taiati masiv sau deformati
        "glare_max_ratio": 0.05   # Acceptam reflexii mari, vrem sa pastram tesutul bolnav
    }
}


def evaluate_image(image_path, cls):
    """
    Evalueaza imaginea aplicand pragurile specifice clasei.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        return False, "Eroare_Citire"

    rules = THRESHOLDS["0"] if cls == "0" else THRESHOLDS["minoritare"]

    img_resized = cv2.resize(img, (512, 512))
    gray = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)
    total_pixels = 512 * 512

    # --- 1. VERIFICARE LUMINOSITATE GLOBALA ---
    non_black_pixels = gray[gray > 10]
    if len(non_black_pixels) == 0:
        return False, "Imagine_Neagra"
        
    mean_brightness = np.mean(non_black_pixels)
    if mean_brightness < rules["bright_min"]:
        return False, f"Prea_Intunecata"
    if mean_brightness > rules["bright_max"]:
        return False, f"Supraexpusa_Total"

    # --- 2. VERIFICARE BLUR ---
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if laplacian_var < rules["blur_min"]:
        return False, f"Blurata"

    # --- 3. EXTRAGERE CONTUR OCHI ---
    _, thresh = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
    kernel_clean = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    thresh_clean = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_clean)
    contours, _ = cv2.findContours(thresh_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return False, "Fara_Contur"

    contur_ochi = max(contours, key=cv2.contourArea)
    ochi_area = cv2.contourArea(contur_ochi)
    
    # --- 4. VERIFICARE ZOOM (ARIA) ---
    area_ratio = ochi_area / total_pixels
    if area_ratio < rules["area_min"]:
        return False, f"Zoom_Prea_Mic"
    if area_ratio > rules["area_max"]:
        return False, f"Zoom_Exagerat_Taiat"

    # --- 5. NOU: VERIFICARE FORMA (CIRCULARITATE) ---
    perimeter = cv2.arcLength(contur_ochi, True)
    if perimeter == 0:
        return False, "Eroare_Geometrie"
        
    circularity = (4 * np.pi * ochi_area) / (perimeter * perimeter)
    if circularity < rules["circularity_min"]:
        return False, f"Forma_Taiata_Neregulata"

    # --- 6. NOU: VERIFICARE REFLEXIE / GLARE (LENTILA) ---
    # Consideram pixeli de reflexie pe cei mai albi de 245
    glare_mask = gray > 245
    # Cati pixeli orbi avem raportat la suprafata ochiului?
    glare_ratio = np.sum(glare_mask) / (ochi_area + 1e-6) # +1e-6 pentru a evita impartirea la zero
    
    if glare_ratio > rules["glare_max_ratio"]:
        return False, f"Reflexie_Blit_Lentila"

    return True, "OK"


def process_and_copy(task):
    src_path, dst_path, cls = task
    
    is_valid, reason = evaluate_image(src_path, cls)
    
    if is_valid:
        shutil.copy2(src_path, dst_path)
        return True, "OK", cls
    else:
        return False, reason, cls


def main():
    if not INPUT_DIR.exists():
        raise FileNotFoundError(f"Folderul de intrare nu exista: {INPUT_DIR}")

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    
    tasks = []
    for cls in CLASSES:
        class_dir = INPUT_DIR / cls
        if not class_dir.exists():
            continue
            
        (OUTPUT_DIR / cls).mkdir(parents=True, exist_ok=True)
        
        for file in class_dir.iterdir():
            if file.is_file() and file.suffix.lower() in IMAGE_EXTENSIONS:
                dst_path = OUTPUT_DIR / cls / file.name
                tasks.append((file, dst_path, cls))

    if not tasks:
        print("Nu s-au gasit imagini in folderul sursa.")
        return

    print(f"Incepem filtrarea a {len(tasks)} imagini...")
    print("Reguli aplicate pt Clasa 0: Circularitate > 0.85, Glare < 0.5%")
    
    stats_clasa_0 = Counter()
    stats_minoritare = Counter()
    
    with ProcessPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(process_and_copy, task) for task in tasks]
        
        for future in tqdm(as_completed(futures), total=len(futures), desc="Procesare Extrema"):
            is_valid, reason, cls = future.result()
            
            if cls == "0":
                stats_clasa_0[reason] += 1
            else:
                stats_minoritare[reason] += 1

    # ==========================================
    # AFISARE RAPORT DETALIAT
    # ==========================================
    print("\n" + "="*55)
    print("RAPORT CURATARE - CLASA 0 (MĂCEL)")
    print("="*55)
    total_0 = sum(stats_clasa_0.values())
    ok_0 = stats_clasa_0.get("OK", 0)
    print(f"Total imagini: {total_0} | Pastrate: {ok_0} | ELIMINATE: {total_0 - ok_0}")
    for reason, count in stats_clasa_0.items():
        if reason != "OK": print(f" - {reason}: {count} imagini")

    print("\n" + "="*55)
    print("RAPORT CURATARE - CLASELE 1-4 (INDULGENT)")
    print("="*55)
    total_min = sum(stats_minoritare.values())
    ok_min = stats_minoritare.get("OK", 0)
    print(f"Total imagini: {total_min} | Pastrate: {ok_min} | ELIMINATE: {total_min - ok_min}")
    for reason, count in stats_minoritare.items():
        if reason != "OK": print(f" - {reason}: {count} imagini")

    print(f"\nNoul dataset a fost salvat curat in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()