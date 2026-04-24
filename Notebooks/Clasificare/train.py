import os
import time
import argparse
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
import matplotlib.pyplot as plt
import torch.nn.functional as F

# Importăm clasele noastre de MULTI-CLASĂ
from my_dataset import DRDataset
from my_dataset_augmented import DRDatasetAugmented
from my_dataset_bengraham import DRDatasetBenGraham
from builder import get_model, get_optimizer, get_loss_function

import seaborn as sns
from sklearn.metrics import confusion_matrix

def parse_args():
    parser = argparse.ArgumentParser(description="Antrenare Clasificare Multi-Clasă (Stadii 0-4)")
    parser.add_argument('--dataset', type=str, default='aptos')
    parser.add_argument('--model', type=str, default='resnet50')
    parser.add_argument('--loss', type=str, default='ce') # CrossEntropy
    parser.add_argument('--epochs', type=int, default=15)
    parser.add_argument('--batch_size', type=int, default=32)
    parser.add_argument('--lr', type=float, default=0.0001)
    parser.add_argument('--img_size', type=int, default=224)
    parser.add_argument('--num_workers', type=int, default=0)
    parser.add_argument('--root_dir', type=str, default=r'B:\Projects\Disertatie\Diabetic-Retinopathy-Classifier')
    parser.add_argument('--use_weights', action='store_true', help='Folosește Weighted CrossEntropy')
    return parser.parse_args()

