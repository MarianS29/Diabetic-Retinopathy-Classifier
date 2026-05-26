import argparse
import importlib
import os
import sys
import time

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import torch
import torch.nn.functional as F
from sklearn.metrics import (
    auc,
    balanced_accuracy_score,
    classification_report,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
    roc_auc_score,
    roc_curve,
)
from sklearn.preprocessing import label_binarize
from torch.utils.data import DataLoader
from tqdm import tqdm


try:
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    CURRENT_DIR = os.getcwd()

PARENT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..', '..'))

if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from builder import (
    compute_loss,
    count_trainable_parameters,
    format_lrs,
    get_loss_function,
    get_model,
    get_optimizer,
    get_predictions,
    set_backbone_trainable,
)
import my_dataset as my_dataset_module

my_dataset_module = importlib.reload(my_dataset_module)
EXPERIMENTS = my_dataset_module.EXPERIMENTS
DATA_SOURCES = my_dataset_module.DATA_SOURCES
make_dataset = my_dataset_module.make_dataset
resolve_experiment = my_dataset_module.resolve_experiment


CLASS_NAMES = ['0', '1', '2', '3', '4']
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406])
IMAGENET_STD = np.array([0.229, 0.224, 0.225])

RESULT_SUBDIRS = {
    'history': 'istoric',
    'loss': 'loss',
    'accuracy': 'acuratete',
    'auc': 'auc',
    'qwk': 'qwk',
    'macro_f1': 'macro_f1',
    'balanced_acc': 'balanced_accuracy',
    'confusion': 'matrici_confuzie',
    'classification_reports': 'rapoarte_clasificare',
    'precision_recall_f1': 'precision_recall_f1',
    'roc': 'roc',
    'gradcam': 'gradcam',
    'errors': 'erori',
    'other': 'altele',
}


def parse_args():
    parser = argparse.ArgumentParser(description="Antrenament DR - experimente Balanced/APTOS")
    parser.add_argument('--model', type=str, default='resnet50', help='ex: resnet50, efficientnet_b3, inception_v3')
    parser.add_argument('--loss_name', type=str, default='ce', help='ex: ce, bce_ordinal, focal_loss, weighted_ce')
    parser.add_argument('--optimizer', type=str, default='adam', help='Variante: adam, adamw, sgd')
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--batch_size', type=int, default=32)
    parser.add_argument('--lr', type=float, default=0.0001)
    parser.add_argument('--img_size', type=int, default=224)
    parser.add_argument('--num_workers', type=int, default=0)
    parser.add_argument('--class_weights', type=float, nargs='+', default=None)
    parser.add_argument('--gamma', type=float, default=1.5, help='Valoarea gamma pentru Focal Loss (daca este selectat).')
    parser.add_argument(
        '--monitor_metric',
        type=str,
        default='qwk',
        choices=['qwk', 'macro_f1', 'balanced_acc', 'auc', 'acc', 'val_loss'],
        help='Metrica folosita pentru checkpoint si early stopping.',
    )
    parser.add_argument(
        '--scheduler',
        type=str,
        default='plateau',
        choices=['plateau', 'cosine', 'none'],
        help='Scheduler LR. plateau pastreaza comportamentul vechi; cosine e util pentru fine-tuning.',
    )
    parser.add_argument('--amp', action='store_true', help='Activeaza mixed precision pe CUDA.')
    parser.add_argument('--grad_clip', type=float, default=0.0, help='Clip gradient norm. 0 dezactiveaza.')
    parser.add_argument('--ema_decay', type=float, default=0.0, help='EMA pentru greutati. Ex: 0.999. 0 dezactiveaza.')
    parser.add_argument(
        '--model_dropout',
        type=float,
        default=0.0,
        help='Dropout intern pentru modele timm, util pentru incres_v2. 0 pastreaza comportamentul implicit.',
    )
    parser.add_argument(
        '--freeze_backbone_epochs',
        type=int,
        default=0,
        help='Antreneaza doar head-ul in primele N epoci, apoi deblocheaza backbone-ul.',
    )
    parser.add_argument(
        '--backbone_lr_mult',
        type=float,
        default=1.0,
        help='Multiplicator LR pentru backbone. Ex: 0.1 inseamna backbone LR = lr * 0.1.',
    )
    parser.add_argument(
        '--tta_eval',
        action='store_true',
        help='Activeaza TTA la validare/test pentru multiclass: original + horizontal flip.',
    )
    parser.add_argument(
        '--train_augment',
        type=str,
        default='basic',
        choices=['basic', 'none'],
        help='Augmentare online pentru split-ul train. basic pastreaza comportamentul vechi; none aplica doar resize/tensor/normalizare.',
    )
    parser.add_argument(
        '--early_stopping_patience',
        type=int,
        default=0,
        help='Opreste antrenarea dupa N epoci fara imbunatatire. 0 dezactiveaza early stopping.',
    )
    parser.add_argument(
        '--early_stopping_min_delta',
        type=float,
        default=0.0,
        help='Imbunatatirea minima a metricii monitorizate necesara pentru resetarea patience.',
    )

    parser.add_argument(
        '--experiment',
        type=str,
        default=None,
        choices=list(EXPERIMENTS.keys()),
        help='Alege direct combinatia train/test. Ex: balanced_aptos_to_aptos',
    )
    parser.add_argument(
        '--train_source',
        type=str,
        default='balanced',
        choices=DATA_SOURCES,
        help='Sursa pentru train/val daca nu folosesti --experiment.',
    )
    parser.add_argument(
        '--test_source',
        type=str,
        default='balanced',
        choices=DATA_SOURCES,
        help='Sursa pentru test daca nu folosesti --experiment.',
    )
    parser.add_argument(
        '--test_sources',
        type=str,
        nargs='+',
        default=None,
        choices=DATA_SOURCES,
        help='Optional: ruleaza testarea finala pe mai multe surse, in aceeasi antrenare. Ex: --test_sources aptos balanced',
    )
    parser.add_argument(
        '--root_dir',
        type=str,
        default=None,
        help='Compatibilitate veche: radacina pentru Diabetic_Balanced_Data.',
    )
    parser.add_argument('--balanced_root', type=str, default=None)
    parser.add_argument(
        '--balanced_aug_root',
        type=str,
        default=None,
        help='Radacina pentru Diabetic_Balanced_Aug_Ben_Graham, cu structura train/val/test/0..4.',
    )
    parser.add_argument(
        '--aptos_root',
        type=str,
        default=None,
        help='Radacina APTOS deja preprocesat Ben Graham, cu structura train/val/test/0..4.',
    )
    return parser.parse_args()


