import os
from cv2 import transform
import torch
from PIL import Image
from torch.utils.data import Dataset
import torchvision.transforms as T

class BalancedDRDataset(Dataset):
    def __init__(self, root_dir, split='train', image_size=224, transform=None):
        self.root_dir = root_dir
        self.split = split.lower()
        self.image_size = image_size
        self.split_dir = os.path.join(self.root_dir, self.split)
        
        if not os.path.exists(self.split_dir):
            raise FileNotFoundError(f"[Eroare] Folderul nu există: {self.split_dir}")

        self.image_paths = []
        self.labels = []
        
        for class_id in range(5):
            class_folder = os.path.join(self.split_dir, str(class_id))
            if not os.path.exists(class_folder):
                continue
            for img_name in os.listdir(class_folder):
                if img_name.lower().endswith(('.png', '.jpg', '.jpeg')):
                    self.image_paths.append(os.path.join(class_folder, img_name))
                    self.labels.append(class_id)

        if transform is None:
            # Dacă suntem în faza de TRAIN, aplicăm Data Augmentation
            if self.split == 'train':
                self.transform = T.Compose([
                    T.Resize((self.image_size, self.image_size)),
                    T.RandomHorizontalFlip(p=0.5),      # Întoarce imaginea în oglindă stânga-dreapta
                    T.RandomVerticalFlip(p=0.5),        # Întoarce imaginea sus-jos (comun la ochi)
                    T.RandomRotation(degrees=15),       # Rotește ușor cu 15 grade
                    T.ColorJitter(brightness=0.1, contrast=0.1), # Schimbă puțin lumina
                    T.ToTensor(),
                    T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
                ])
            # Dacă suntem în VALID sau TEST, DOAR redimensionăm și normalizăm (nu trișăm!)
            else:
                self.transform = T.Compose([
                    T.Resize((self.image_size, self.image_size)),
                    T.ToTensor(),
                    T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
                ])
        else:
            self.transform = transform

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        img_path = self.image_paths[idx]
        label = self.labels[idx]
        try:
            image = Image.open(img_path).convert('RGB')
        except:
            image = Image.new('RGB', (self.image_size, self.image_size), (0, 0, 0))

        if self.transform:
            image = self.transform(image)
            
        return image, torch.tensor(label, dtype=torch.long)