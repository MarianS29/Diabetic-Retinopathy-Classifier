import os
import time
import argparse
import torch
from torch.utils.data import DataLoader
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import confusion_matrix, roc_auc_score
import torch.nn.functional as F
from tqdm import tqdm
import sys

# 1. Aflăm unde ne aflăm acum (adică în folderul Clasificare_datasets_normal)
try:
    cale_curenta = os.path.dirname(os.path.abspath(__file__))
except NameError:
    cale_curenta = os.getcwd()

# 2. Facem un singur pas în spate ('..') pentru a ajunge la nivelul unde se află builder.py
cale_parinte = os.path.abspath(os.path.join(cale_curenta, '..'))

# 3. Adăugăm folderul părinte "pe radarul" lui Python
if cale_parinte not in sys.path:
    sys.path.insert(0, cale_parinte)

# Importuri din celelalte fișiere
from my_dataset_augmented import DRDatasetAugmented
from builder import get_model, get_optimizer, get_loss_function, compute_loss, get_predictions

def parse_args():
    parser = argparse.ArgumentParser(description="Antrenament DR - Train/Test din foldere")
    parser.add_argument('--model', type=str, default='resnet50', help='ex: resnet50, efficientnet_b3')
    parser.add_argument('--loss_name', type=str, default='ce', help='ex: ce, bce_ordinal, focal_loss, weighted_ce')
    
    # --- ARGUMENT NOU ---
    parser.add_argument('--optimizer', type=str, default='adam', help='Variante: adam, adamw, sgd')
    
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--batch_size', type=int, default=32)
    parser.add_argument('--lr', type=float, default=0.0001)
    parser.add_argument('--img_size', type=int, default=224)
    parser.add_argument('--num_workers', type=int, default=0)
    parser.add_argument('--class_weights', type=float, nargs='+', default=None)
    parser.add_argument('--nume_ds', type=str, default='aptos', help='Numele datasetului pentru loguri și logică internă')
    parser.add_argument('--root_dir', type=str, 
                        default=r'B:\Projects\Disertatie\Diabetic-Retinopathy-Classifier',)
    return parser.parse_args()