def make_results_dirs(grafice_dir):
    dirs = {}
    os.makedirs(grafice_dir, exist_ok=True)
    for key, folder_name in RESULT_SUBDIRS.items():
        path = os.path.join(grafice_dir, folder_name)
        os.makedirs(path, exist_ok=True)
        dirs[key] = path
    return dirs

# grafice si rapoarte pentru analiza post-antrenare, care vor fi salvate in subfolderele din results_dirs
def save_combined_history(history, path, show=False):
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    axes = axes.ravel()
    
    axes[0].plot(history['train_loss'], label='Train Loss')
    axes[0].plot(history['val_loss'], label='Val Loss')
    axes[0].set_title('Istoric Loss')
    axes[0].set_xlabel('Epoca')
    axes[0].set_ylabel('Loss')
    axes[0].legend()

    axes[1].plot(history['val_acc'], label='Val Accuracy', color='orange')
    axes[1].set_title('Istoric Acuratete (Val)')
    axes[1].set_xlabel('Epoca')
    axes[1].set_ylabel('Acuratete')
    axes[1].legend()

    axes[2].plot(history['val_auc'], label='Val AUC', color='green')
    axes[2].set_title('Istoric AUC (Val)')
    axes[2].set_xlabel('Epoca')
    axes[2].set_ylabel('AUC')
    axes[2].legend()

    axes[3].plot(history['val_qwk'], label='Val QWK', color='purple')
    axes[3].set_title('Istoric QWK (Val)')
    axes[3].set_xlabel('Epoca')
    axes[3].set_ylabel('QWK')
    axes[3].legend()

    axes[4].plot(history['val_macro_f1'], label='Val Macro F1', color='red')
    axes[4].set_title('Istoric Macro F1 (Val)')
    axes[4].set_xlabel('Epoca')
    axes[4].set_ylabel('Macro F1')
    axes[4].legend()

    axes[5].plot(history['val_balanced_acc'], label='Val Balanced Acc', color='brown')
    axes[5].set_title('Istoric Balanced Accuracy (Val)')
    axes[5].set_xlabel('Epoca')
    axes[5].set_ylabel('Balanced Accuracy')
    axes[5].legend()

    plt.savefig(path, bbox_inches='tight')
    if show:
        plt.show()
    plt.close()


def save_line_plot(values, title, ylabel, path, color=None, label=None, show=False):
    plt.figure(figsize=(8, 5))
    plt.plot(values, color=color, label=label or ylabel)
    plt.title(title)
    plt.xlabel('Epoca')
    plt.ylabel(ylabel)
    plt.legend()
    plt.grid(alpha=0.25)
    plt.savefig(path, bbox_inches='tight')
    if show:
        plt.show()
    plt.close()


