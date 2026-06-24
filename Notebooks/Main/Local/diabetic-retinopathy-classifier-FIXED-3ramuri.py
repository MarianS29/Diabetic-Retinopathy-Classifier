# ==============================================================================
# Setup - foldere de rezultate (Rezultate_main/...)
# ==============================================================================

import os, glob, shutil
from pathlib import Path

RESULTS_ROOT = Path("Rezultate_main")
DIR_BINAR = RESULTS_ROOT / "binar"
def dir_clasificare(mode): return RESULTS_ROOT / f"clasificare_{mode}"
for d in [DIR_BINAR] + [dir_clasificare(m) for m in ["crossentropy", "regression"]]:
    d.mkdir(parents=True, exist_ok=True)

# Mutam rezultatele vechi (daca exista) in folderele dedicate
def _muta(pattern, dest):
    for f in glob.glob(pattern):
        try:
            shutil.move(f, str(Path(dest) / os.path.basename(f)))
            print(f"  mutat {f} -> {dest}")
        except Exception as e:
            print(f"  (skip {f}: {e})")

_muta("efficientnet_b3_binar_best.pth", DIR_BINAR)
_muta("matrice_confuzie_binar.png", DIR_BINAR)
for m in ["crossentropy", "regression"]:
    _muta(f"efficientnet_b3_multiclass_{m}.pth", dir_clasificare(m))
    _muta(f"curbe_{m}.png", dir_clasificare(m))
    _muta(f"matrice_confuzie_{m}.png", dir_clasificare(m))
print("Foldere de rezultate gata.")


# Functii de grafice (refolosite la binar si la clasificarea multi-clasa)
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from sklearn.metrics import classification_report, confusion_matrix

def plot_curbe(train_loss, val_loss, train_acc, val_acc, metric_vals, metric_name, out_dir, titlu):
    xs = range(1, len(train_loss) + 1)
    # train loss + val loss
    plt.figure(figsize=(8, 5))
    plt.plot(xs, train_loss, label='Train Loss', lw=2)
    plt.plot(xs, val_loss, label='Val Loss', lw=2, ls='--')
    plt.title(f'Loss {titlu}', fontweight='bold'); plt.xlabel('Epoca'); plt.legend(); plt.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(Path(out_dir) / 'curbe_loss.png', dpi=200, bbox_inches='tight'); plt.show()
    # train acc + val acc
    plt.figure(figsize=(8, 5))
    plt.plot(xs, train_acc, label='Train Acc', lw=2)
    plt.plot(xs, val_acc, label='Val Acc', lw=2, ls='--')
    plt.title(f'Accuracy {titlu}', fontweight='bold'); plt.xlabel('Epoca'); plt.ylim(0, 1); plt.legend(); plt.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(Path(out_dir) / 'curbe_acc.png', dpi=200, bbox_inches='tight'); plt.show()
    # metrica (QWK sau AUC)
    plt.figure(figsize=(8, 5))
    plt.plot(xs, metric_vals, color='green', lw=2)
    plt.title(f'Val {metric_name} {titlu}', fontweight='bold'); plt.xlabel('Epoca'); plt.ylim(-0.05, 1); plt.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(Path(out_dir) / f'curba_{metric_name.lower()}.png', dpi=200, bbox_inches='tight'); plt.show()

def plot_prf(y_true, y_pred, class_names, out_dir, titlu):
    rep = classification_report(y_true, y_pred, target_names=class_names, labels=list(range(len(class_names))), output_dict=True, zero_division=0)
    prec = [rep[c]['precision'] for c in class_names]
    rec  = [rep[c]['recall']    for c in class_names]
    f1   = [rep[c]['f1-score']  for c in class_names]
    x = np.arange(len(class_names)); w = 0.25
    plt.figure(figsize=(max(8, 1.8 * len(class_names)), 5))
    plt.bar(x - w, prec, w, label='Precision')
    plt.bar(x,     rec,  w, label='Recall')
    plt.bar(x + w, f1,   w, label='F1')
    plt.xticks(x, class_names, rotation=15); plt.ylim(0, 1); plt.grid(axis='y', alpha=.3)
    plt.title(f'Distributie Precision / Recall / F1 {titlu}', fontweight='bold'); plt.legend()
    plt.tight_layout(); plt.savefig(Path(out_dir) / 'prf_bars.png', dpi=200, bbox_inches='tight'); plt.show()

