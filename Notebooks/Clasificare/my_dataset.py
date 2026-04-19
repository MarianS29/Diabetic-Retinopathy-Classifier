import os
import torch
import pandas as pd
from PIL import Image
from torch.utils.data import Dataset
import torchvision.transforms as T

class DRDataset(Dataset):
    def __init__(self, root_dir, dataset_name, split='train', image_size=224):
        """
        Dataset pentru Clasificare Multi-Clasă (Stadiile 0, 1, 2, 3, 4)
        """
        self.root_dir = root_dir
        self.dataset_name = dataset_name.lower()
        self.split = split.lower()
        self.image_size = image_size
        
        # Dicționar simplificat: DOAR Train și Test
        paths_config = {
            'aptos': {
                'train': {'csv': 'datasets/aptos2019/versions/3/train_1.csv', 
                          'img': 'datasets/aptos2019/versions/3/train_images/train_images'},
                'test':  {'csv': 'datasets/aptos2019/versions/3/test.csv',  
                          'img': 'datasets/aptos2019/versions/3/test_images/test_images'}
            },
            'eyepacs': {
                'train': {'csv': 'datasets/resized-2015-2019-diabetic-retinopathy-detection/versions/4/labels/trainLabels15.csv', 
                          'img': 'datasets/resized-2015-2019-diabetic-retinopathy-detection/versions/4/resized_traintest15_train19'},
                'test':  {'csv': 'datasets/resized-2015-2019-diabetic-retinopathy-detection/versions/4/labels/testLabels15.csv',  
                          'img': 'datasets/resized-2015-2019-diabetic-retinopathy-detection/versions/4/resized_test19'}
            },
            'idrid': {
                'train': {'csv': 'datasets/idrid-dataset/versions/1/idrid_labels.csv', 
                          'img': 'datasets/idrid-dataset/versions/1/Imagenes/Imagenes'},
                'test':  {'csv': 'datasets/idrid-dataset/versions/1/idrid_labels.csv', 
                          'img': 'datasets/idrid-dataset/versions/1/Imagenes/Imagenes'}
            },
            'messidor2': {
                'train': {'csv': 'datasets/messidor2preprocess/versions/2/messidor_data.csv', 
                          'img': 'datasets/messidor2preprocess/versions/2/messidor-2/messidor-2/preprocess'},
                'test':  {'csv': 'datasets/messidor2preprocess/versions/2/messidor_data.csv', 
                          'img': 'datasets/messidor2preprocess/versions/2/messidor-2/messidor-2/preprocess'} 
            }
        }

        config = paths_config[self.dataset_name][self.split]
        self.csv_path = os.path.join(self.root_dir, config['csv'])
        self.img_dir = os.path.join(self.root_dir, config['img'])
        self.dataframe = pd.read_csv(self.csv_path)

        ext_map = {'aptos': '.png', 'eyepacs': '.jpeg', 'idrid': '.jpg', 'messidor2': '.jpg'}
        self.default_ext = ext_map[self.dataset_name]

        # Transformări identice
        if self.split == 'train':
            self.transform = T.Compose([
                T.Resize((self.image_size, self.image_size)),
                T.RandomHorizontalFlip(),
                T.RandomVerticalFlip(),
                T.RandomRotation(15),
                T.ColorJitter(brightness=0.1, contrast=0.1),
                T.ToTensor(),
                T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
            ])
        else:
            self.transform = T.Compose([
                T.Resize((self.image_size, self.image_size)),
                T.ToTensor(),
                T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
            ])

    def __len__(self):
        return len(self.dataframe)

    def __getitem__(self, idx):
        img_name = str(self.dataframe.iloc[idx, 0])
        if not img_name.endswith(('.png', '.jpg', '.jpeg')):
            img_name += self.default_ext
            
        img_path = os.path.join(self.img_dir, img_name)
        try:
            image = Image.open(img_path).convert('RGB')
        except:
            image = Image.new('RGB', (self.image_size, self.image_size), (0, 0, 0))

        if self.transform:
            image = self.transform(image)
            
        # =========================================================
        # --- DIFERENȚA PENTRU CLASIFICARE (Multi-clasă) ---
        # =========================================================
        label = int(self.dataframe.iloc[idx, 1])
        
        # Păstrăm label-ul brut (ex: 3) și îl facem torch.long (pentru CrossEntropy)
        # NU îl punem în listă [label], îl lăsăm simplu scalar
        label_tensor = torch.tensor(label, dtype=torch.long)
        
        return image, label_tensor