def save_confusion_matrix(labels, preds, path, normalized=False, show=False):
    if normalized:
        cm = confusion_matrix(labels, preds, labels=list(range(5)), normalize='true')
        fmt = '.2f'
        title = 'Matrice Confuzie Normalizata'
    else:
        cm = confusion_matrix(labels, preds, labels=list(range(5)))
        fmt = 'd'
        title = 'Matrice Confuzie'

    plt.figure(figsize=(8, 6))
    sns.heatmap(
        cm,
        annot=True,
        fmt=fmt,
        cmap='Blues',
        xticklabels=CLASS_NAMES,
        yticklabels=CLASS_NAMES,
        vmin=0 if normalized else None,
        vmax=1 if normalized else None,
    )
    plt.xlabel('Predictie (Model)')
    plt.ylabel('Realitate (Adevar)')
    plt.title(title)
    plt.savefig(path, bbox_inches='tight')
    if show:
        plt.show()
    plt.close()


def save_precision_recall_f1(labels, preds, base_name, results_dirs, show=False):
    precision, recall, f1, support = precision_recall_fscore_support(
        labels,
        preds,
        labels=list(range(5)),
        zero_division=0,
    )

    x = np.arange(len(CLASS_NAMES))
    width = 0.25

    plt.figure(figsize=(10, 6))
    plt.bar(x - width, precision, width, label='Precision')
    plt.bar(x, recall, width, label='Recall')
    plt.bar(x + width, f1, width, label='F1')
    plt.xticks(x, CLASS_NAMES)
    plt.ylim(0, 1)
    plt.xlabel('Clasa')
    plt.ylabel('Scor')
    plt.title('Precision / Recall / F1 pe clase')
    plt.legend()
    plt.grid(axis='y', alpha=0.25)

    prf1_path = os.path.join(results_dirs['precision_recall_f1'], f"prf1_{base_name}.png")
    plt.savefig(prf1_path, bbox_inches='tight')
    if show:
        plt.show()
    plt.close()

    report = classification_report(
        labels,
        preds,
        labels=list(range(5)),
        target_names=CLASS_NAMES,
        zero_division=0,
    )
    report_path = os.path.join(results_dirs['classification_reports'], f"classification_report_{base_name}.txt")
    with open(report_path, 'w', encoding='utf-8') as report_file:
        report_file.write(report)

    metrics_path = os.path.join(results_dirs['precision_recall_f1'], f"prf1_{base_name}.csv")
    with open(metrics_path, 'w', encoding='utf-8') as metrics_file:
        metrics_file.write('class,precision,recall,f1,support\n')
        for class_name, p, r, f, s in zip(CLASS_NAMES, precision, recall, f1, support):
            metrics_file.write(f'{class_name},{p:.6f},{r:.6f},{f:.6f},{int(s)}\n')

    return prf1_path, report_path, metrics_path, report


def save_roc_curve(labels, probs, base_name, results_dirs, show=False):
    labels = np.asarray(labels)
    probs = np.asarray(probs)
    y_true = label_binarize(labels, classes=list(range(5)))

    plt.figure(figsize=(8, 6))
    plotted_any = False

    for class_idx, class_name in enumerate(CLASS_NAMES):
        if y_true[:, class_idx].sum() == 0:
            continue
        if y_true[:, class_idx].sum() == len(y_true):
            continue

        fpr, tpr, _ = roc_curve(y_true[:, class_idx], probs[:, class_idx])
        class_auc = auc(fpr, tpr)
        plt.plot(fpr, tpr, label=f'Clasa {class_name} (AUC={class_auc:.3f})')
        plotted_any = True

    if plotted_any:
        try:
            fpr_micro, tpr_micro, _ = roc_curve(y_true.ravel(), probs.ravel())
            micro_auc = auc(fpr_micro, tpr_micro)
            plt.plot(fpr_micro, tpr_micro, linestyle='--', color='black', label=f'Micro (AUC={micro_auc:.3f})')
        except Exception:
            pass

    plt.plot([0, 1], [0, 1], linestyle=':', color='gray')
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title('Curbe ROC multiclasa')
    plt.legend(loc='lower right')
    plt.grid(alpha=0.25)

    roc_path = os.path.join(results_dirs['roc'], f"roc_{base_name}.png")
    plt.savefig(roc_path, bbox_inches='tight')
    if show:
        plt.show()
    plt.close()
    return roc_path


