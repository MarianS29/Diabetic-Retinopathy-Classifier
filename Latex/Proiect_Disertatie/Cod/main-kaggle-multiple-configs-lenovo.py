# ==========================================
# IMPORTURI SI ELIBERARE MEMORIE
# ==========================================
import os
import time
import gc
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, models
from PIL import Image
from sklearn.metrics import accuracy_score, f1_score
import matplotlib.pyplot as plt

def curata_memoria():
    print("Initializare proces de curatare a memoriei...")
    
    # 1. Identificarea si stergerea variabilelor globale reziduale
    variabile_grele = ['model', 'train_loader', 'test_loader', 'train_ds', 'test_ds', 
                       'full_dataset', 'images', 'labels', 'optimizer', 'df']
    
    pentru_curatare = 0
    for var in variabile_grele:
        if var in globals():
            del globals()[var]
            pentru_curatare += 1
            
    # 2. Eliberare memorie RAM
    gc.collect()
    
    # 3. Eliberare memorie VRAM si procese IPC ramase de la dataloadere
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect() 
        
    print(f"S-au eliminat {pentru_curatare} variabile din mediul global.")
    print("Memoria RAM si VRAM a fost eliberata cu succes.\n")

curata_memoria()

# ==========================================
# 0. CONFIGURATII EXPERIMENTE (DEEP FINE-TUNING)
# ==========================================
EXPERIMENTE = [
    # --- Partea 1: Arhitecturi diferite evaluate pe setul APTOS ---
    {
        "nume": "Exp1_DenseNet121_DeepFT_Aptos",
        "model": "densenet121",
        "train_datasets": ["APTOS"], 
        "test_datasets": ["APTOS"], 
        "epoci": 20, "aug": True, "fine_tune_deep": True, "use_weighted_loss": False
    },
    {
        "nume": "Exp2_EfficientNetB0_DeepFT_Aptos",
        "model": "efficientnet_b0",
        "train_datasets": ["APTOS"], 
        "test_datasets": ["APTOS"], 
        "epoci": 20, "aug": True, "fine_tune_deep": True, "use_weighted_loss": False
    },

    # --- Partea 2: Evaluare model de baza (ResNet50) pe seturi de date eterogene ---
    # Setul IDRID: Volum redus de date, predispozitie la overfitting
    {
        "nume": "Exp3_ResNet50_DeepFT_IDRID",
        "model": "resnet50",
        "train_datasets": ["IDRID"], 
        "test_datasets": ["IDRID"], 
        "epoci": 25, 
        "aug": True, "fine_tune_deep": True, "use_weighted_loss": False
    },
    # Setul MESSIDOR: Volum mediu de date, echipament de achizitie diferit
    {
        "nume": "Exp4_ResNet50_DeepFT_MESSIDOR",
        "model": "resnet50",
        "train_datasets": ["MESSIDOR"], 
        "test_datasets": ["MESSIDOR"], 
        "epoci": 20, "aug": True, "fine_tune_deep": True, "use_weighted_loss": False
    },
    # Setul EYEPACS: Volum extins de date, variabilitate mare
    {
        "nume": "Exp5_ResNet50_DeepFT_EYEPACS",
        "model": "resnet50",
        "train_datasets": ["EYEPACS"], 
        "test_datasets": ["EYEPACS"], 
        "epoci": 10, 
        "aug": False, 
        "fine_tune_deep": True, "use_weighted_loss": False
    },
    {
        "nume": "Exp6_ResNet50_DeepFT_EYEPACS_Aug",
        "model": "resnet50",
        "train_datasets": ["EYEPACS"], 
        "test_datasets": ["EYEPACS"], 
        "epoci": 10, 
        "aug": True, 
        "fine_tune_deep": True, "use_weighted_loss": False
    }
]

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device curent: {device} | Numar GPU-uri detectate: {torch.cuda.device_count()}")

# ==========================================
# 1. CONFIGURARE CAI DIRECTOARE
# ==========================================
def get_dataset_paths(dataset_name):
    """ Returneaza caile catre fisierele CSV si directoarele cu imagini aferente fiecarui set. """
    if dataset_name == "APTOS":
        base = "/home/marian-s/Disertatie/Dataset_APTOS_2019"
        return {"csv": f"{base}/train_1.csv", "dir": f"{base}/train_images/train_images"}
        
    elif dataset_name == "EYEPACS":
        base = "/home/marian-s/Disertatie/Dataset_KaggleEyePACS"
        return {"csv": f"{base}/labels/traintestLabels15_trainLabels19.csv", "dir": f"{base}/resized_traintest15_train19"}
        
    elif dataset_name == "IDRID":
        base = "/home/marian-s/Disertatie/Dataset_IDRID"
        return {"csv": f"{base}/idrid_labels.csv", "dir": f"{base}/Imagenes/Imagenes"}
        
    elif dataset_name == "MESSIDOR":
        base = "/home/marian-s/Disertatie/Dataset_Messidor_2"
        return {"csv": f"{base}/messidor_data.csv", "dir": f"{base}/messidor-2/messidor-2/preprocess"}
        
    else:
        raise ValueError(f"Setul de date specificat nu este recunoscut: {dataset_name}")

