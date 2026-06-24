import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models
import torch.optim as optim

# Importam timm pentru Inception-ResNet-v2
try:
    import timm
except ImportError:
    timm = None

class InceptionWrapper(nn.Module):
    """
    Carcasa de protectie pentru Inception-v3.
    Lasa modelul sa se incarce nativ, dar returneaza o singura iesire la antrenare,
    exact cum asteapta functiile noastre de Loss.
    """
    def __init__(self, num_classes, pretrained=True):
        super().__init__()
        # Lasam Inception sa se initializeze 100% standard (fara erori de aux_logits)
        weights = models.Inception_V3_Weights.DEFAULT if pretrained else None
        self.model = models.inception_v3(weights=weights)
        
        # Modificam ultimul strat
        in_features = self.model.fc.in_features
        self.model.fc = nn.Linear(in_features, num_classes)
        
    def forward(self, x):
        outputs = self.model(x)
        # La antrenare, Inception returneaza un obiect cu 2 iesiri. Noi o dam mai departe doar pe prima.
        if self.training:
            return outputs[0]  # outputs[0] reprezinta predictia principala (logits)
        # La validare, returneaza oricum o singura iesire
        return outputs


# ==============================================================================
# 1. Implementare focal loss pentru clasificare multi-clasa 
# ==============================================================================
class FocalLossMultiClass(nn.Module):
    """
    Focal Loss adaptat pentru clasificare multi-clasa.
    Accepta predictii de forma [Batch, Clase] si etichete standard (indici) de forma [Batch].
    """
    def __init__(self, alpha=None, gamma=1.5, reduction='mean', label_smoothing=0.0):
        super(FocalLossMultiClass, self).__init__()
        self.gamma = gamma
        self.alpha = alpha 
        self.reduction = reduction
        self.label_smoothing = label_smoothing

    def forward(self, inputs, targets):
        # Calculam direct Cross Entropy (care stie sa citeasca indicii claselor)
        ce_loss = F.cross_entropy(inputs, targets, weight=self.alpha, reduction='none', label_smoothing=self.label_smoothing)
        pt = torch.exp(-ce_loss)
        focal_loss = ((1 - pt) ** self.gamma) * ce_loss
        
        if self.reduction == 'mean':
            return focal_loss.mean()
        elif self.reduction == 'sum':
            return focal_loss.sum()
        else:
            return focal_loss

# ==============================================================================
# 2. FABRICA DE MODELE
# ==============================================================================
def get_model(model_name, num_classes=5, pretrained=True, drop_rate=0.0):
    """
    Fabrica de modele. Toate au strat final modificat pentru num_classes.
    """
    model_name = model_name.lower()

    if model_name == 'resnet50':
        weights = models.ResNet50_Weights.DEFAULT if pretrained else None
        model = models.resnet50(weights=weights)
        num_ftrs = model.fc.in_features
        model.fc = nn.Sequential(
            nn.Dropout(0.5), 
            nn.Linear(num_ftrs, num_classes)
        )

    elif model_name == 'efficientnet_b3':
        weights = models.EfficientNet_B3_Weights.DEFAULT if pretrained else None
        model = models.efficientnet_b3(weights=weights)
        in_features = model.classifier[1].in_features
        model.classifier[1] = nn.Sequential(
            nn.Dropout(0.5), 
            nn.Linear(in_features, num_classes)
        )

    elif model_name == 'inception_v3':
        model = InceptionWrapper(num_classes=num_classes, pretrained=pretrained)

    elif model_name == 'incres_v2':
        if timm is None:
            raise ImportError(
                "Modelul incres_v2 necesita pachetul 'timm'. Instaleaza-l cu: pip install timm"
            )
        model = timm.create_model(
            'inception_resnet_v2',
            pretrained=pretrained,
            num_classes=num_classes,
            drop_rate=drop_rate,
        )

    else:
        raise ValueError(f"Modelul {model_name} nu este suportat!")

    return model