def find_last_conv_layer(model):
    last_name, last_module = None, None
    for name, module in model.named_modules():
        if isinstance(module, torch.nn.Conv2d):
            last_name, last_module = name, module

    if last_module is None:
        raise RuntimeError("Nu am gasit niciun strat Conv2d pentru Grad-CAM.")

    return last_name, last_module


def denormalize_image(tensor):
    image = tensor.detach().cpu().permute(1, 2, 0).numpy()
    image = (image * IMAGENET_STD) + IMAGENET_MEAN
    return np.clip(image, 0, 1)


def save_gradcam_overlay(model, data_loader, loss_name, device, base_name, results_dirs, show=False):
    try:
        layer_name, target_layer = find_last_conv_layer(model)
    except RuntimeError as error:
        print(f"Grad-CAM sarit: {error}")
        return None

    activations = []
    gradients = []

    def forward_hook(_, __, output):
        activations.append(output.detach())

    def backward_hook(_, grad_input, grad_output):
        gradients.append(grad_output[0].detach())

    forward_handle = target_layer.register_forward_hook(forward_hook)
    backward_handle = target_layer.register_full_backward_hook(backward_hook)

    model.eval()
    try:
        imgs, labels = next(iter(data_loader))
        img = imgs[:1].to(device)
        label = labels[0].item()

        model.zero_grad(set_to_none=True)
        outputs = model(img)
        preds = get_predictions(outputs, loss_name)
        pred = preds[0].item()
        target_class = pred
        score = outputs[0, target_class]
        score.backward()

        activation = activations[-1][0]
        gradient = gradients[-1][0]
        weights = gradient.mean(dim=(1, 2), keepdim=True)
        cam = torch.sum(weights * activation, dim=0)
        cam = F.relu(cam)
        cam = cam - cam.min()
        cam = cam / (cam.max() + 1e-8)
        cam = F.interpolate(
            cam.unsqueeze(0).unsqueeze(0),
            size=img.shape[-2:],
            mode='bilinear',
            align_corners=False,
        ).squeeze().cpu().numpy()

        image = denormalize_image(imgs[0])
        heatmap = plt.cm.jet(cam)[..., :3]
        overlay = np.clip((0.55 * image) + (0.45 * heatmap), 0, 1)

        gradcam_path = os.path.join(results_dirs['gradcam'], f"gradcam_{base_name}.png")
        plt.figure(figsize=(10, 4))
        plt.subplot(1, 2, 1)
        plt.imshow(image)
        plt.title(f'Original | Real: {label}')
        plt.axis('off')

        plt.subplot(1, 2, 2)
        plt.imshow(overlay)
        plt.title(f'Grad-CAM | Pred: {pred} | Layer: {layer_name}')
        plt.axis('off')

        plt.savefig(gradcam_path, bbox_inches='tight')
        if show:
            plt.show()
        plt.close()
        return gradcam_path
    except Exception as error:
        print(f"Grad-CAM sarit: {error}")
        return None
    finally:
        forward_handle.remove()
        backward_handle.remove()


class ModelEMA:
    def __init__(self, model, decay):
        self.decay = decay
        self.shadow = {
            name: param.detach().clone()
            for name, param in model.state_dict().items()
            if torch.is_floating_point(param)
        }
        self.backup = {}

    @torch.no_grad()
    def update(self, model):
        model_state = model.state_dict()
        for name, shadow_param in self.shadow.items():
            shadow_param.mul_(self.decay).add_(model_state[name].detach(), alpha=1.0 - self.decay)

    def apply_shadow(self, model):
        self.backup = {}
        model_state = model.state_dict()
        for name, shadow_param in self.shadow.items():
            self.backup[name] = model_state[name].detach().clone()
            model_state[name].copy_(shadow_param)

    def restore(self, model):
        model_state = model.state_dict()
        for name, backup_param in self.backup.items():
            model_state[name].copy_(backup_param)
        self.backup = {}


def get_multiclass_outputs(model, imgs, use_tta=False):
    outputs = model(imgs)
    if not use_tta:
        return outputs

    flipped_outputs = model(torch.flip(imgs, dims=[3]))
    return (outputs + flipped_outputs) / 2.0


def compute_extra_metrics(labels, preds):
    try:
        qwk = cohen_kappa_score(labels, preds, weights='quadratic')
    except Exception:
        qwk = 0.0
    try:
        macro_f1 = f1_score(labels, preds, labels=list(range(5)), average='macro', zero_division=0)
    except Exception:
        macro_f1 = 0.0
    try:
        balanced_acc = balanced_accuracy_score(labels, preds)
    except Exception:
        balanced_acc = 0.0
    return qwk, macro_f1, balanced_acc


