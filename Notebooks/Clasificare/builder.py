import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models
import torch.optim as optim

# Importăm timm pentru Inception-ResNet-v2
try:
    import timm
except ImportError:
    timm = None

class InceptionWrapper(nn.Module):
    """
    Carcasă de protecție pentru Inception-v3.
    Lasă modelul să se încarce nativ, dar returnează o singură ieșire la antrenare,
    exact cum așteaptă funcțiile noastre de Loss.
    """
    def __init__(self, num_classes, pretrained=True):
        super().__init__()
        # Lăsăm Inception să se inițializeze 100% standard (fără erori de aux_logits)
        weights = models.Inception_V3_Weights.DEFAULT if pretrained else None
        self.model = models.inception_v3(weights=weights)
        
        # Modificăm ultimul strat
        in_features = self.model.fc.in_features
        self.model.fc = nn.Linear(in_features, num_classes)
        
    def forward(self, x):
        outputs = self.model(x)
        # La antrenare, Inception returnează un obiect cu 2 ieșiri. Noi o dăm mai departe doar pe prima.
        if self.training:
            return outputs[0]  # outputs[0] reprezintă predicția principală (logits)
        # La validare, returnează oricum o singură ieșire
        return outputs

# ==============================================================================
# 1. IMPLEMENTARE CUSTOM LORSS-URI (Focal Loss)
# ==============================================================================
class FocalLossMultiClass(nn.Module):
    """
    Focal Loss adaptat pentru clasificare multi-clasa.
    Accepta predictii de forma [Batch, Clase] si etichete de forma [Batch].
    """
    def __init__(self, alpha=None, gamma=2.0, reduction='mean'):
        super(FocalLossMultiClass, self).__init__()
        self.gamma = gamma
        self.alpha = alpha # Ponderile claselor
        self.reduction = reduction

    def forward(self, inputs, targets):
        # inputs: [Batch_Size, Num_Classes] (ex: 32, 5)
        # targets: [Batch_Size] sau One-Hot. Daca e [Batch_Size], F.cross_entropy stie sa il citeasca nativ.
        
        ce_loss = F.cross_entropy(inputs, targets, weight=self.alpha, reduction='none')
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
# 3. FABRICA DE LOSS-URI
# ==============================================================================
def get_loss_function(loss_name, class_weights=None, device='cuda'):
    loss_name = loss_name.lower()
    
    if loss_name == 'bce_ordinal':
        return nn.BCEWithLogitsLoss()
        
    elif loss_name == 'focal_loss':
        return FocalLossMultiClass(alpha=class_weights, gamma=2.0)
        
    elif loss_name == 'ce':
        return nn.CrossEntropyLoss()
        
    elif loss_name == 'weighted_ce':
        if class_weights is None:
            raise ValueError("Pentru Weighted CrossEntropy, trebuie să transmiți tensorul 'class_weights'!")
        # Greutățile trebuie mutate pe GPU pentru a fi folosite în timpul antrenării
        return nn.CrossEntropyLoss(weight=class_weights.to(device))
        
    else:
        raise ValueError(f"Loss-ul '{loss_name}' nu este suportat.")

# ==============================================================================
# 4. FABRICA DE OPTIMIZATORI
# ==============================================================================
def get_optimizer(model, lr=1e-4):
    parameters = [p for p in model.parameters() if p.requires_grad]
    return optim.AdamW(parameters, lr=lr, weight_decay=1e-4)