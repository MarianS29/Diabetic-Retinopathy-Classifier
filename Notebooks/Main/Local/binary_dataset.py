import os
import torch
from torchvision import datasets
from torch.utils.data import Dataset

class BinaryRetinopathyDataset(Dataset):
    def __init__(self, root_dir, transform=None):
        self.raw_dataset = datasets.ImageFolder(root_dir)
        self.transform = transform
        
        # Forțăm harta logică: sanatos -> 0.0, bolnav -> 1.0
        self.class_mapping = {'sanatos': 0.0, 'bolnav': 1.0}

    def __len__(self):
        return len(self.raw_dataset)

    def __getitem__(self, idx):
        img, original_class_idx = self.raw_dataset[idx]
        folder_name = self.raw_dataset.classes[original_class_idx]
        
        label = self.class_mapping[folder_name]
        
        if self.transform:
            img = self.transform(img)
            
        return img, torch.tensor(label, dtype=torch.float32)