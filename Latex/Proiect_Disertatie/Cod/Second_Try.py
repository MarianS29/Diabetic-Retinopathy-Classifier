import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Incarcarea setului de date de antrenare APTOS
df = pd.read_csv('Datasets/Dataset_APTOS_2019/train_1.csv')

# Vizualizarea distributiei claselor
plt.figure(figsize=(8, 5))
sns.countplot(x='diagnosis', data=df)
plt.title('Distributia claselor de Retinopatie Diabetica')
plt.xlabel('Clasa (0=Fara, 1=Usor, 2=Moderat, 3=Sever, 4=Proliferativ)')
plt.ylabel('Numar de imagini')
plt.show()

# Afisarea numarului de imagini si a distributiei pe clase
print("Numar total de imagini:", len(df))
print("Numar de imagini per clasa:")
print(df['diagnosis'].value_counts())

# Afisarea unei imagini reprezentative pentru fiecare clasa
import matplotlib.image as mpimg
for diagnosis in df['diagnosis'].unique():
    img_path = df[df['diagnosis'] == diagnosis]['id_code'].iloc[0] + '.png'
    img = mpimg.imread('Datasets/Dataset_APTOS_2019/train_images/train_images/' + img_path)
    plt.imshow(img)
    plt.title(f'Clasa: {diagnosis}')
    plt.axis('off')
    plt.show()

import os
import cv2
import torch
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from PIL import Image

class DiabeticRetinopathyDataset(Dataset):
    def __init__(self, dataframe, image_dir, transform=None):
        self.dataframe = dataframe
        self.image_dir = image_dir
        self.transform = transform

    def __len__(self):
        return len(self.dataframe)

    def __getitem__(self, idx):
        # Extragerea numelui imaginii si a etichetei
        img_name = str(self.dataframe.iloc[idx, 0]) + '.png'
        img_path = os.path.join(self.image_dir, img_name)
        
        # Incarcare imagine in format RGB
        image = Image.open(img_path).convert('RGB')
        label = self.dataframe.iloc[idx, 1]

        if self.transform:
            image = self.transform(image)

        return image, label

# Transformari pentru setul de antrenare (Data Augmentation)
train_transforms = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.RandomHorizontalFlip(),
    transforms.RandomVerticalFlip(),
    transforms.RandomRotation(15),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], # Standard ImageNet
                         std=[0.229, 0.224, 0.225])
])

# Transformari pentru seturile de validare si testare
eval_transforms = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225])
])

# Citirea fisierelor CSV
train_df = pd.read_csv('Datasets/Dataset_APTOS_2019/train_1.csv')
val_df = pd.read_csv('Datasets/Dataset_APTOS_2019/valid.csv')
test_df = pd.read_csv('Datasets/Dataset_APTOS_2019/test.csv')

# Initializarea obiectelor de tip Dataset
train_dataset = DiabeticRetinopathyDataset(train_df, 'Datasets/Dataset_APTOS_2019/train_images/train_images', transform=train_transforms)
val_dataset = DiabeticRetinopathyDataset(val_df, 'Datasets/Dataset_APTOS_2019/val_images/val_images', transform=eval_transforms)
test_dataset = DiabeticRetinopathyDataset(test_df, 'Datasets/Dataset_APTOS_2019/test_images/test_images', transform=eval_transforms)

# Initializarea obiectelor de tip DataLoader
train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True, num_workers=8)
val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False, num_workers=8)
test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False, num_workers=8)

print(f"Set de antrenare: {len(train_dataset)} imagini | Set de validare: {len(val_dataset)} imagini | Set de testare: {len(test_dataset)} imagini")

import torchvision.models as models
import torch.nn as nn

def create_model(num_classes=5):
    # Incarcarea arhitecturii ResNet50 pre-antrenata pe ImageNet
    model = models.resnet50(weights=models.ResNet50_Weights.DEFAULT)
    
    # Inghetarea parametrilor straturilor convolutionale de baza
    for param in model.parameters():
        param.requires_grad = False
        
    # Modificarea stratului Fully Connected (FC) pentru clasificare in 5 clase
    num_ftrs = model.fc.in_features
    model.fc = nn.Sequential(
        nn.Linear(num_ftrs, 512),
        nn.ReLU(),
        nn.Dropout(0.4),
        nn.Linear(512, num_classes)
    )
    
    # Activarea gradientilor pentru noul strat FC
    for param in model.fc.parameters():
        param.requires_grad = True
        
    return model

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = create_model().to(device)
print(f"Dispozitiv de rulare configurat: {device}")

# Importuri aditionale pentru bucla de antrenare
from sklearn.model_selection import train_test_split
import torch.optim as optim
from tqdm import tqdm

# Definirea functiei de cost si a optimizatorului
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.fc.parameters(), lr=0.0001)