def plot_confuzie(y_true, y_pred, class_names, out_dir, titlu):
    cm = confusion_matrix(y_true, y_pred, labels=list(range(len(class_names))))
    fig, axes = plt.subplots(1, 2, figsize=(8 + 2 * len(class_names), 6))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', xticklabels=class_names, yticklabels=class_names,
                ax=axes[0], annot_kws={"size": 13})
    axes[0].set_title('Valori absolute', fontweight='bold'); axes[0].set_ylabel('Adevarata'); axes[0].set_xlabel('Prezisa')
    cm_norm = cm.astype(float) / cm.sum(axis=1, keepdims=True).clip(min=1)
    sns.heatmap(cm_norm, annot=True, fmt='.2f', cmap='Blues', xticklabels=class_names, yticklabels=class_names,
                ax=axes[1], annot_kws={"size": 13}, vmin=0, vmax=1)
    axes[1].set_title('Normalizata (recall/rand)', fontweight='bold'); axes[1].set_ylabel('Adevarata'); axes[1].set_xlabel('Prezisa')
    plt.suptitle(f'Matrice de confuzie {titlu}', fontweight='bold', y=1.02)
    plt.tight_layout(); plt.savefig(Path(out_dir) / 'confusion.png', dpi=300, bbox_inches='tight'); plt.show()
print("Functii de grafice gata.")


# ==============================================================================
# EfficientNet-B3 Binar - versiune corectata
# ==============================================================================
# 
# Ce s-a schimbat fata de varianta ta si de ce:
# 
# 1. Antrenare in doua faze (FREEZE_BACKBONE_EPOCHS = 3). In faza 1 backbone-ul e inghetat si se antreneaza doar capul nou, cu LR mare (1e-3). In faza 2 se dezgheata tot, cu LR diferentiat: backbone 1e-4, cap 3e-4.
# 2. Augmentare activata (flip, rotatie, color jitter) - era complet comentata.
# 3. num_workers=0 - propriul tau comentariu avertiza ca pe Windows num_workers>0 ingheata la epoca 2.
# 4. AUC raportat si monitorizat - early stopping si checkpoint pe AUC de validare.
# 5. Prag de decizie ales pe validare (Youden's J) si aplicat consecvent pe test.
# 6. Etichete fortate la float in bucla.
# 7. Celula optionala de sanity-check.

import os
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import models, transforms
from torch.utils.data import DataLoader, Subset
from tqdm import tqdm
from sklearn.metrics import classification_report, accuracy_score, roc_auc_score, roc_curve
import matplotlib.pyplot as plt

# Importam DOAR clasa de Dataset din fisierul nostru extern
from binary_dataset import BinaryRetinopathyDataset

print("=== INCARCARE DATE SI DATALOADERS ===")

DATA_DIR = r'B:\Projects\Disertatie\Diabetic-Retinopathy-Classifier\datasets\processed_by_me\eyepacs\eyepacs_binar'
IMG_SIZE = 300          # rezolutia nativa a EfficientNet-B3
BATCH_SIZE = 32         # la 512: scade la 16/8 daca iei CUDA Out of Memory
USE_BEN_GRAHAM = False  # vezi nota din primul cell inainte sa activezi

# --- Preprocesare optionala specifica de fundus (Ben Graham, EyePACS 2015) ---
class BenGrahamPreprocess:
    def __init__(self, sigma_scale=10, crop_tol=7):
        self.sigma_scale = sigma_scale
        self.crop_tol = crop_tol

    def _crop_to_circle(self, img):
        import cv2
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        mask = gray > self.crop_tol
        if mask.sum() == 0:
            return img
        coords = np.argwhere(mask)
        y0, x0 = coords.min(axis=0)
        y1, x1 = coords.max(axis=0) + 1
        return img[y0:y1, x0:x1]

    def __call__(self, img):
        import cv2
        from PIL import Image
        arr = np.array(img.convert("RGB"))
        arr = self._crop_to_circle(arr)
        s = max(arr.shape[0], arr.shape[1]) / self.sigma_scale
        blurred = cv2.GaussianBlur(arr, (0, 0), s)
        arr = cv2.addWeighted(arr, 4, blurred, -4, 128)
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


_pre = [BenGrahamPreprocess()] if USE_BEN_GRAHAM else []
_norm = transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])

# 1. Transformari - AUGMENTAREA E ACUM ACTIVA pe train
train_transform = transforms.Compose(_pre + [
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomVerticalFlip(p=0.5),
    transforms.RandomRotation(15),
    transforms.ColorJitter(brightness=0.1, contrast=0.1),
    transforms.ToTensor(),
    _norm,
])

test_transform = transforms.Compose(_pre + [
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.ToTensor(),
    _norm,
])

# 2. Dataseturi
train_ds = BinaryRetinopathyDataset(os.path.join(DATA_DIR, 'train'), transform=train_transform)
val_ds   = BinaryRetinopathyDataset(os.path.join(DATA_DIR, 'val'),   transform=test_transform)
test_ds  = BinaryRetinopathyDataset(os.path.join(DATA_DIR, 'test'),  transform=test_transform)