# ==========================================
# 2. DEFINIRE CLASA DATASET
# ==========================================
class RetinopathyDataset(Dataset):
    def __init__(self, dataset_names, transform=None):
        self.transform = transform
        self.samples = [] 
        
        for ds_name in dataset_names:
            paths = get_dataset_paths(ds_name)
            df = pd.read_csv(paths["csv"])
            
            for idx in range(len(df)):
                img_name = str(df.iloc[idx, 0])
                
                # Verificare si corectie extensii fisiere
                if not img_name.lower().endswith(('.jpg', '.jpeg', '.png')):
                    if ds_name == "EYEPACS": 
                        img_name += '.jpeg'
                    elif ds_name == "APTOS": 
                        img_name += '.png'
                    else: 
                        img_name += '.jpg'
                
                full_path = os.path.join(paths["dir"], img_name)
                label_binar = 0 if int(df.iloc[idx, 1]) == 0 else 1
                self.samples.append({'path': full_path, 'label': label_binar})

            del df
            gc.collect() 
        
        print(f"  -> Set incarcat ({'+'.join(dataset_names)}): {len(self.samples)} imagini.")

    def __len__(self): return len(self.samples)

    def __getitem__(self, idx):
        path = self.samples[idx]['path']
        
        # Fallback in cazul in care fisierul nu este gasit sub extensia implicita
        if not os.path.exists(path):
            baza = os.path.splitext(path)[0] 
            variante_extensii = ['.png', '.jpeg', '.jpg', '.JPG', '.PNG', '.JPEG']
            
            for ext in variante_extensii:
                if os.path.exists(baza + ext):
                    path = baza + ext
                    break

        image = Image.open(path).convert('RGB')
        label = torch.tensor(self.samples[idx]['label'], dtype=torch.float32)
        if self.transform: image = self.transform(image)
        return image, label

# ==========================================
# 3. INITIALIZARE MODELE
# ==========================================
def build_model(model_name, fine_tune_deep=False):
    if model_name == "resnet50":
        model = models.resnet50(weights=models.ResNet50_Weights.IMAGENET1K_V1)
        for param in model.parameters(): param.requires_grad = False
        
        if fine_tune_deep:
            print("  - Deep Fine-Tuning: Activare gradienti pentru 'layer4' (ResNet50)")
            for param in model.layer4.parameters(): param.requires_grad = True
                
        num_ftrs = model.fc.in_features
        model.fc = nn.Sequential(nn.Dropout(0.5), nn.Linear(num_ftrs, 1))
        return model

    elif model_name == "densenet121":
        model = models.densenet121(weights=models.DenseNet121_Weights.IMAGENET1K_V1)
        for param in model.parameters(): param.requires_grad = False
        
        if fine_tune_deep:
            print("  - Deep Fine-Tuning: Activare gradienti pentru 'denseblock4' si 'norm5' (DenseNet121)")
            for param in model.features.denseblock4.parameters(): param.requires_grad = True
            for param in model.features.norm5.parameters(): param.requires_grad = True
                
        num_ftrs = model.classifier.in_features
        model.classifier = nn.Sequential(nn.Dropout(0.5), nn.Linear(num_ftrs, 1))
        return model

    elif model_name == "efficientnet_b0":
        model = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.IMAGENET1K_V1)
        for param in model.parameters(): param.requires_grad = False
        
        if fine_tune_deep:
            print("  - Deep Fine-Tuning: Activare gradienti pentru ultimele blocuri convolutionale (EfficientNet-B0)")
            for param in model.features[6].parameters(): param.requires_grad = True
            for param in model.features[7].parameters(): param.requires_grad = True
            for param in model.features[8].parameters(): param.requires_grad = True
                
        num_ftrs = model.classifier[1].in_features
        model.classifier = nn.Sequential(nn.Dropout(p=0.5, inplace=True), nn.Linear(num_ftrs, 1))
        return model