EPOCHS = 100
best_val_acc = 0.0
train_losses = []
val_losses = []
train_accuracies = []
val_accuracies = []

# BUCLA DE ANTRENARE SI VALIDARE
for epoch in range(EPOCHS):
    # --- Faza de Antrenare ---
    model.train()
    running_loss, correct, total = 0.0, 0, 0
    
    print(f"\nEpoca {epoch+1}/{EPOCHS}")
    for images, labels in tqdm(train_loader, desc="Training"):
        images, labels = images.to(device), labels.to(device)
        
        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
        
        running_loss += loss.item()
        _, predicted = torch.max(outputs.data, 1)
        total += labels.size(0)
        correct += (predicted == labels).sum().item()
        
    train_acc = 100 * correct / total
    train_accuracies.append(train_acc)
    train_loss = running_loss / len(train_loader)
    train_losses.append(train_loss)
    
    # --- Faza de Validare ---
    model.eval()
    val_loss, val_correct, val_total = 0.0, 0, 0
    
    with torch.no_grad():
        for images, labels in val_loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)
            loss = criterion(outputs, labels)
            
            val_loss += loss.item()
            _, predicted = torch.max(outputs.data, 1)
            val_total += labels.size(0)
            val_correct += (predicted == labels).sum().item()
            
    val_acc = 100 * val_correct / val_total
    val_loss = val_loss / len(val_loader)
    
    # Adaugare in lista a valorilor de validare o singura data pe epoca
    val_accuracies.append(val_acc)
    val_losses.append(val_loss)
    
    print(f"Train Loss: {train_loss:.4f} | Train Acc: {train_acc:.2f}%")
    print(f"Val Loss: {val_loss:.4f} | Val Acc: {val_acc:.2f}%")
    
    # Salvarea modelului optim pe baza acuratetii de validare
    if val_acc > best_val_acc:
        best_val_acc = val_acc
        torch.save(model.state_dict(), 'best_dr_model.pth')
        print("-> Model salvat (imbunatatire performanta validare).")


from sklearn.metrics import confusion_matrix, classification_report, cohen_kappa_score
import numpy as np

print("\n--- FAZA DE TESTARE ---")

# Incarcarea ponderilor modelului optim
model.load_state_dict(torch.load('best_dr_model.pth'))
model.eval()

test_correct = 0
test_total = 0
test_preds = []
test_labels = []

with torch.no_grad():
    for images, labels in tqdm(test_loader, desc="Testing"):
        images, labels = images.to(device), labels.to(device)
        outputs = model(images)
        
        _, predicted = torch.max(outputs.data, 1)
        
        test_total += labels.size(0)
        test_correct += (predicted == labels).sum().item()
        
        test_preds.extend(predicted.cpu().numpy())
        test_labels.extend(labels.cpu().numpy())

test_acc = 100 * test_correct / test_total
print(f"\nAcuratete finala pe setul de testare: {test_acc:.2f}%\n")

# Calculul metricii Quadratic Weighted Kappa (QWK)
qwk = cohen_kappa_score(test_labels, test_preds, weights='quadratic')
print(f"Scor Quadratic Weighted Kappa (QWK): {qwk:.4f}")
# Un scor > 0.7 indica un acord bun in aplicatiile de imagistica medicala

# Generarea matricei de confuzie
cm = confusion_matrix(test_labels, test_preds)
plt.figure(figsize=(8,6))
sns.heatmap(cm, annot=True, fmt='d', cmap='Oranges', 
            xticklabels=['Fara', 'Usor', 'Moderat', 'Sever', 'Proliferativ'], 
            yticklabels=['Fara', 'Usor', 'Moderat', 'Sever', 'Proliferativ'])
plt.xlabel('Predictie Model')
plt.ylabel('Eticheta Reala')
plt.title(f'Matrice de Confuzie - Set de Testare (Acuratete: {test_acc:.2f}%)')
plt.show()

# Generarea raportului de clasificare (Precision, Recall, F1-Score)
print("\nRaport de clasificare:")
print(classification_report(test_labels, test_preds, target_names=['Fara (0)', 'Usor (1)', 'Moderat (2)', 'Sever (3)', 'Proliferativ (4)']))

# Generarea graficelor pentru curbele de invatare
plt.figure(figsize=(12, 5))
plt.subplot(1, 2, 1)
plt.plot(train_losses, label='Train Loss')
plt.plot(val_losses, label='Validation Loss')
plt.title('Evolutie Loss')
plt.xlabel('Epoca')
plt.ylabel('Loss')
plt.legend()

plt.subplot(1, 2, 2)
plt.plot(train_accuracies, label='Train Accuracy')
plt.plot(val_accuracies, label='Validation Accuracy')
plt.title('Evolutie Acuratete')
plt.xlabel('Epoca')
plt.ylabel('Acuratete (%)')
plt.legend()
plt.show()