def main():
    args = parse_args()
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    # Setup foldere pentru rezultate
    os.makedirs("Clasificare_datasets_normal/Rezultate/modele", exist_ok=True)
    os.makedirs("Clasificare_datasets_normal/Rezultate/grafice", exist_ok=True)

    print(f"🔥 Config: {args.model} | Loss: {args.loss_name} | Opt: {args.optimizer} | LR: {args.lr}")
    
    # ==========================================
    # 1. ÎNCĂRCAREA DATELOR DIN FOLDERE
    # ==========================================
    # Numele datasetului tău pentru loguri (sau pentru logica internă a clasei)
    nume_ds = args.nume_ds
    
    # Inițializăm cele 3 seturi de date folosind noile tale argumente
    train_ds = DRDatasetAugmented(
        root_dir=args.root_dir, 
        dataset_name=nume_ds, 
        split='train', 
        image_size=args.img_size
    )
    
    test_ds = DRDatasetAugmented(
        root_dir=args.root_dir, 
        dataset_name=nume_ds, 
        split='test', 
        image_size=args.img_size
    )

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers)
    test_loader  = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)

    print(f"📊 Distribuție Date: TRAIN={len(train_ds)} | TESTARE={len(test_ds)}")

    # ==========================================
    # 2. INIȚIALIZARE COMPONENTE
    # ==========================================
    model = get_model(args.model, num_classes=5).to(device)
    criterion = get_loss_function(args.loss_name, class_weights=args.class_weights, device=device)
    
    # --- CONECTĂM NOUL ARGUMENT ---
    optimizer = get_optimizer(model, optimizer_name=args.optimizer, lr=args.lr)
    
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.5, patience=3)

    istoric = {'train_loss': [], 'test_loss': [], 'test_acc': [], 'test_auc': []}
    best_metric = 0.0
    
    # --- NUME NOU PENTRU MODEL ---
    baza_nume = f"{args.model}_{args.loss_name}_{args.optimizer}_LR_{args.lr}"
    cale_model = f"Clasificare_datasets_normal/Rezultate/modele/best_{baza_nume}.pth"

    # ==========================================
    # 3. BUCLA DE ANTRENARE ȘI TESTARE
    # ==========================================
    for epoch in range(args.epochs):
        start_time = time.time()
        
        # --- FAZA TRAIN ---
        model.train()
        t_loss = 0
        train_pbar = tqdm(train_loader, desc=f"Ep {epoch+1:02d} [TRAIN]", leave=False)
        for imgs, labels in train_pbar:
            imgs, labels = imgs.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(imgs)
            loss = compute_loss(criterion, outputs, labels, args.loss_name, device)
            loss.backward()
            optimizer.step()
            t_loss += loss.item()
            train_pbar.set_postfix({'loss': f"{loss.item():.4f}"})

        # --- FAZA TESTARE ---
        model.eval()
        v_loss, v_corr, v_total = 0, 0, 0
        all_test_labels, all_test_probs = [], []
        test_pbar = tqdm(test_loader, desc=f"Ep {epoch+1:02d} [TEST]", leave=False)
        with torch.no_grad():
            for imgs, labels in test_pbar:
                imgs, labels = imgs.to(device), labels.to(device)
                outputs = model(imgs)
                loss = compute_loss(criterion, outputs, labels, args.loss_name, device)
                v_loss += loss.item()
                preds = get_predictions(outputs, args.loss_name)
                v_corr += (preds == labels).sum().item()
                v_total += labels.size(0)
                all_test_labels.extend(labels.cpu().numpy())
                all_test_probs.extend(F.softmax(outputs, dim=1).cpu().numpy())

        # Statistici Epocă
        ep_t_loss = t_loss / len(train_loader)
        ep_test_loss = v_loss / len(test_loader)
        test_acc = v_corr / v_total
        try: 
            test_auc = roc_auc_score(all_test_labels, all_test_probs, multi_class='ovr', average='macro')
        except: 
            test_auc = 0.0

        istoric['train_loss'].append(ep_t_loss)
        istoric['test_loss'].append(ep_test_loss)
        istoric['test_acc'].append(test_acc)
        istoric['test_auc'].append(test_auc)

        scheduler.step(test_auc)

        # Salvare Cel Mai Bun Model
        metrica = test_auc if args.loss_name != 'bce_ordinal' else test_acc
        if metrica > best_metric:
            best_metric = metrica
            torch.save(model.state_dict(), cale_model)
            marker = "🌟 NOU BEST"
        else: 
            marker = ""

        print(f"Ep {epoch+1:02d}/{args.epochs} | T_Loss: {ep_t_loss:.4f} | V_Loss: {ep_test_loss:.4f} | V_Acc: {test_acc*100:.1f}% | V_AUC: {test_auc:.4f} {marker}")
        print(f"Durată Epocă: {(time.time() - start_time)/60:.2f} min")

    # ==========================================
    # 4. FAZA DE TESTARE FINALĂ
    # ==========================================
    print("\n" + "="*50)
    print("🚀 START FAZA DE TESTARE FINALĂ (PE FOLDERUL 'TEST')")
    print("="*50)
    
    model.load_state_dict(torch.load(cale_model))
    model.eval()
    
    test_loss, test_corr, test_total = 0, 0, 0
    all_test_preds, all_test_labels, all_test_probs = [], [], []
    
    test_pbar = tqdm(test_loader, desc="Testare Model", leave=False)
    with torch.no_grad():
        for imgs, labels in test_pbar:
            imgs, labels = imgs.to(device), labels.to(device)
            
            outputs = model(imgs)
            loss = compute_loss(criterion, outputs, labels, args.loss_name, device)
            test_loss += loss.item()
            
            preds = get_predictions(outputs, args.loss_name)
            test_corr += (preds == labels).sum().item()
            test_total += labels.size(0)
            
            all_test_preds.extend(preds.cpu().numpy())
            all_test_labels.extend(labels.cpu().numpy())
            all_test_probs.extend(F.softmax(outputs, dim=1).cpu().numpy())

    final_test_loss = test_loss / len(test_loader)
    final_test_acc = test_corr / test_total
    try: 
        final_test_auc = roc_auc_score(all_test_labels, all_test_probs, multi_class='ovr', average='macro')
    except: 
        final_test_auc = 0.0

    print(f"📊 REZULTATE TESTARE FINALĂ:")
    print(f"   ► Acuratețe: {final_test_acc*100:.2f}%")
    print(f"   ► Scor AUC:  {final_test_auc:.4f}")
    print(f"   ► Pierdere (Loss): {final_test_loss:.4f}\n")

    # ==========================================
    # 5. GENERARE GRAFICE ȘI MATRICE DE CONFUZIE
    # ==========================================
    print("📈 Generăm graficele...")
    plt.figure(figsize=(15, 5))
    
    plt.subplot(1, 3, 1)
    plt.plot(istoric['train_loss'], label='Train')
    plt.plot(istoric['test_loss'], label='Test')
    plt.title('Evoluție Loss')
    plt.legend()
    
    plt.subplot(1, 3, 2)
    plt.plot(istoric['test_acc'], color='orange', label='Acuratețe Test')
    plt.title('Acuratețe (Test)')
    plt.legend()
    
    plt.subplot(1, 3, 3)
    plt.plot(istoric['test_auc'], color='green', label='AUC Test')
    plt.title('Scor AUC (Test)')
    plt.legend()
    
    # --- NUME NOU PENTRU GRAFICUL DE EVOLUȚIE ---
    plt.savefig(f"Rezultate/grafice/e_{baza_nume}.png", bbox_inches='tight')
    plt.show()  # 👈 ADAUGĂ ACEASTĂ LINIE
    plt.close()

    cm = confusion_matrix(all_test_labels, all_test_preds)
    plt.figure(figsize=(8, 6))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', 
                xticklabels=['0', '1', '2', '3', '4'], yticklabels=['0', '1', '2', '3', '4'])
    plt.xlabel('Predicție (Model)')
    plt.ylabel('Realitate (Adevăr)')
    plt.title(f'Matrice Confuzie Test | Acc: {final_test_acc*100:.1f}% | AUC: {final_test_auc:.3f}')
    
    # --- NUME NOU PENTRU MATRICEA DE CONFUZIE ---
    plt.savefig(f"Rezultate/grafice/cm_{baza_nume}.png", bbox_inches='tight')
    plt.show()  # 👈 ADAUGĂ ACEASTĂ LINIE
    plt.close()
    
    print(f"✅ Gata! Fisiere salvate cu formatul: {baza_nume}")

if __name__ == '__main__':
    import sys
    if not hasattr(sys.modules['__main__'], '__spec__'):
        sys.modules['__main__'].__spec__ = None
    # torch.multiprocessing.freeze_support()
    main()