import os
import torch
import pandas as pd
from PIL import Image
from torch.utils.data import Dataset
import torchvision.transforms as T

class DRDatasetBenGraham(Dataset):
    def __init__(self, root_dir, dataset_name, split='train', image_size=224):
        """
        Dataset OPTIMIZAT: Citește imaginile gata preprocesate, augmentate 
        și echilibrate direct din folderul 'datasets_bengraham'.
        """
        self.dataset_name = dataset_name.lower()
        self.split = split.lower()
        self.image_size = image_size
        
        # Noua structură simplificată: datasets_bengraham/nume/train/
        self.base_dir = os.path.join(root_dir, 'datasets_bengraham', self.dataset_name, self.split)
        self.img_dir = os.path.join(self.base_dir, 'images')
        
        # Căutăm automat fișierul CSV potrivit generat de scriptul nostru
        csv_files = [f for f in os.listdir(self.base_dir) if f.endswith('.csv')]
        if not csv_files:
            raise FileNotFoundError(f"[Eroare] Nu am găsit niciun .csv în {self.base_dir}")
            
        # Dacă suntem la train, căutăm fișierul '_balanced.csv'
        # Dacă suntem la test, căutăm fișierul '_processed.csv'
        target_csv = [f for f in csv_files if ('balanced' in f if self.split == 'train' else 'processed' in f)]
        
        if target_csv:
            self.csv_path = os.path.join(self.base_dir, target_csv[0])
        else:
            # Fallback dacă are alt nume
            self.csv_path = os.path.join(self.base_dir, csv_files[0])
            
        self.dataframe = pd.read_csv(self.csv_path)

        # ==========================================
        # TRANSFORMĂRI (ULTRA-UȘOARE)
        # ==========================================
        # Am scos RandomRotation și RandomFlip pentru că am făcut asta FIZIC pe hard disk.
        self.transform = T.Compose([
            T.Resize((self.image_size, self.image_size)), # Siguranță în caz că au altă mărime
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])

    def __len__(self):
        return len(self.dataframe)

    def __getitem__(self, idx):
        # 1. Numele imaginii din CSV
        img_name = str(self.dataframe.iloc[idx, 0])
        
        # Pentru că scriptul de offline augmentare a salvat totul ca .jpg
        if not img_name.endswith('.jpg'):
            img_name = os.path.splitext(img_name)[0] + '.jpg'
            
        img_path = os.path.join(self.img_dir, img_name)
        
        # 2. Încărcarea imaginii cu PIL (mult mai rapid decât cv2 pentru Tensors)
        try:
            image = Image.open(img_path).convert('RGB')
        except Exception as e:
            # Fallback de siguranță dacă o imagine e coruptă
            image = Image.new('RGB', (self.image_size, self.image_size), (0, 0, 0))

        # 3. Aplicăm Tensor și Normalizarea
        if self.transform:
            image = self.transform(image)
            
        # 4. Eticheta pentru Clasificare Multi-Clasă (vrea torch.long)
        # Atenție: folosim indexul corect de coloană. În noul nostru CSV, clasa este a doua coloană (index 1).
        label = int(self.dataframe.iloc[idx, 1])
        label_tensor = torch.tensor(label, dtype=torch.long)
        
        return image, label_tensor