# 3. DataLoadere - num_workers=0 pe Windows
NUM_WORKERS = 8
train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,  num_workers=NUM_WORKERS, pin_memory=True)
val_loader   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False, num_workers=NUM_WORKERS, pin_memory=True)
test_loader  = DataLoader(test_ds,  batch_size=BATCH_SIZE, shuffle=False, num_workers=NUM_WORKERS, pin_memory=True)

print("DataLoaderele au fost create cu succes!")
print(f"Numar de batch-uri pe antrenament: {len(train_loader)}")
print(f"Ben Graham: {'ACTIV' if USE_BEN_GRAHAM else 'dezactivat'}")


# ==============================================================================
# Model + configuratie in doua faze
# ==============================================================================

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Antrenam pe: {device}")

# --- Hiperparametri ---
HEAD_LR_PHASE1     = 1e-3   
BACKBONE_LR_PHASE2 = 1e-4   
HEAD_LR_PHASE2     = 3e-4   
WEIGHT_DECAY       = 1e-4
DROPOUT            = 0.40
FREEZE_BACKBONE_EPOCHS  = 3   
EARLY_STOPPING_PATIENCE = 30
USE_POS_WEIGHT     = False     

# --- EfficientNet-B3 pre-antrenat ---
model = models.efficientnet_b3(weights=models.EfficientNet_B3_Weights.IMAGENET1K_V1)
num_features = model.classifier[1].in_features
model.classifier[1] = nn.Sequential(
    nn.Dropout(p=DROPOUT),
    nn.Linear(num_features, 1)
)
model = model.to(device)

# Verificam distributia claselor
num_sanatosi = len(os.listdir(os.path.join(DATA_DIR, 'train', 'sanatos')))
num_bolnavi  = len(os.listdir(os.path.join(DATA_DIR, 'train', 'bolnav')))
print(f"Clase: sanatos={num_sanatosi}, bolnav={num_bolnavi}")