def evaluate(model, data_loader, criterion, loss_name, device, desc, use_tta=False):
    model.eval()
    total_loss, correct, total = 0.0, 0, 0
    all_preds, all_labels, all_probs = [], [], []
    use_tta = use_tta and loss_name.lower() not in ['bce_ordinal', 'ordinal']

    with torch.no_grad():
        progress = tqdm(data_loader, desc=desc, leave=False)
        for imgs, labels in progress:
            imgs, labels = imgs.to(device), labels.to(device)
            outputs = model(imgs)
            loss = compute_loss(criterion, outputs, labels, loss_name, device)
            metric_outputs = get_multiclass_outputs(model, imgs, use_tta=use_tta)

            total_loss += loss.item()
            preds = get_predictions(metric_outputs, loss_name)
            correct += (preds == labels).sum().item()
            total += labels.size(0)

            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())
            all_probs.extend(F.softmax(metric_outputs, dim=1).cpu().numpy())

    avg_loss = total_loss / max(len(data_loader), 1)
    acc = correct / max(total, 1)
    try:
        auc = roc_auc_score(all_labels, all_probs, multi_class='ovr', average='macro')
    except Exception:
        auc = 0.0
    qwk, macro_f1, balanced_acc = compute_extra_metrics(all_labels, all_preds)

    return avg_loss, acc, auc, qwk, macro_f1, balanced_acc, all_preds, all_labels, all_probs


def select_metric(metrics, monitor_metric):
    return {
        'acc': metrics['acc'],
        'auc': metrics['auc'],
        'qwk': metrics['qwk'],
        'macro_f1': metrics['macro_f1'],
        'balanced_acc': metrics['balanced_acc'],
        'val_loss': metrics['val_loss'],
    }[monitor_metric]


def is_lower_better_metric(monitor_metric):
    return monitor_metric == 'val_loss'


def metric_improved(metric, best_metric, monitor_metric, min_delta):
    if is_lower_better_metric(monitor_metric):
        return metric < best_metric - min_delta
    return metric > best_metric + min_delta


def make_result_base_name(base_name, test_source, use_test_suffix):
    if not use_test_suffix:
        return base_name
    safe_test_source = test_source.replace('+', '_').replace('/', '_').replace('\\', '_')
    return f"{base_name}_test_{safe_test_source}"


def run_final_test(
    model,
    test_source,
    test_loader,
    criterion,
    args,
    device,
    base_name,
    results_dirs,
    use_test_suffix,
):
    result_base_name = make_result_base_name(base_name, test_source, use_test_suffix)

    print("\n" + "=" * 50)
    print(f"START TEST FINAL: {test_source}")
    print("=" * 50)

    test_loss, test_acc, test_auc, test_qwk, test_macro_f1, test_balanced_acc, test_preds, test_labels, test_probs = evaluate(
        model,
        test_loader,
        criterion,
        args.loss_name,
        device,
        desc=f"Testare model [{test_source}]",
        use_tta=args.tta_eval,
    )

    print("Rezultate testare finala:")
    print(f"   Dataset test: {test_source}")
    print(f"   Acuratete: {test_acc * 100:.2f}%")
    print(f"   Scor AUC:  {test_auc:.4f}")
    print(f"   QWK:       {test_qwk:.4f}")
    print(f"   Macro F1:  {test_macro_f1:.4f}")
    print(f"   Bal Acc:   {test_balanced_acc:.4f}")
    print(f"   Loss:      {test_loss:.4f}\n")

    print("Classification report:")
    prf1_path, report_path, metrics_path, report = save_precision_recall_f1(
        test_labels,
        test_preds,
        result_base_name,
        results_dirs,
        show=True
    )
    print(report)

    cm_path = os.path.join(results_dirs['confusion'], f"cm_{result_base_name}.png")
    save_confusion_matrix(test_labels, test_preds, cm_path, normalized=False, show=True)

    cm_norm_path = os.path.join(results_dirs['confusion'], f"cm_norm_{result_base_name}.png")
    save_confusion_matrix(test_labels, test_preds, cm_norm_path, normalized=True, show=True)

    roc_path = save_roc_curve(test_labels, test_probs, result_base_name, results_dirs, show=True)
    gradcam_path = save_gradcam_overlay(model, test_loader, args.loss_name, device, result_base_name, results_dirs, show=True)

    print(f"Rezultate pentru test={test_source}:")
    print(f"Matrice confuzie: {cm_path}")
    print(f"Matrice confuzie normalizata: {cm_norm_path}")
    print(f"Precision/Recall/F1: {prf1_path}")
    print(f"Raport clasificare: {report_path}")
    print(f"Metrici CSV: {metrics_path}")
    print(f"ROC curve: {roc_path}")
    if gradcam_path:
        print(f"Grad-CAM overlay: {gradcam_path}")

    return {
        'source': test_source,
        'loss': test_loss,
        'acc': test_acc,
        'auc': test_auc,
        'qwk': test_qwk,
        'macro_f1': test_macro_f1,
        'balanced_acc': test_balanced_acc,
        'cm_path': cm_path,
        'cm_norm_path': cm_norm_path,
        'prf1_path': prf1_path,
        'report_path': report_path,
        'metrics_path': metrics_path,
        'roc_path': roc_path,
        'gradcam_path': gradcam_path,
    }


