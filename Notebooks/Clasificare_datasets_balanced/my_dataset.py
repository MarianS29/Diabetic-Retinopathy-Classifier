import os

import torch
from PIL import Image
from torch.utils.data import ConcatDataset, Dataset
import torchvision.transforms as T


IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg')

EXPERIMENTS = {
    'balanced_to_balanced': ('balanced', 'balanced'),
    'balanced_aptos_to_balanced_aptos': ('combined', 'combined'),
    'balanced_aptos_to_aptos': ('combined', 'aptos'),
    'balanced_aptos_to_balanced': ('combined', 'balanced'),
    'aptos_to_balanced': ('aptos', 'balanced'),
    'aptos_to_balanced_aptos': ('aptos', 'combined'),
    'balanced_to_aptos': ('balanced', 'aptos')
}


def default_transform(split='train', image_size=224):
    split = split.lower()
    if split == 'train':
        return T.Compose([
            T.Resize((image_size, image_size)),
            T.RandomHorizontalFlip(p=0.5),
            T.RandomVerticalFlip(p=0.5),
            T.RandomRotation(degrees=15),
            T.ColorJitter(brightness=0.1, contrast=0.1),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

    return T.Compose([
        T.Resize((image_size, image_size)),
        T.ToTensor(),
        T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])


class BalancedDRDataset(Dataset):
    def __init__(self, root_dir, split='train', image_size=224, transform=None):
        self.root_dir = root_dir
        self.split = split.lower()
        self.image_size = image_size
        self.split_dir = os.path.join(self.root_dir, self.split)

        if not os.path.exists(self.split_dir):
            raise FileNotFoundError(f"[Eroare] Folderul nu exista: {self.split_dir}")

        self.image_paths = []
        self.labels = []

        for class_id in range(5):
            class_folder = os.path.join(self.split_dir, str(class_id))
            if not os.path.exists(class_folder):
                continue
            for img_name in os.listdir(class_folder):
                if img_name.lower().endswith(IMAGE_EXTENSIONS):
                    self.image_paths.append(os.path.join(class_folder, img_name))
                    self.labels.append(class_id)

        self.transform = transform or default_transform(self.split, self.image_size)

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        img_path = self.image_paths[idx]
        label = self.labels[idx]

        try:
            image = Image.open(img_path).convert('RGB')
        except Exception:
            image = Image.new('RGB', (self.image_size, self.image_size), (0, 0, 0))

        if self.transform:
            image = self.transform(image)

        return image, torch.tensor(label, dtype=torch.long)


class AptosDRDataset(BalancedDRDataset):
    """APTOS Ben Graham este deja preprocesat si organizat pe foldere train/val/test/0..4."""
    pass


def make_dataset(
    source,
    split,
    image_size,
    balanced_root,
    aptos_root,
):
    source = source.lower()
    split = split.lower()

    if source == 'balanced':
        return BalancedDRDataset(balanced_root, split=split, image_size=image_size)

    if source == 'aptos':
        return AptosDRDataset(aptos_root, split=split, image_size=image_size)

    if source in ('combined', 'balanced_aptos', 'diabetic_balanced_data+aptos'):
        return ConcatDataset([
            BalancedDRDataset(balanced_root, split=split, image_size=image_size),
            AptosDRDataset(aptos_root, split=split, image_size=image_size),
        ])

    raise ValueError(f"Sursa de date necunoscuta: {source}")


def resolve_experiment(experiment=None, train_source=None, test_source=None):
    if experiment:
        experiment = experiment.lower()
        if experiment not in EXPERIMENTS:
            valid = ', '.join(EXPERIMENTS.keys())
            raise ValueError(f"Experiment necunoscut: {experiment}. Variante: {valid}")
        return EXPERIMENTS[experiment]

    return (train_source or 'balanced').lower(), (test_source or 'balanced').lower()
