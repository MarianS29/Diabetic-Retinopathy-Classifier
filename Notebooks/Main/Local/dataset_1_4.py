import os
import torch
from torchvision import datasets
from torch.utils.data import Dataset

class MultiClassRetinopathyDataset(Dataset):
    def __init__(self, root_dir, transform=None):
        self.raw_dataset = datasets.ImageFolder(root_dir)
        self.transform = transform
        
        # FIX CRITIC: Loss-ul multiclasă (CrossEntropyLoss) necesită ca etichetele 
        # să fie exact în intervalul [0, num_classes - 1].
        # Deci stadiile noastre 1, 2, 3 și 4 devin clasele 0, 1, 2 și 3.
        self.class_mapping = {
            'stadiul_1': 0,
            'stadiul_2': 1,
            'stadiul_3': 2,
            'stadiul_4': 3
        }
        self.classes = ['stadiul_1', 'stadiul_2', 'stadiul_3', 'stadiul_4']
        self.class_to_idx = self.class_mapping
        self.targets = [
            self.class_mapping[self.raw_dataset.classes[class_idx]]
            for _, class_idx in self.raw_dataset.samples
        ]

    def __len__(self):
        return len(self.raw_dataset)

    def __getitem__(self, idx):
        img, original_class_idx = self.raw_dataset[idx]
        folder_name = self.raw_dataset.classes[original_class_idx]
        
        # Obținem eticheta corectată (0, 1, 2 sau 3)
        label = self.class_mapping[folder_name]
        
        if self.transform:
            img = self.transform(img)
            
        # Spre deosebire de Binar (float32), aici returnăm eticheta ca număr întreg (long)
        return img, torch.tensor(label, dtype=torch.long)