if USE_POS_WEIGHT:
    pos_weight = torch.tensor([num_sanatosi / max(num_bolnavi, 1)], dtype=torch.float32, device=device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    print(f"pos_weight activ: {pos_weight.item():.4f}")
else:
    criterion = nn.BCEWithLogitsLoss()
    print("pos_weight dezactivat (set echilibrat).")


# --- Helpers pentru inghet/dezghet si construirea optimizatorului pe faze ---
def set_backbone_trainable(m, trainable):
    for name, p in m.named_parameters():
        if not name.startswith("classifier"):
            p.requires_grad = trainable

def split_params(m):
    head = [p for n, p in m.named_parameters() if n.startswith("classifier")]
    backbone = [p for n, p in m.named_parameters() if not n.startswith("classifier")]
    return head, backbone

def build_optimizer_phase1(m):
    set_backbone_trainable(m, False)  
    head, _ = split_params(m)
    opt = optim.AdamW(head, lr=HEAD_LR_PHASE1, weight_decay=WEIGHT_DECAY)
    sch = optim.lr_scheduler.ReduceLROnPlateau(opt, mode='max', factor=0.5, patience=2)
    return opt, sch

def build_optimizer_phase2(m):
    set_backbone_trainable(m, True)   
    head, backbone = split_params(m)
    opt = optim.AdamW([
        {"params": backbone, "lr": BACKBONE_LR_PHASE2},
        {"params": head,     "lr": HEAD_LR_PHASE2},
    ], weight_decay=WEIGHT_DECAY)
    sch = optim.lr_scheduler.ReduceLROnPlateau(opt, mode='max', factor=0.5, patience=2)
    return opt, sch

scaler = torch.amp.GradScaler('cuda')
print("Model si configuratie gata. Faza 1 (backbone inghetat) incepe la antrenare.")


# ==============================================================================
# (Optional) Sanity-check: poate modelul sa suprainvete 100 de imagini?
# ==============================================================================
RUN_SANITY = True  

if RUN_SANITY:
    import copy
    small = Subset(train_ds, list(range(100)))
    small_loader = DataLoader(small, batch_size=16, shuffle=True, num_workers=0)
    m = copy.deepcopy(model)
    set_backbone_trainable(m, True)
    opt = optim.AdamW(m.parameters(), lr=1e-4, weight_decay=0)
    for ep in range(20):
        m.train(); preds, tgts = [], []
        for images, labels in small_loader:
            images = images.to(device); labels = labels.float().to(device)
            opt.zero_grad()
            with torch.amp.autocast('cuda'):
                out = m(images).squeeze(1)
                loss = criterion(out, labels)
            scaler.scale(loss).backward(); scaler.step(opt); scaler.update()
            preds += ((torch.sigmoid(out) > 0.5).int().detach().cpu().numpy().tolist())
            tgts  += labels.int().cpu().numpy().tolist()
        acc = accuracy_score(tgts, preds)
        print(f"sanity epoca {ep+1}: train_acc={acc:.3f}")
    print("Daca acc ajunge ~1.0 -> pipeline OK. Daca ramane ~0.5 -> problema in date/etichete.")
else:
    print("Sanity-check dezactivat (RUN_SANITY=False).")


# ==============================================================================
# Antrenare (doua faze + early stopping pe AUC)
# ==============================================================================

EPOCHS = 50
FREEZE_BACKBONE_EPOCHS  = 10
best_val_auc = -1.0
bad_epochs = 0

optimizer, scheduler = build_optimizer_phase1(model)
print("=== INCEPERE ANTRENARE - FAZA 1 (backbone inghetat) ===")

history = {"train_loss": [], "train_acc": [], "val_loss": [], "val_acc": [], "val_auc": []}

for epoch in range(EPOCHS):
    if epoch == FREEZE_BACKBONE_EPOCHS:
        optimizer, scheduler = build_optimizer_phase2(model)
        print("=== FAZA 2: backbone dezghetat, fine-tuning complet cu LR diferentiat ===")

    # ---- TRAIN ----
    model.train()
    train_loss = 0.0
    train_corrects = 0 

    for images, labels in tqdm(train_loader, desc=f"Epoca {epoch+1}/{EPOCHS} [TRAIN]"):
        images = images.to(device)
        labels = labels.float().to(device)        
        optimizer.zero_grad()
        
        with torch.amp.autocast('cuda'):
            outputs = model(images).squeeze(1)
            loss = criterion(outputs, labels)
            
            probs = torch.sigmoid(outputs.detach())
            preds = (probs > 0.5).float()
            train_corrects += torch.sum(preds == labels).item()

        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()
        
        train_loss += loss.item() * images.size(0)

    # ---- VAL ----
    model.eval()
    val_loss = 0.0
    val_probs, val_targets = [], []
    with torch.no_grad():
        for images, labels in tqdm(val_loader, desc=f"Epoca {epoch+1}/{EPOCHS} [VAL]"):
            images = images.to(device)
            labels = labels.float().to(device)
            outputs = model(images).squeeze(1)
            loss = criterion(outputs, labels)
            val_loss += loss.item() * images.size(0)
            val_probs.extend(torch.sigmoid(outputs).cpu().numpy())
            val_targets.extend(labels.cpu().numpy())

    avg_train_loss = train_loss / len(train_ds)
    avg_train_acc  = train_corrects / len(train_ds) 

    avg_val_loss   = val_loss / len(val_ds)
    val_preds = (np.array(val_probs) > 0.5).astype(int)
    val_acc = accuracy_score(val_targets, val_preds)
    
    try:
        val_auc = roc_auc_score(val_targets, val_probs)
    except ValueError:
        val_auc = float("nan")

    history["train_loss"].append(avg_train_loss)
    history["train_acc"].append(avg_train_acc) 
    history["val_loss"].append(avg_val_loss)
    history["val_acc"].append(val_acc)
    history["val_auc"].append(val_auc)

    scheduler.step(val_auc) 
    
    current_lr = optimizer.param_groups[0]['lr'] 

    print(f"Epoca {epoch+1}: T_Loss={avg_train_loss:.4f} | T_Acc={avg_train_acc:.4f} | V_Loss={avg_val_loss:.4f} "
          f"| V_Acc={val_acc:.4f} | V_AUC={val_auc:.4f} | LR={current_lr:.1e}")

    # Checkpoint + early stopping pe AUC
    if val_auc > best_val_auc + 1e-4:
        best_val_auc = val_auc
        bad_epochs = 0
        torch.save(model.state_dict(), 'efficientnet_b3_binar_best.pth')
        print(f"Model nou salvat! (Val AUC: {best_val_auc:.4f})")
    else:
        bad_epochs += 1
        print(f"Fara imbunatatire pe AUC: {bad_epochs}/{EARLY_STOPPING_PATIENCE}")
        if bad_epochs >= EARLY_STOPPING_PATIENCE:
            print("Early stopping.")
            break

print(f"Cel mai bun Val AUC: {best_val_auc:.4f}")

# ==============================================================================
# Evaluare pe test
# ==============================================================================

import seaborn as sns
from sklearn.metrics import confusion_matrix, fbeta_score, f1_score

model.load_state_dict(torch.load(DIR_BINAR / 'efficientnet_b3_binar_best.pth')); model.eval()
CN_BIN = ['Sanatos (0)', 'Bolnav (1)']

# beta=2 -> FN sunt de 2x mai grave decat FP
beta = 2.0
best_thr, best_fb = 0.5, 0.0

# Prag optim pe validare 
v_probs, v_targets = [], []
with torch.no_grad():
    for images, labels in tqdm(val_loader, desc="Val (prag)"):
        images = images.to(device)
        v_probs.extend(torch.sigmoid(model(images).squeeze(1)).cpu().numpy())
        v_targets.extend(labels.numpy())
v_probs = np.array(v_probs)

for t in np.linspace(0.01, 0.99, 200):
    preds = (v_probs > t).astype(int)
    fb = fbeta_score(v_targets, preds, beta=beta, pos_label=1, zero_division=0)
    if fb > best_fb:
        best_fb = fb
        best_thr = t

print(f"Prag optim pe F{beta}: {best_thr:.3f} (F{beta}={best_fb:.3f})")

# Probabilitati pe TEST
test_probs, test_targets = [], []
with torch.no_grad():
    for images, labels in tqdm(test_loader, desc="Testare"):
        images = images.to(device)
        test_probs.extend(torch.sigmoid(model(images).squeeze(1)).cpu().numpy())
        test_targets.extend(labels.numpy())
test_probs = np.array(test_probs)
test_auc = roc_auc_score(test_targets, test_probs)
print(f"\nTest AUC: {test_auc:.4f}")

for label, t in [("prag 0.5", 0.5), (f"prag {best_thr:.3f} (din val)", best_thr)]:
    preds = (test_probs > t).astype(int)
    print(f"\nRAPORT - {label}:")
    print(classification_report(test_targets, preds, target_names=CN_BIN, labels=[0,1], digits=3))

test_pred = (test_probs > best_thr).astype(int)

# Grafice
plot_curbe(history["train_loss"], history["val_loss"], history["train_acc"], history["val_acc"],
           history["val_auc"], 'AUC', DIR_BINAR, '- Binar')
plot_prf(test_targets, test_pred, CN_BIN, DIR_BINAR, '- Binar')
plot_confuzie(test_targets, test_pred, CN_BIN, DIR_BINAR, '- Binar')
print(f"Grafice salvate in {DIR_BINAR}")


# ==============================================================================
# Clasificare 1-4 - sectiune comuna
# ==============================================================================

import os
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torchvision import models, transforms
from torch.utils.data import DataLoader, Subset
from tqdm import tqdm
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix, cohen_kappa_score
import scipy.optimize as opt
import matplotlib.pyplot as plt
import seaborn as sns
import sys
from pathlib import Path

DATA_DIR    = r'B:\Projects\Disertatie\Diabetic-Retinopathy-Classifier\datasets\processed_by_me\eyepacs\eyepacs_1_4'
IMG_SIZE    = 300
BATCH_SIZE  = 32   
NUM_CLASSES = 4
CLASS_NAMES = ['Stadiul 1', 'Stadiul 2', 'Stadiul 3', 'Stadiul 4']
NUM_WORKERS = 8   

_norm = transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])

