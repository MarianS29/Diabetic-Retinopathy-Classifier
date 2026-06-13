from pathlib import Path

import torch
from PIL import Image
from torch.utils.data import Dataset


class RetinopathyDataset(Dataset):
    def __init__(self, dataframe, transform=None, is_stage2=False):
        self.dataframe = dataframe.reset_index(drop=True)
        self.transform = transform
        self.is_stage2 = is_stage2

    def __len__(self):
        return len(self.dataframe)

    def __getitem__(self, idx):
        row = self.dataframe.iloc[idx]
        image_path = Path(row["file_path"])
        image = Image.open(image_path).convert("RGB")

        if self.transform:
            image = self.transform(image)

        if self.is_stage2:
            label = row["level_stage2"]
            return image, torch.tensor(label, dtype=torch.long)

        label = row["is_diseased"]
        return image, torch.tensor(label, dtype=torch.float32)
