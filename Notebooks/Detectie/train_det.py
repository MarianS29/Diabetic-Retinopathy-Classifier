import os
import time
import argparse
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
import matplotlib.pyplot as plt

# Importăm clasele noastre din fișierele modulare
from my_dataset_det import BinaryDRDataset
from builder_det import get_model, get_optimizer, get_loss_function

def parse_args():
    parser = argparse.ArgumentParser(description="Antrenare Detecție Boală (Binar)")
    parser.add_argument('--dataset', type=str, default='aptos')
    parser.add_argument('--model', type=str, default='resnet50')
    parser.add_argument('--loss', type=str, default='bce')
    parser.add_argument('--epochs', type=int, default=15)
    parser.add_argument('--batch_size', type=int, default=32)
    parser.add_argument('--lr', type=float, default=0.0001)
    parser.add_argument('--img_size', type=int, default=224)
    parser.add_argument('--pos_weight', type=float, default=None)
    parser.add_argument('--num_workers', type=int, default=0)
    parser.add_argument('--root_dir', type=str, default=r'B:\Projects\Disertatie\Diabetic-Retinopathy-Classifier')
    return parser.parse_args()

def main():
    args = parse_args()
    
    # Creăm folderele pentru salvări dacă nu există
    os.makedirs("../../Rezultate/Detectie/salvari_modele_binar", exist_ok=True)
    os.makedirs("../../Rezultate/Detectie/salvari_grafice_binar", exist_ok=True)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"🔥 Rulăm pe device: {device} | Model: {args.model} | Dataset: {args.dataset}")

    # ==========================================
    # 1. Încărcarea Datelor
    # ==========================================
    train_dataset = BinaryDRDataset(args.root_dir, args.dataset, split='train', image_size=args.img_size)
    test_dataset = BinaryDRDataset(args.root_dir, args.dataset, split='test', image_size=args.img_size)

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)
    
    print(f"Imagini train: {len(train_dataset)} | Imagini test: {len(test_dataset)}")

    # ==========================================
    # 2. Construirea Modelului, Funcției de Cost și Optimizatorului
    # ==========================================
    model = get_model(args.model, num_classes=1).to(device)
    
    # Suport pentru Multi-GPU (Kaggle sau PC cu mai multe plăci)
    if torch.cuda.device_count() > 1:
        print(f"Folosim {torch.cuda.device_count()} GPU-uri în paralel cu DataParallel!")
        model = nn.DataParallel(model)

    criterion = get_loss_function(args.loss, pos_weight=args.pos_weight)
    # Mutăm pos_weight pe GPU dacă există
    if hasattr(criterion, 'pos_weight') and criterion.pos_weight is not None:
        criterion.pos_weight = criterion.pos_weight.to(device)

    optimizer = get_optimizer(model, lr=args.lr)

    # ==========================================
    # 3. Bucla de Antrenare (A ta, perfect integrată)
    # ==========================================
    num_epochs = args.epochs
    istoric_train_loss = []
    istoric_test_loss = []
    best_val_loss = float('inf')
    
    # Calea de salvare personalizată automat în funcție de argumente
    nume_salvare_model = f"../../Rezultate/Detectie/salvari_modele_binar/best_{args.model}_{args.dataset}.pth"

    print("\nÎncepe antrenamentul...")
    for epoch in range(num_epochs):
        
        start_time = time.time()
        
        # --- ETAPA DE ANTRENAMENT ---
        model.train()
        running_train_loss = 0.0
        
        for images, labels in train_loader:
            images = images.to(device)
            # Folosim view(-1, 1) pentru a fi 100% siguri că forma e [batch_size, 1] pt BCEWithLogits
            labels = labels.to(device).view(-1, 1)
            
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            
            loss.backward()
            optimizer.step()
            
            running_train_loss += loss.item()
            
        avg_train_loss = running_train_loss / len(train_loader)
        istoric_train_loss.append(avg_train_loss)
        
        # --- ETAPA DE TESTARE / VALIDARE ---
        model.eval()
        running_test_loss = 0.0
        
        with torch.no_grad():
            for images, labels in test_loader:
                images = images.to(device)
                labels = labels.to(device).view(-1, 1)
                
                outputs = model(images)
                loss = criterion(outputs, labels)
                
                running_test_loss += loss.item()
                
        avg_test_loss = running_test_loss / len(test_loader)
        istoric_test_loss.append(avg_test_loss)
        
        # --- CALCUL TIMP ---
        end_time = time.time()
        timp_total_secunde = end_time - start_time
        minute = int(timp_total_secunde // 60)
        secunde = int(timp_total_secunde % 60)
        
        # --- AFIȘARE (fără trecere pe linie nouă) ---
        print(f"Epoca [{epoch+1}/{num_epochs}] | Train Loss: {avg_train_loss:.4f} | Test Loss: {avg_test_loss:.4f} | Timp: {minute}m {secunde}s", end="")
        
        # --- LOGICA DE SALVARE A MODELULUI ---
        if avg_test_loss < best_val_loss:
            best_val_loss = avg_test_loss
            
            # Gestionăm corect salvarea în caz de DataParallel
            if isinstance(model, nn.DataParallel):
                torch.save(model.module.state_dict(), nume_salvare_model)
            else:
                torch.save(model.state_dict(), nume_salvare_model)
            
            print(f"  --> Model salvat! (Loss nou record: {best_val_loss:.4f})")
        else:
            print()

    print("\nAntrenamentul s-a terminat!")

    # ==========================================
    # 4. Generarea Graficului
    # ==========================================
    plt.figure(figsize=(10, 6))
    plt.plot(range(1, num_epochs + 1), istoric_train_loss, label='Train Loss', color='blue', linewidth=2)
    plt.plot(range(1, num_epochs + 1), istoric_test_loss, label='Test Loss', color='red', linestyle='--', linewidth=2)
    
    plt.title(f'Evoluția Loss-ului - {args.model.upper()} ({args.dataset.upper()})', fontsize=14)
    plt.xlabel('Epoca', fontsize=12)
    plt.ylabel('Loss (BCEWithLogits)', fontsize=12)
    plt.legend(fontsize=12)
    plt.grid(True, linestyle=':', alpha=0.7)
    
    cale_grafic = f"../../Rezultate/Detectie/salvari_grafice_binar/grafic_{args.model}_{args.dataset}.png"
    plt.savefig(cale_grafic, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"Graficul a fost salvat ca: {cale_grafic}")

if __name__ == '__main__':
    # Patch pentru Jupyter pe Windows
    import sys
    if not hasattr(sys.modules['__main__'], '__spec__'):
        sys.modules['__main__'].__spec__ = None
    torch.multiprocessing.freeze_support()
    
    main()