train_transform = transforms.Compose([
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomVerticalFlip(p=0.5),
    transforms.RandomRotation(15),
    transforms.ColorJitter(brightness=0.15, contrast=0.15),
    transforms.RandomAffine(degrees=0, translate=(0.05, 0.05)),
    transforms.ToTensor(),
    _norm,
])
test_transform = transforms.Compose([
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.ToTensor(),
    _norm,
])

LOCAL_DIR = Path(r'B:\Projects\Disertatie\Diabetic-Retinopathy-Classifier\Notebooks\Main\Local')
if str(LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_DIR))
from dataset_1_4 import MultiClassRetinopathyDataset

train_ds = MultiClassRetinopathyDataset(os.path.join(DATA_DIR, 'train'), transform=train_transform)
val_ds   = MultiClassRetinopathyDataset(os.path.join(DATA_DIR, 'val'),   transform=test_transform)
test_ds  = MultiClassRetinopathyDataset(os.path.join(DATA_DIR, 'test'),  transform=test_transform)

loader_kwargs = {'num_workers': NUM_WORKERS, 'pin_memory': torch.cuda.is_available()}
if NUM_WORKERS > 0:
    loader_kwargs['prefetch_factor'] = 1

train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,  **loader_kwargs)
val_loader   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False, **loader_kwargs)
test_loader  = DataLoader(test_ds,  batch_size=BATCH_SIZE, shuffle=False, **loader_kwargs)

print("=== STATISTICI DATASET ===")
print(f"Mapare clase: {train_ds.class_to_idx}")
for split_name, ds in [("TRAIN", train_ds), ("VAL", val_ds), ("TEST", test_ds)]:
    targets = np.array(ds.targets)
    print(f"{split_name} ({len(ds)}): " + ", ".join(f"{c}={(targets==i).sum()}" for i,c in enumerate(CLASS_NAMES)))
print(f"Batch-uri train: {len(train_loader)}")


device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Antrenam pe: {device}")

HEAD_LR_PHASE1          = 1e-3
BACKBONE_LR_PHASE2      = 1e-4
HEAD_LR_PHASE2          = 3e-4
WEIGHT_DECAY            = 1e-4
DROPOUT                 = 0.40
FREEZE_BACKBONE_EPOCHS  = 5
TOTAL_EPOCHS            = 50
EARLY_STOPPING_PATIENCE = 30
LABEL_SMOOTHING         = 0.10   
SEED                    = 42

