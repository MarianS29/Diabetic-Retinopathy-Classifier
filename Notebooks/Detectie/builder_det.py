from pyexpat import model

import torch
import torch.nn as nn
import torchvision.models as models
import timm
import torch.optim as optim

class InceptionWrapper(nn.Module):
    """
    Carcasă de protecție pentru Inception-v3 (Evită eroarea cu aux_logits).
    """
    def __init__(self, num_classes=1, pretrained=True):
        super().__init__()
        weights = models.Inception_V3_Weights.DEFAULT if pretrained else None
        self.model = models.inception_v3(weights=weights)
        
        in_features = self.model.fc.in_features
        self.model.fc = nn.Linear(in_features, num_classes)
        
    def forward(self, x):
        outputs = self.model(x)
        if self.training:
            return outputs[0]
        return outputs

def get_model(model_name, num_classes=1, pretrained=True):
    """
    Fabrica de modele pentru Clasificare Binară.
    Toate modelele sunt ÎNGHEȚATE (Transfer Learning) și au un strat final de Dropout(0.5).
    """
    model_name = model_name.lower()

    if model_name == 'resnet34':
        weights = models.ResNet34_Weights.DEFAULT if pretrained else None
        model = models.resnet34(weights=weights)
        for param in model.parameters(): param.requires_grad = False
        num_ftrs = model.fc.in_features
        model.fc = nn.Sequential(nn.Dropout(0.5), nn.Linear(num_ftrs, num_classes))

    elif model_name == 'resnet50':
        weights = models.ResNet50_Weights.DEFAULT if pretrained else None
        model = models.resnet50(weights=weights)
        for param in model.parameters(): param.requires_grad = False
        num_ftrs = model.fc.in_features
        model.fc = nn.Sequential(nn.Dropout(0.5), nn.Linear(num_ftrs, num_classes))

    elif model_name == 'efficientnet_b0':
        weights = models.EfficientNet_B0_Weights.DEFAULT if pretrained else None
        model = models.efficientnet_b0(weights=weights)
        in_features = model.classifier[1].in_features
        model.classifier[1] = nn.Linear(in_features, num_classes)

    elif model_name == 'efficientnet_b3':
        weights = models.EfficientNet_B3_Weights.DEFAULT if pretrained else None
        model = models.efficientnet_b3(weights=weights)
        in_features = model.classifier[1].in_features
        model.classifier[1] = nn.Linear(in_features, num_classes)

    elif model_name == 'densenet121':
        weights = models.DenseNet121_Weights.DEFAULT if pretrained else None
        model = models.densenet121(weights=weights)
        in_features = model.classifier.in_features
        model.classifier = nn.Linear(in_features, num_classes)

    elif model_name == 'vgg16':
        weights = models.VGG16_Weights.DEFAULT if pretrained else None
        model = models.vgg16(weights=weights)
        in_features = model.classifier[6].in_features
        model.classifier[6] = nn.Linear(in_features, num_classes)

    elif model_name == 'inception_v3':
        model = InceptionWrapper(num_classes=num_classes, pretrained=pretrained)

    elif model_name == 'incres_v2':
        # timm este deștept și știe să adapteze automat ultimul strat
        model = timm.create_model('inception_resnet_v2', pretrained=pretrained, num_classes=num_classes)

    else:
        raise ValueError(f"Modelul {model_name} nu este suportat!")

    return model

# ==============================================================================

import torch.nn as nn
import torch.optim as optim

def get_optimizer(model, optimizer_name='adam', lr=0.0001):
    """
    Returnează optimizatorul dorit. 
    AdamW este adesea standardul modern, dar SGD cu momentum e excelent pentru arhitecturi adânci.
    """
    optimizer_name = optimizer_name.lower()

    # ==========================================
    # SOLUȚIA UNIVERSALĂ:
    # PyTorch extrage automat doar straturile noi (neînghețate), 
    # indiferent cum se numesc ele (fc, classifier) sau dacă e DataParallel.
    # ==========================================
    parametri_de_antrenat = filter(lambda p: p.requires_grad, model.parameters())
    
    # weight_decay (L2 Regularization) ajută modelul să nu facă overfitting pe datele de train
    if optimizer_name == 'adam':
        return optim.Adam(parametri_de_antrenat, lr=lr, weight_decay=1e-4)
        
    elif optimizer_name == 'adamw':
        return optim.AdamW(parametri_de_antrenat, lr=lr, weight_decay=1e-4)
        
    elif optimizer_name == 'sgd':
        return optim.SGD(parametri_de_antrenat, lr=lr, momentum=0.9, weight_decay=1e-4)
        
    else:
        raise ValueError(f"Optimizatorul {optimizer_name} nu este suportat! Alege dintre: adam, adamw, sgd")
    
# ==============================================================================

def get_loss_function(loss_name='bce', pos_weight=None):
    """
    Pentru Clasificare Binară folosim standard BCEWithLogitsLoss.
    Dacă setul de date are mulți pacienți sănătoși și puțini bolnavi,
    putem folosi 'pos_weight' pentru a forța modelul să fie mai atent la cei bolnavi.
    """
    loss_name = loss_name.lower()
    
    if loss_name == 'bce':
        if pos_weight is not None:
            # pos_weight îi spune modelului: "O greșeală pe clasa 1 (Bolnav) te costă de X ori mai mult"
            # Trebuie să fie tensor, deci îl convertim.
            return nn.BCEWithLogitsLoss(pos_weight=torch.tensor([pos_weight]))
        else:
            return nn.BCEWithLogitsLoss()
            
    else:
        raise ValueError("Pentru clasificare binară suportăm doar 'bce' (BCEWithLogitsLoss).")