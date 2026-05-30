import os

import torch
from PIL import Image
from torch.utils.data import ConcatDataset, Dataset
import torchvision.transforms as T


IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg')


def default_transform(split='train', image_size=224, train_augment='basic'):
    split = split.lower()
    train_augment = train_augment.lower()

    if split == 'train' and train_augment == 'basic':
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


class ImageFolderDRDataset(Dataset):
    def __init__(self, root_dir, split='train', image_size=224, transform=None, train_augment='basic'):
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

        self.transform = transform or default_transform(self.split, self.image_size, train_augment=train_augment)

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


def make_dataset(
    root_dirs,
    split,
    image_size,
    train_augment='basic',
):
    if isinstance(root_dirs, (str, os.PathLike)):
        root_dirs = [root_dirs]

    root_dirs = [str(root_dir) for root_dir in root_dirs if root_dir]
    if not root_dirs:
        raise ValueError("Trebuie sa furnizezi cel putin un root de dataset.")

    if len(root_dirs) > 1:
        return ConcatDataset([
            ImageFolderDRDataset(
                root_dir,
                split=split,
                image_size=image_size,
                train_augment=train_augment,
            )
            for root_dir in root_dirs
        ])

    return ImageFolderDRDataset(root_dirs[0], split=split, image_size=image_size, train_augment=train_augment)