torch.manual_seed(SEED); np.random.seed(SEED)

# ---------------- Construire model in functie de MODE ----------------
def build_model(mode):
    m = models.efficientnet_b3(weights=models.EfficientNet_B3_Weights.IMAGENET1K_V1)
    nf = m.classifier[1].in_features
    if mode == "crossentropy":
        m.classifier[1] = nn.Sequential(nn.Dropout(DROPOUT), nn.Linear(nf, NUM_CLASSES))
    elif mode == "regression":
        m.classifier[1] = nn.Sequential(nn.Dropout(DROPOUT), nn.Linear(nf, 1))
    else:
        raise ValueError(f"MODE necunoscut: {mode}")
    return m.to(device)

ce_criterion  = nn.CrossEntropyLoss(label_smoothing=LABEL_SMOOTHING)
reg_criterion = nn.SmoothL1Loss()

def compute_loss(out, labels):
    if MODE == "crossentropy":
        return ce_criterion(out, labels)
    if MODE == "regression":
        return reg_criterion(out.squeeze(1), labels.float())

def decode(out):
    """Predictii intregi 0..K-1 pentru monitorizare (regresie: rotunjire naiva)."""
    if MODE == "crossentropy":
        return out.argmax(1)
    if MODE == "regression":
        return out.squeeze(1).round().clamp(0, NUM_CLASSES - 1).long()

def raw_scores(out):
    """Iesirea continua pentru regresie (necesara la rounder-ul optimizat)."""
    return out.squeeze(1) if MODE == "regression" else None

# ---------------- Rounder optimizat pe validare (doar regresie) ----------------
class OptimizedRounder:
    """Alege K-1 praguri care maximizeaza QWK pe validare (Nelder-Mead)."""
    def __init__(self, n_classes): self.n_classes = n_classes; self.coef_ = None
    def _classify(self, X, coef):
        return np.clip(np.digitize(X, np.sort(coef)), 0, self.n_classes - 1)
    def _neg_qwk(self, coef, X, y):
        return -cohen_kappa_score(y, self._classify(X, coef), weights='quadratic')
    def fit(self, X, y):
        init = np.arange(self.n_classes - 1) + 0.5
        r = opt.minimize(self._neg_qwk, init, args=(X, y), method='Nelder-Mead')
        self.coef_ = np.sort(r.x)
    def predict(self, X):
        return self._classify(X, self.coef_)

# ---------------- Freeze/unfreeze + optimizatoare pe faze ----------------
def set_backbone_trainable(m, trainable):
    for name, p in m.named_parameters():
        if not name.startswith("classifier"):
            p.requires_grad = trainable

def split_params(m):
    head     = [p for n, p in m.named_parameters() if n.startswith("classifier")]
    backbone = [p for n, p in m.named_parameters() if not n.startswith("classifier")]
    return head, backbone

def build_optimizer_phase1(m):
    set_backbone_trainable(m, False)
    head, _ = split_params(m)
    o = optim.AdamW(head, lr=HEAD_LR_PHASE1, weight_decay=WEIGHT_DECAY)
    s = optim.lr_scheduler.ReduceLROnPlateau(o, mode='max', factor=0.5, patience=2)
    return o, s

def build_optimizer_phase2(m):
    set_backbone_trainable(m, True)
    head, backbone = split_params(m)
    o = optim.AdamW([{"params": backbone, "lr": BACKBONE_LR_PHASE2},
                     {"params": head,     "lr": HEAD_LR_PHASE2}], weight_decay=WEIGHT_DECAY)
    s = optim.lr_scheduler.ReduceLROnPlateau(o, mode='max', factor=0.5, patience=2)
    return o, s

print("Helperi de clasificare gata (build_model, compute_loss, decode, ...).")