def main():
    args = parse_args()
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    balanced_root = args.balanced_root or args.root_dir or os.path.join(PROJECT_ROOT, 'datasets', 'Diabetic_Balanced_Data')
    balanced_aug_root = args.balanced_aug_root or os.path.join(PROJECT_ROOT, 'datasets', 'Diabetic_Balanced_Aug_Ben_Graham')
    aptos_root = args.aptos_root or os.path.join(PROJECT_ROOT, 'datasets', 'aptos', 'aptos_ben_graham')
    train_source, test_source = resolve_experiment(args.experiment, args.train_source, args.test_source)
    test_sources = args.test_sources or [test_source]
    val_source = train_source
    experiment_name = args.experiment or f"{train_source}_to_{test_source}"

    rezultate_dir = os.path.join(CURRENT_DIR, "Rezultate")
    modele_dir = os.path.join(rezultate_dir, "modele")
    grafice_dir = os.path.join(rezultate_dir, "grafice")
    os.makedirs(modele_dir, exist_ok=True)
    results_dirs = make_results_dirs(grafice_dir)

    print(f"Config: {args.model} | Loss: {args.loss_name} | Opt: {args.optimizer} | LR: {args.lr}")
    print(f"Experiment: {experiment_name} | TRAIN/VAL={train_source} | TEST={', '.join(test_sources)}")
    print(f"Train augment: {args.train_augment}")
    print(f"Monitor metric: {args.monitor_metric} | Scheduler: {args.scheduler}")
    print(f"AMP: {args.amp} | Grad clip: {args.grad_clip} | EMA decay: {args.ema_decay} | TTA eval: {args.tta_eval}")
    print(
        f"Model dropout: {args.model_dropout} | Freeze backbone epochs: {args.freeze_backbone_epochs} | "
        f"Backbone LR mult: {args.backbone_lr_mult}"
    )
    if args.model.lower() == 'incres_v2' and args.img_size < 299:
        print(
            "Atentie: incres_v2 este de obicei folosit cu input >= 299. "
            "Pentru rularea principala ia in calcul --img_size 299 sau 384."
        )
    print(f"Balanced root: {balanced_root}")
    print(f"Balanced Aug root: {balanced_aug_root}")
    print(f"APTOS root:    {aptos_root}")

    train_ds = make_dataset(
        train_source,
        split='train',
        image_size=args.img_size,
        balanced_root=balanced_root,
        aptos_root=aptos_root,
        balanced_aug_root=balanced_aug_root,
        train_augment=args.train_augment,
    )
    val_ds = make_dataset(
        val_source,
        split='val',
        image_size=args.img_size,
        balanced_root=balanced_root,
        aptos_root=aptos_root,
        balanced_aug_root=balanced_aug_root,
        train_augment=args.train_augment,
    )
    test_datasets = {}
    for current_test_source in test_sources:
        test_datasets[current_test_source] = make_dataset(
            current_test_source,
            split='test',
            image_size=args.img_size,
            balanced_root=balanced_root,
            aptos_root=aptos_root,
            balanced_aug_root=balanced_aug_root,
            train_augment=args.train_augment,
        )

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)
    test_loaders = {
        current_test_source: DataLoader(test_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)
        for current_test_source, test_ds in test_datasets.items()
    }

    # Daca avem focal loss, afisam valoarea gamma
    if args.loss_name == 'focal_loss':
        print(f"Focal Loss activat cu gamma={args.gamma}")
    test_sizes = ' | '.join([f"TESTARE[{source}]={len(dataset)}" for source, dataset in test_datasets.items()])
    print(f"Distributie date: TRAIN={len(train_ds)} | VALIDARE={len(val_ds)} | {test_sizes}")

    model = get_model(args.model, num_classes=5, drop_rate=args.model_dropout).to(device)
    if args.freeze_backbone_epochs > 0:
        set_backbone_trainable(model, trainable=False)
        print(
            f"Backbone inghetat pentru primele {args.freeze_backbone_epochs} epoci. "
            f"Parametri antrenabili initial: {count_trainable_parameters(model):,}"
        )
    criterion = get_loss_function(args.loss_name, class_weights=args.class_weights, device=device, gamma=args.gamma)
    optimizer = get_optimizer(
        model,
        optimizer_name=args.optimizer,
        lr=args.lr,
        backbone_lr_mult=args.backbone_lr_mult,
    )
    if args.scheduler == 'plateau':
        scheduler_mode = 'min' if is_lower_better_metric(args.monitor_metric) else 'max'
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode=scheduler_mode, factor=0.5, patience=3)
    elif args.scheduler == 'cosine':
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(args.epochs, 1), eta_min=args.lr * 0.01)
    else:
        scheduler = None
    use_amp = args.amp and device.type == 'cuda'
    scaler = torch.amp.GradScaler(device.type, enabled=use_amp)
    ema = ModelEMA(model, args.ema_decay) if args.ema_decay > 0 else None

    history = {
        'train_loss': [],
        'val_loss': [],
        'val_acc': [],
        'val_auc': [],
        'val_qwk': [],
        'val_macro_f1': [],
        'val_balanced_acc': [],
    }
    best_metric = float('inf') if is_lower_better_metric(args.monitor_metric) else -float('inf')
    epochs_without_improvement = 0
    stopped_early = False
    stopped_epoch = None
    base_name = f"{experiment_name}_{args.model}_{args.loss_name}_{args.optimizer}_LR_{args.lr}_Gamma_{args.gamma}"
    model_path = os.path.join(modele_dir, f"best_{base_name}.pth")

    for epoch in range(args.epochs):
        start_time = time.time()
        if args.freeze_backbone_epochs > 0 and epoch == args.freeze_backbone_epochs:
            set_backbone_trainable(model, trainable=True)
            print(
                f"Backbone deblocat la epoca {epoch + 1}. "
                f"Parametri antrenabili: {count_trainable_parameters(model):,}"
            )
        model.train()
        train_loss = 0.0

        progress = tqdm(train_loader, desc=f"Ep {epoch + 1:02d} [TRAIN]", leave=False)
        for imgs, labels in progress:
            imgs, labels = imgs.to(device), labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(device.type, enabled=use_amp):
                outputs = model(imgs)
                loss = compute_loss(criterion, outputs, labels, args.loss_name, device)

            scaler.scale(loss).backward()
            if args.grad_clip > 0:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
            scaler.step(optimizer)
            scaler.update()
            if ema is not None:
                ema.update(model)

            train_loss += loss.item()
            progress.set_postfix({'loss': f"{loss.item():.4f}"})

        epoch_train_loss = train_loss / max(len(train_loader), 1)
        if ema is not None:
            ema.apply_shadow(model)
        val_loss, val_acc, val_auc, val_qwk, val_macro_f1, val_balanced_acc, _, _, _ = evaluate(
            model,
            val_loader,
            criterion,
            args.loss_name,
            device,
            desc=f"Ep {epoch + 1:02d} [VALID]",
            use_tta=args.tta_eval,
        )
        if ema is not None:
            ema.restore(model)

        history['train_loss'].append(epoch_train_loss)
        history['val_loss'].append(val_loss)
        history['val_acc'].append(val_acc)
        history['val_auc'].append(val_auc)
        history['val_qwk'].append(val_qwk)
        history['val_macro_f1'].append(val_macro_f1)
        history['val_balanced_acc'].append(val_balanced_acc)

        metrics = {
            'acc': val_acc,
            'auc': val_auc,
            'qwk': val_qwk,
            'macro_f1': val_macro_f1,
            'balanced_acc': val_balanced_acc,
            'val_loss': val_loss,
        }
        metric = select_metric(metrics, args.monitor_metric)
        if scheduler is not None:
            if args.scheduler == 'plateau':
                scheduler.step(metric)
            else:
                scheduler.step()
        marker = ""
        if metric_improved(metric, best_metric, args.monitor_metric, args.early_stopping_min_delta):
            best_metric = metric
            epochs_without_improvement = 0
            if ema is not None:
                ema.apply_shadow(model)
            torch.save(model.state_dict(), model_path)
            if ema is not None:
                ema.restore(model)
            marker = "NOU BEST"
        else:
            epochs_without_improvement += 1

        print(
            f"Ep {epoch + 1:02d}/{args.epochs} | "
            f"T_Loss: {epoch_train_loss:.4f} | V_Loss: {val_loss:.4f} | "
            f"V_Acc: {val_acc * 100:.1f}% | V_AUC: {val_auc:.4f} | "
            f"V_QWK: {val_qwk:.4f} | V_F1: {val_macro_f1:.4f} | "
            f"V_BalAcc: {val_balanced_acc:.4f} | Best[{args.monitor_metric}]={best_metric:.4f} {marker}"
        )
        print(f"LR curent: {format_lrs(optimizer)}")
        print(f"Durata epoca: {(time.time() - start_time) / 60:.2f} min")
        if args.early_stopping_patience > 0:
            print(
                f"Early stopping: {epochs_without_improvement}/"
                f"{args.early_stopping_patience} epoci fara imbunatatire"
            )
            if epochs_without_improvement >= args.early_stopping_patience:
                stopped_early = True
                stopped_epoch = epoch + 1
                print(
                    f"Early stopping activat la epoca {stopped_epoch}. "
                    f"Cea mai buna metrica: {best_metric:.4f}"
                )
                break

    model.load_state_dict(torch.load(model_path, map_location=device))

    # Afisare grafice de acuratete, loss, AUC, matricile de confuzie (normala + normalizata), Grad-CAM, curba ROC
    # Am adaugat paramtetrul show=True ca sa apara pozele dupa testare

    history_path = os.path.join(results_dirs['history'], f"istoric_combinat_{base_name}.png")
    save_combined_history(history, history_path, show=True)

    loss_path = os.path.join(results_dirs['loss'], f"loss_{base_name}.png")
    save_line_plot(history['train_loss'], 'Loss Antrenament', 'Loss', loss_path, color='blue', label='Train Loss', show=True)

    acc_path = os.path.join(results_dirs['accuracy'], f"acc_{base_name}.png")
    save_line_plot(history['val_acc'], 'Acuratete Validare', 'Acuratete', acc_path, color='orange', label='Val Acc', show=True)

    auc_path = os.path.join(results_dirs['auc'], f"auc_{base_name}.png")
    save_line_plot(history['val_auc'], 'Scor AUC Validare', 'AUC', auc_path, color='green', label='Val AUC', show=True)

    qwk_path = os.path.join(results_dirs['qwk'], f"qwk_{base_name}.png")
    save_line_plot(history['val_qwk'], 'Quadratic Weighted Kappa Validare', 'QWK', qwk_path, color='purple', label='Val QWK', show=True)

    macro_f1_path = os.path.join(results_dirs['macro_f1'], f"macro_f1_{base_name}.png")
    save_line_plot(history['val_macro_f1'], 'Macro F1 Validare', 'Macro F1', macro_f1_path, color='red', label='Val Macro F1', show=True)

    balanced_acc_path = os.path.join(results_dirs['balanced_acc'], f"balanced_acc_{base_name}.png")
    save_line_plot(
        history['val_balanced_acc'],
        'Balanced Accuracy Validare',
        'Balanced Accuracy',
        balanced_acc_path,
        color='brown',
        label='Val Balanced Acc',
        show=True,
    )

    use_test_suffix = len(test_loaders) > 1
    test_results = []
    for current_test_source, current_test_loader in test_loaders.items():
        test_results.append(run_final_test(
            model=model,
            test_source=current_test_source,
            test_loader=current_test_loader,
            criterion=criterion,
            args=args,
            device=device,
            base_name=base_name,
            results_dirs=results_dirs,
            use_test_suffix=use_test_suffix,
        ))

    print(f"\nGata. Model: {model_path}")
    print(f"Grafic evolutie combinat: {history_path}")
    print(f"Grafic loss: {loss_path}")
    print(f"Grafic acuratete: {acc_path}")
    print(f"Grafic AUC: {auc_path}")
    print(f"Grafic QWK: {qwk_path}")
    print(f"Grafic Macro F1: {macro_f1_path}")
    print(f"Grafic Balanced Acc: {balanced_acc_path}")
    if stopped_early:
        print(f"Antrenare oprita anticipat la epoca {stopped_epoch}/{args.epochs}.")
    if len(test_results) > 1:
        print("Rezumat testari finale:")
        for result in test_results:
            print(
                f"   {result['source']}: "
                f"Acc={result['acc'] * 100:.2f}% | AUC={result['auc']:.4f} | "
                f"QWK={result['qwk']:.4f} | F1={result['macro_f1']:.4f} | "
                f"BalAcc={result['balanced_acc']:.4f} | Loss={result['loss']:.4f}"
            )


if __name__ == '__main__':
    if not hasattr(sys.modules['__main__'], '__spec__'):
        sys.modules['__main__'].__spec__ = None
    main()