# ==============================================================================
# 3. FABRICA DE LOSS-URI SI PREDICTII (Totul se intampla aici)
# ==============================================================================
def get_loss_function(loss_name, class_weights=None, device='cuda', gamma=1.5, label_smoothing=0.0):
    loss_name = loss_name.lower()
    
    # -----------------------------------------------------------------
    # REPARAT: Transformam lista venita din consola intr-un Tensor
    # -----------------------------------------------------------------
    if class_weights is not None and isinstance(class_weights, list):
        class_weights = torch.tensor(class_weights, dtype=torch.float)
        
    if loss_name in ['bce_ordinal', 'ordinal']:
        return nn.BCEWithLogitsLoss()
        
    elif loss_name == 'focal_loss':
        # Trimitem ponderile pe GPU (daca exista) pentru Focal Loss
        alpha_tensor = class_weights.to(device) if class_weights is not None else None
        return FocalLossMultiClass(alpha=alpha_tensor, gamma=gamma, label_smoothing=label_smoothing)
        
    elif loss_name == 'ce':
        return nn.CrossEntropyLoss(label_smoothing=label_smoothing)
        
    elif loss_name == 'weighted_ce':
        if class_weights is None:
            raise ValueError("Pentru Weighted CE, trebuie sa trimiti '--class_weights'!")
        # Acum class_weights este oficial un Tensor, deci .to(device) va functiona perfect!
        return nn.CrossEntropyLoss(weight=class_weights.to(device), label_smoothing=label_smoothing)
        
    else:
        raise ValueError(f"Loss-ul '{loss_name}' nu este suportat.")
    

def compute_loss(criterion, outputs, labels, loss_name, device):
    """
    Calculeaza valoarea erorii. Gestioneaza automat transformarile necesare
    pentru etichete (ex. transformarea in vectori ordinali).
    """
    loss_name = loss_name.lower()
    
    if loss_name in ['bce_ordinal', 'ordinal']:
        # Ordinal Regression necesita transformarea [2] -> [1, 1, 1, 0, 0]
        levels = torch.arange(5).to(device)
        labels_ordinal = (labels.unsqueeze(1) >= levels).float()
        return criterion(outputs, labels_ordinal)
        
    else:
        # Pentru CE, Weighted CE si noul Focal Loss, putem da etichetele exact asa cum vin (indici 0-4)
        return criterion(outputs, labels)


def get_predictions(outputs, loss_name):
    """
    Transforma iesirea modelului (tensor de probabilitati/logits) intr-o eticheta finala (0, 1, 2, 3, 4).
    """
    loss_name = loss_name.lower()
    
    if loss_name in ['bce_ordinal', 'ordinal']:
        # Adunam valorile care trec pragul de 0.0 (pragul implicit dupa BCEWithLogits)
        preds = (outputs > 0.0).sum(dim=1) - 1
        return torch.clamp(preds, min=0, max=4)
        
    else:
        # Pentru CE, Weighted CE si Focal Loss, extragem direct valoarea maxima
        return torch.argmax(outputs, dim=1)

HEAD_PARAM_KEYWORDS = (
    'fc',
    'classifier',
    'classif',
    'head',
    'last_linear',
    'logits',
)


def is_head_parameter(name):
    lowered = name.lower()
    return any(keyword in lowered for keyword in HEAD_PARAM_KEYWORDS)


def set_backbone_trainable(model, trainable):
    for name, param in model.named_parameters():
        if not is_head_parameter(name):
            param.requires_grad = trainable


def count_trainable_parameters(model):
    return sum(param.numel() for param in model.parameters() if param.requires_grad)


def get_optimizer_params(model, lr, backbone_lr_mult=1.0):
    if backbone_lr_mult == 1.0:
        return model.parameters()

    head_params = []
    backbone_params = []
    for name, param in model.named_parameters():
        if is_head_parameter(name):
            head_params.append(param)
        else:
            backbone_params.append(param)

    return [
        {'params': backbone_params, 'lr': lr * backbone_lr_mult},
        {'params': head_params, 'lr': lr},
    ]


def format_lrs(optimizer):
    return ', '.join([f"{group['lr']:.8f}" for group in optimizer.param_groups])


# ==============================================================================
# 4. OPTIMIZATORII
# ==============================================================================
def get_optimizer(model, optimizer_name='adam', lr=1e-4, backbone_lr_mult=1.0):
    optimizer_name = optimizer_name.lower()
    params = get_optimizer_params(model, lr, backbone_lr_mult=backbone_lr_mult)
    
    if optimizer_name == 'adam':
        return optim.Adam(params, lr=lr, weight_decay=1e-4)
    elif optimizer_name == 'adamw':
        return optim.AdamW(params, lr=lr, weight_decay=1e-4)
    elif optimizer_name == 'sgd':
        return optim.SGD(params, lr=lr, momentum=0.9, weight_decay=1e-5)
    else:
        raise ValueError(f"Optimizatorul '{optimizer_name}' nu este suportat.")