def ruleaza_ramura(mode):
    """Codul tau de antrenare in 2 faze + evaluare, pentru un mod."""
    global MODE
    MODE = mode
    torch.manual_seed(SEED); np.random.seed(SEED)
    out_dir = dir_clasificare(mode)
    CKPT = str(out_dir / 'model_best.pth')

    model = build_model(mode)
    scaler = torch.amp.GradScaler('cuda', enabled=(device.type == 'cuda'))
    optimizer, scheduler = build_optimizer_phase1(model)
    best_val_qwk = -1.0
    epochs_no_improve = 0
    history = {'t_loss': [], 'v_loss': [], 't_acc': [], 'v_acc': [], 'v_qwk': []}

    print(f"=== ANTRENARE [{mode}] - FAZA 1 (backbone inghetat) ===")
    for epoch in range(TOTAL_EPOCHS):
        if epoch == FREEZE_BACKBONE_EPOCHS:
            optimizer, scheduler = build_optimizer_phase2(model)
            print("=== FAZA 2: backbone dezghetat, fine-tuning complet ===")

        # ---- TRAIN ----
        model.train(); train_loss = 0.0; train_preds, train_targets = [], []
        for images, labels in tqdm(train_loader, desc=f"[{mode}] Epoca {epoch+1}/{TOTAL_EPOCHS} [TRAIN]"):
            images = images.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast('cuda', enabled=(device.type == 'cuda')):
                out = model(images); loss = compute_loss(out, labels)
            scaler.scale(loss).backward(); scaler.step(optimizer); scaler.update()
            train_loss += loss.item() * images.size(0)
            train_preds.extend(decode(out).detach().cpu().tolist())
            train_targets.extend(labels.detach().cpu().tolist())

        # ---- VAL ----
        model.eval(); val_loss = 0.0; val_preds, val_targets = [], []
        with torch.no_grad():
            for images, labels in tqdm(val_loader, desc=f"[{mode}] Epoca {epoch+1}/{TOTAL_EPOCHS} [VAL]"):
                images = images.to(device, non_blocking=True)
                labels = labels.to(device, non_blocking=True)
                with torch.amp.autocast('cuda', enabled=(device.type == 'cuda')):
                    out = model(images); loss = compute_loss(out, labels)
                val_loss += loss.item() * images.size(0)
                val_preds.extend(decode(out).detach().cpu().tolist())
                val_targets.extend(labels.detach().cpu().tolist())

        avg_train_loss = train_loss / len(train_ds)
        avg_val_loss   = val_loss / len(val_ds)
        train_acc = accuracy_score(train_targets, train_preds)
        val_acc = accuracy_score(val_targets, val_preds)
        val_qwk = cohen_kappa_score(val_targets, val_preds, weights='quadratic')
        for k, v in zip(history, [avg_train_loss, avg_val_loss, train_acc, val_acc, val_qwk]):
            history[k].append(v)
        scheduler.step(val_qwk)
        print(f"Epoca {epoch+1}: T_Loss={avg_train_loss:.4f} | V_Loss={avg_val_loss:.4f} "
              f"| T_Acc={train_acc:.4f} | V_Acc={val_acc:.4f} | V_QWK={val_qwk:.4f}")

        if val_qwk > best_val_qwk + 1e-4:
            best_val_qwk = val_qwk; epochs_no_improve = 0
            torch.save(model.state_dict(), CKPT)
            print(f"Model nou salvat! (Val QWK: {best_val_qwk:.4f})")
        else:
            epochs_no_improve += 1
            print(f"Fara imbunatatire pe QWK: {epochs_no_improve}/{EARLY_STOPPING_PATIENCE}")
            if epochs_no_improve >= EARLY_STOPPING_PATIENCE:
                print("Early stopping."); break
    print(f"Cel mai bun Val QWK [{mode}]: {best_val_qwk:.4f}")

    # ---- EVALUARE PE TEST ----
    model.load_state_dict(torch.load(CKPT)); model.eval()
    def collect(loader):
        preds, targets, scores = [], [], []
        with torch.no_grad():
            for images, labels in tqdm(loader, desc=f"[{mode}] eval"):
                images = images.to(device)
                out = model(images)
                preds.extend(decode(out).cpu().tolist())
                targets.extend(labels.tolist())
                if mode == "regression":
                    scores.extend(raw_scores(out).cpu().numpy())
        return np.array(preds), np.array(targets), np.array(scores)

    if mode == "regression":
        _, val_t, val_s = collect(val_loader)
        rounder = OptimizedRounder(NUM_CLASSES); rounder.fit(val_s, val_t)
        np.save(out_dir / 'rounder_coef.npy', rounder.coef_)
        print(f"Praguri optime (din val): {np.round(rounder.coef_, 3)}")
        _, test_t, test_s = collect(test_loader)
        test_p = rounder.predict(test_s)
    else:
        test_p, test_t, _ = collect(test_loader)

    test_acc = accuracy_score(test_t, test_p)
    test_qwk = cohen_kappa_score(test_t, test_p, weights='quadratic')
    print(f"\nTest Accuracy : {test_acc:.4f}\nTest QWK      : {test_qwk:.4f}\n")
    print(classification_report(test_t, test_p, target_names=CLASS_NAMES, labels=list(range(NUM_CLASSES)), digits=3))

    # Grafice
    plot_curbe(history['t_loss'], history['v_loss'], history['t_acc'], history['v_acc'],
               history['v_qwk'], 'QWK', out_dir, f'- [{mode}]')
    plot_prf(test_t, test_p, CLASS_NAMES, out_dir, f'- [{mode}]')
    plot_confuzie(test_t, test_p, CLASS_NAMES, out_dir, f'- [{mode}] QWK={test_qwk:.3f}')
    print(f"Salvat in {out_dir}")
    return {'mode': mode, 'qwk': test_qwk, 'acc': test_acc}