# ==========================================
# 4. EXECUTIA EXPERIMENTELOR
# ==========================================
for idx_exp, exp in enumerate(EXPERIMENTE):
    print(f"\n{'-'*65}")
    print(f"Rulare Experiment {idx_exp+1}: {exp['nume']}")
    print(f"{'-'*65}")
    
    # 4.1 Definire pipeline de transformari
    if exp["aug"]:
        transforms_pipeline = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.RandomHorizontalFlip(), transforms.RandomVerticalFlip(),
            transforms.RandomRotation(15), transforms.ColorJitter(brightness=0.2, contrast=0.2),
            transforms.ToTensor(), transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])
    else:
        transforms_pipeline = transforms.Compose([
            transforms.Resize((224, 224)), transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])
    
    # 4.2 Initializare DataLoadere
    print("  Pregatire set de antrenare...")
    train_ds = RetinopathyDataset(exp["train_datasets"], transform=transforms_pipeline)
    print("  Pregatire set de validare...")
    test_ds = RetinopathyDataset(exp["test_datasets"], transform=transforms_pipeline)
    
    train_loader = DataLoader(train_ds, batch_size=32, shuffle=True, num_workers=8, pin_memory=True)
    test_loader = DataLoader(test_ds, batch_size=32, shuffle=False, num_workers=8, pin_memory=True)
    
    # 4.3 Initializare Model si Optimizator
    model = build_model(exp["model"], exp["fine_tune_deep"])
    if torch.cuda.device_count() > 1: model = nn.DataParallel(model)
    model = model.to(device)
    
    params_to_train = [p for p in model.parameters() if p.requires_grad]
    optimizer = optim.Adam(params_to_train, lr=0.001)
    
    # 4.4 Configurare functie de Loss
    if exp.get("use_weighted_loss", False):
        pondere = torch.tensor([exp["pos_weight_val"]]).to(device)
        criterion = nn.BCEWithLogitsLoss(pos_weight=pondere)
        print(f"  - Weighted Loss activat. Pondere clasa pozitiva: {exp['pos_weight_val']}")
    else:
        criterion = nn.BCEWithLogitsLoss()
    
    # 4.5 Bucla de antrenare
    istoric = {'train_loss': [], 'test_loss': [], 'test_f1': [], 'test_acc': []}
    best_f1_score = 0.0
    
    for epoch in range(exp["epoci"]):
        start_time = time.time()
        
        # Faza de antrenare
        model.train()
        running_train_loss = 0.0
        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device).unsqueeze(1)
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            running_train_loss += loss.item()
            
        avg_train_loss = running_train_loss / len(train_loader)
        
        # Faza de validare
        model.eval()
        running_test_loss = 0.0
        all_preds, all_labels = [], []
        
        with torch.no_grad():
            for images, labels in test_loader:
                images, labels = images.to(device), labels.to(device).unsqueeze(1)
                outputs = model(images)
                loss = criterion(outputs, labels)
                running_test_loss += loss.item()
                
                probs = torch.sigmoid(outputs)
                all_preds.extend((probs >= 0.5).float().cpu().numpy())
                all_labels.extend(labels.cpu().numpy())
                
        avg_test_loss = running_test_loss / len(test_loader)
        epoch_f1 = f1_score(all_labels, all_preds, zero_division=0)
        epoch_acc = accuracy_score(all_labels, all_preds)
        
        istoric['train_loss'].append(avg_train_loss)
        istoric['test_loss'].append(avg_test_loss)
        istoric['test_f1'].append(epoch_f1)
        istoric['test_acc'].append(epoch_acc)
        
        m, s = divmod(time.time() - start_time, 60)
        print(f"  Epoca [{epoch+1}/{exp['epoci']}] | Train Loss: {avg_train_loss:.4f} | Val Loss: {avg_test_loss:.4f} | F1: {epoch_f1:.4f} | Acc: {epoch_acc*100:.1f}% | Timp: {int(m)}m {int(s)}s", end="")
        
        if epoch_f1 > best_f1_score:
            best_f1_score = epoch_f1
            torch.save(model.module.state_dict() if isinstance(model, nn.DataParallel) else model.state_dict(), f"{exp['nume']}_best.pth")
            print(" -> Model salvat (imbunatatire F1).")
        else:
            print()

        del all_preds, all_labels
        gc.collect()
            
    # 4.6 Generare si salvare grafice
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5))
    ax1.plot(istoric['train_loss'], label='Train Loss', color='blue')
    ax1.plot(istoric['test_loss'], label='Val Loss', color='red', linestyle='--')
    ax1.set_title(f"Evolutie Loss: {exp['nume']}")
    ax1.legend(); ax1.grid(True, alpha=0.3)
    
    ax2.plot(istoric['test_acc'], label='Accuracy', color='green')
    ax2.plot(istoric['test_f1'], label='F1-Score', color='purple', linestyle='-.')
    ax2.set_title(f"Evolutie Metrici: {exp['nume']}")
    ax2.legend(); ax2.grid(True, alpha=0.3)
    
    plt.savefig(f"grafic_{exp['nume']}.png", dpi=300)
    plt.close()
    
    # 4.7 Eliberare resurse la finalul experimentului
    print("  Finalizare experiment. Eliberare VRAM...")
    del model, optimizer, train_loader, test_loader
    torch.cuda.empty_cache()
    gc.collect()
    time.sleep(2)

print("\nExecutia tuturor experimentelor a fost finalizata cu succes.")