def main():
    args = parse_args()
    
    # Creăm folderele pentru salvări (Diferite de cele de binar!)
    os.makedirs("Rezultate/salvari_modele_multi", exist_ok=True)
    os.makedirs("Rezultate/salvari_grafice_multi", exist_ok=True)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"🔥 Rulăm pe device: {device} | Model: {args.model} | Dataset: {args.dataset} (Multi-Clasă)")

    # ==========================================
    # 1. Încărcarea Datelor
    # ==========================================
    train_dataset = DRDatasetBenGraham(args.root_dir, args.dataset, split='train', image_size=args.img_size)
    test_dataset = DRDatasetBenGraham(args.root_dir, args.dataset, split='test', image_size=args.img_size)

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)
    
    print(f"Imagini train: {len(train_dataset)} | Imagini test: {len(test_dataset)}")

    # ==========================================
    # 2. Construirea Modelului, Funcției de Cost și Optimizatorului
    # ==========================================
    model = get_model(args.model, num_classes=5).to(device)
    
    if torch.cuda.device_count() > 1:
        print(f"Folosim {torch.cuda.device_count()} GPU-uri în paralel!")
        model = nn.DataParallel(model)

    # --- CONFIGURARE CLASS WEIGHTS ---
    ponderi_clase = None
    
    if args.use_weights: # Dacă ai rulat cu --use_weights în consolă
        # Aceste valori trebuie calculate în funcție de dataset-ul tău.
        # Regula: Clasa cu multe imagini primește pondere mică, clasa cu puține primește pondere mare.
        # Exemplu ipotetic pentru Retinopatie (0: foarte mulți, 4: foarte puțini):
        valori_ponderi = [0.1, 0.8, 1.2, 2.5, 5.0]
        
        # PyTorch cere obligatoriu ca ponderile să fie Tensor Float și să fie pe același device cu modelul!
        ponderi_clase = torch.tensor(valori_ponderi, dtype=torch.float32).to(device)
        print(f"⚖️ Folosim Weighted CrossEntropy cu ponderile: {valori_ponderi}")

    # Trimitem ponderile către fabrica noastră din builder.py
    criterion = get_loss_function(args.loss, class_weights=ponderi_clase)
    
    optimizer = get_optimizer(model, lr=args.lr)

    # ==========================================
    # 3. Bucla de Antrenare
    # ==========================================
    num_epochs = args.epochs
    istoric_train_loss = []
    istoric_test_loss = []
    istoric_train_acc = []
    istoric_test_acc = []
    
    best_val_loss = float('inf')
    nume_salvare_model = f"Rezultate/salvari_modele_multi/best_{args.model}_{args.dataset}.pth"

    print("\nÎncepe antrenamentul...")
    for epoch in range(num_epochs):
        start_time = time.time()
        
        # --- ETAPA DE ANTRENAMENT ---
        model.train()
        running_train_loss = 0.0
        train_correct = 0
        train_total = 0
        
        for images, labels in train_loader:
            images = images.to(device)
            # La Multi-Clasă lăsăm labels așa cum sunt (forma [batch_size])
            labels = labels.to(device)
            
            optimizer.zero_grad()
            
            outputs = model(images)

            # ==========================================
            # ADAPTAREA ETICHETELOR PENTRU LOSS-URI AVANSATE
            # ==========================================
            if args.loss == 'ce':
                # CrossEntropyLoss merge cu index simplu [32]
                loss = criterion(outputs, labels)

            elif args.loss == 'focal_loss':
                # Focal Loss vrea One-Hot Encoding [32, 5]
                # ex: Clasa 2 devine [0, 0, 1, 0, 0]
                labels_one_hot = F.one_hot(labels, num_classes=5).float()
                loss = criterion(outputs, labels_one_hot)

            elif args.loss in ['bce_ordinal', 'ordinal']:
                # BCE Ordinal vrea Ordinal Encoding [32, 5]
                # ex: Clasa 2 devine [1, 1, 1, 0, 0] (Boala a trecut prin 0, 1 și 2)
                levels = torch.arange(5).to(device)
                labels_ordinal = (labels.unsqueeze(1) >= levels).float()
                loss = criterion(outputs, labels_ordinal)

            else:
                # Fallback default
                loss = criterion(outputs, labels)
            
            loss.backward()
            optimizer.step()
            
            running_train_loss += loss.item()
            
            # Calcul Acuratețe Multi-Clasă (Alegem clasa cu probabilitatea maximă)
            predictii = torch.argmax(outputs, dim=1)
            train_correct += (predictii == labels).sum().item()
            train_total += labels.size(0)
            
        avg_train_loss = running_train_loss / len(train_loader)
        train_acc = train_correct / train_total
        istoric_train_loss.append(avg_train_loss)
        istoric_train_acc.append(train_acc)
        
        # --- ETAPA DE TESTARE ---
        model.eval()
        running_test_loss = 0.0
        test_correct = 0
        test_total = 0
        
        with torch.no_grad():
            for images, labels in test_loader:
                images = images.to(device)
                labels = labels.to(device)
                
                outputs = model(images)

                # ==========================================
                # ADAPTAREA ETICHETELOR PENTRU LOSS-URI AVANSATE
                # ==========================================
                if args.loss == 'ce':
                    # CrossEntropyLoss merge cu index simplu [32]
                    loss = criterion(outputs, labels)

                elif args.loss == 'focal_loss':
                    # Focal Loss vrea One-Hot Encoding [32, 5]
                    # ex: Clasa 2 devine [0, 0, 1, 0, 0]
                    labels_one_hot = F.one_hot(labels, num_classes=5).float()
                    loss = criterion(outputs, labels_one_hot)

                elif args.loss in ['bce_ordinal', 'ordinal']:
                    # BCE Ordinal vrea Ordinal Encoding [32, 5]
                    # ex: Clasa 2 devine [1, 1, 1, 0, 0] (Boala a trecut prin 0, 1 și 2)
                    levels = torch.arange(5).to(device)
                    labels_ordinal = (labels.unsqueeze(1) >= levels).float()
                    loss = criterion(outputs, labels_ordinal)

                else:
                    # Fallback default
                    loss = criterion(outputs, labels)
                
                running_test_loss += loss.item()
                
                predictii = torch.argmax(outputs, dim=1)
                test_correct += (predictii == labels).sum().item()
                test_total += labels.size(0)
                
        avg_test_loss = running_test_loss / len(test_loader)
        test_acc = test_correct / test_total
        istoric_test_loss.append(avg_test_loss)
        istoric_test_acc.append(test_acc)
        
        # --- CALCUL TIMP ---
        end_time = time.time()
        timp_total_secunde = end_time - start_time
        minute = int(timp_total_secunde // 60)
        secunde = int(timp_total_secunde % 60)
        
        # --- AFIȘARE (Acum include și acuratețea) ---
        print(f"Epoca [{epoch+1}/{num_epochs}] | "
              f"Train Loss: {avg_train_loss:.4f} (Acc: {train_acc*100:.1f}%) | "
              f"Test Loss: {avg_test_loss:.4f} (Acc: {test_acc*100:.1f}%) | "
              f"Timp: {minute}m {secunde}s", end="")
        
        # --- LOGICA DE SALVARE A MODELULUI ---
        if avg_test_loss < best_val_loss:
            best_val_loss = avg_test_loss
            if isinstance(model, nn.DataParallel):
                torch.save(model.module.state_dict(), nume_salvare_model)
            else:
                torch.save(model.state_dict(), nume_salvare_model)
            print(f"  --> Model salvat! (Loss nou record: {best_val_loss:.4f})")
        else:
            print()

    print("\nAntrenamentul s-a terminat!")

    # ==========================================
    # 4. Generarea Graficelor (Loss și Acuratețe)
    # ==========================================
    plt.figure(figsize=(14, 5))
    
    # Grafic 1: Loss
    plt.subplot(1, 2, 1)
    plt.plot(range(1, num_epochs + 1), istoric_train_loss, label='Train Loss', color='blue')
    plt.plot(range(1, num_epochs + 1), istoric_test_loss, label='Test Loss', color='red', linestyle='--')
    plt.title(f'Evoluția Loss-ului (Multi-Clasă) - {args.model}')
    plt.xlabel('Epoca')
    plt.ylabel('Loss (CrossEntropy)')
    plt.legend()
    plt.grid(True)

    # Grafic 2: Acuratețe
    plt.subplot(1, 2, 2)
    plt.plot(range(1, num_epochs + 1), [acc * 100 for acc in istoric_train_acc], label='Train Acc', color='green')
    plt.plot(range(1, num_epochs + 1), [acc * 100 for acc in istoric_test_acc], label='Test Acc', color='orange', linestyle='--')
    plt.title(f'Evoluția Acurateței - {args.model}')
    plt.xlabel('Epoca')
    plt.ylabel('Acuratețe (%)')
    plt.legend()
    plt.grid(True)

    plt.tight_layout()
    cale_grafic = f"Rezultate/salvari_grafice_multi/grafic_{args.model}_{args.dataset}.png"
    plt.savefig(cale_grafic, dpi=300)
    plt.close()
    
    print(f"Graficul combinat a fost salvat ca: {cale_grafic}")

    # ==========================================
    # 4. GENERARE MATRICE DE CONFUZIE
    # ==========================================
    print("\n📊 Antrenament finalizat! Generăm Matricea de Confuzie...")
    
    # Încărcăm modelul care a obținut cel mai mic Loss
    model_eval = get_model(args.model, num_classes=5).to(device)
    model_eval.load_state_dict(torch.load(nume_salvare_model))
    model_eval.eval()

    toate_predictiile = []
    toate_etichetele = []

    # Trecem din nou prin setul de test cu cel mai bun model
    with torch.no_grad():
        for imgs, labels in test_loader:
            imgs = imgs.to(device)
            outputs = model_eval(imgs)
            
            # Logică adaptată pentru tipul de Loss
            if args.loss in ['bce_ordinal', 'ordinal']:
                preds = (outputs > 0.0).sum(dim=1) - 1
                preds = torch.clamp(preds, min=0)
            else:
                preds = torch.argmax(outputs, dim=1)
                
            toate_predictiile.extend(preds.cpu().numpy())
            toate_etichetele.extend(labels.numpy())

    # Calculăm Matricea folosind scikit-learn
    cm = confusion_matrix(toate_etichetele, toate_predictiile, labels=[0, 1, 2, 3, 4])
    
    # Desenăm Matricea folosind Seaborn
    plt.figure(figsize=(8, 6))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', 
                xticklabels=['0 (Sănătos)', '1 (Ușor)', '2 (Moderat)', '3 (Sever)', '4 (Proliferativ)'],
                yticklabels=['0 (Sănătos)', '1 (Ușor)', '2 (Moderat)', '3 (Sever)', '4 (Proliferativ)'])
    
    plt.xlabel('Predicția Modelului', fontsize=12, fontweight='bold')
    plt.ylabel('Diagnosticul Real (Doctor)', fontsize=12, fontweight='bold')
    plt.title(f'Matrice de Confuzie - {args.model} pe dataset {args.dataset.upper()}', fontsize=14)
    
    # Salvăm
    cale_matrice = f"Rezultate/matricie_confuzie/CM_{args.model}_{args.dataset}_{args.loss}.png"
    plt.savefig(cale_matrice, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"✅ Matricea de confuzie a fost salvată ca: {cale_matrice}")

if __name__ == '__main__':
    import sys
    if not hasattr(sys.modules['__main__'], '__spec__'):
        sys.modules['__main__'].__spec__ = None
    torch.multiprocessing.freeze_support()
    main()