print("Functia ruleaza_ramura gata.")

# Ramura regression
res_reg = ruleaza_ramura("regression")

# ==============================================================================
# Inferenta - cascada (binar -> clasificare)
# ==============================================================================

from PIL import Image

INFER_MODE = "regression"     # "crossentropy" | "regression"
PRAG_BINAR = 0.50             # p_sick < PRAG => sanatos (grad 0)

def _build_binary():
    m = models.efficientnet_b3(weights=None)
    nf = m.classifier[1].in_features
    m.classifier[1] = nn.Sequential(nn.Dropout(0.40), nn.Linear(nf, 1))
    return m.to(device)

binm = _build_binary()
binm.load_state_dict(torch.load(DIR_BINAR / 'efficientnet_b3_binar_best.pth')); binm.eval()

MODE = INFER_MODE
clsm = build_model(INFER_MODE)
clsm.load_state_dict(torch.load(dir_clasificare(INFER_MODE) / 'model_best.pth')); clsm.eval()

_rounder_coef = None
if INFER_MODE == "regression":
    p = dir_clasificare("regression") / 'rounder_coef.npy'
    if p.exists():
        _rounder_coef = np.load(p)

GRADE_NAMES = ['Grad 0 (No DR)', 'Grad 1', 'Grad 2', 'Grad 3', 'Grad 4']

@torch.no_grad()
def prezice_imagine(path, prag=PRAG_BINAR):
    img = Image.open(path).convert("RGB")
    x = test_transform(img).unsqueeze(0).to(device)
    p_sick = torch.sigmoid(binm(x).squeeze(1)).item()
    if p_sick < prag:
        return {"grad_final": 0, "eticheta": GRADE_NAMES[0], "p_sick": round(p_sick, 3), "etapa": "binar"}
    out = clsm(x)
    if INFER_MODE == "regression":
        s = out.squeeze(1).item()
        if _rounder_coef is not None:
            g = int(np.clip(np.digitize([s], np.sort(_rounder_coef))[0], 0, NUM_CLASSES - 1))
        else:
            g = int(np.clip(round(s), 0, NUM_CLASSES - 1))
    else:
        g = int(decode(out).item())
    grad_final = g + 1   # clasificatorul da 0..3 -> gradele 1..4
    return {"grad_final": grad_final, "eticheta": GRADE_NAMES[grad_final], "p_sick": round(p_sick, 3), "etapa": "cascada"}

import random
print("=== DEMO INFERENTA IN CASCADA (Binar -> Multi-Clasa) ===")

DIR_TEST_SANATOS = r'B:\Projects\Disertatie\Diabetic-Retinopathy-Classifier\datasets\processed_by_me\eyepacs\eyepacs_binar\test\0_sanatos'
DIR_TEST_MULTI = r'B:\Projects\Disertatie\Diabetic-Retinopathy-Classifier\datasets\processed_by_me\eyepacs\eyepacs_1_4\test'

fisiere_demo = []

if os.path.exists(DIR_TEST_SANATOS):
    poze_0 = [os.path.join(DIR_TEST_SANATOS, f) for f in os.listdir(DIR_TEST_SANATOS) if f.endswith(('.png', '.jpg', '.jpeg'))]
    if poze_0:
        fisiere_demo.extend(random.sample(poze_0, min(2, len(poze_0))))

stadii = ['stadiul_1', 'stadiul_2', 'stadiul_3', 'stadiul_4']
for stadiu in stadii:
    dir_stadiu = os.path.join(DIR_TEST_MULTI, stadiu)
    if os.path.exists(dir_stadiu):
        poze_stadiu = [os.path.join(dir_stadiu, f) for f in os.listdir(dir_stadiu) if f.endswith(('.png', '.jpg', '.jpeg'))]
        if poze_stadiu:
            fisiere_demo.append(random.choice(poze_stadiu))

random.shuffle(fisiere_demo)
fisiere_demo = fisiere_demo[:6]

if not fisiere_demo:
    print("[Eroare] Nu am gasit imagini. Verifica rutele folderelor de test.")
else:
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
    axes = axes.flatten()

    for idx, img_path in enumerate(fisiere_demo):
        rezultat = prezice_imagine(img_path)
        img_display = Image.open(img_path)
        
        ax = axes[idx]
        ax.imshow(img_display)
        ax.axis('off') 
        
        titlu = f"Predictie: {rezultat['eticheta']}\n"
        titlu += f"P_bolnav: {rezultat['p_sick']:.3f} | Model decizional: {rezultat['etapa'].upper()}"
        
        culoare = 'green' if rezultat['grad_final'] == 0 else 'red'
        ax.set_title(titlu, color=culoare, fontsize=11, fontweight='bold', pad=10)

    for i in range(len(fisiere_demo), len(axes)):
        axes[i].axis('off')

    plt.tight_layout()
    plt.show()