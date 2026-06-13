import os
import random
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
from tqdm import tqdm
from builder import compute_loss, get_predictions

# Constante
CLASS_NAMES = ['0', '1', '2', '3', '4']
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406])
IMAGENET_STD = np.array([0.229, 0.224, 0.225])

RESULT_SUBDIRS = {
    'history': 'istoric', 'loss': 'loss', 'accuracy': 'acuratete', 'auc': 'auc', 'qwk': 'qwk',
    'macro_f1': 'macro_f1', 'balanced_acc': 'balanced_accuracy', 'confusion': 'matrici_confuzie',
    'classification_reports': 'rapoarte_clasificare', 'precision_recall_f1': 'precision_recall_f1',
    'roc': 'roc', 'gradcam': 'gradcam', 'errors': 'erori', 'other': 'altele',
}

# ==============================================================================
# Functii utilitare
# ==============================================================================
def resolve_dataset_path(path, project_root):
    if path is None: return None
    path = os.path.expanduser(path)
    return os.path.abspath(path) if os.path.isabs(path) else os.path.abspath(os.path.join(project_root, path))

def safe_source_name(name):
    return name.replace(' ', '_').replace('/', '_').replace('\\', '_').lower()

def make_results_dirs(grafice_dir):
    dirs = {}
    os.makedirs(grafice_dir, exist_ok=True)
    for key, folder_name in RESULT_SUBDIRS.items():
        path = os.path.join(grafice_dir, folder_name)
        os.makedirs(path, exist_ok=True)
        dirs[key] = path
    return dirs

def make_experiment_base_name(experiment_name, args):
    parts = [experiment_name, args.model]
    if args.loss_name != 'focal_loss': parts.append(args.loss_name)
    if args.optimizer != 'adam': parts.append(args.optimizer)
    if args.loss_name == 'focal_loss': parts.append(f"g{args.gamma:g}")
    return "_".join(parts)

def make_result_base_name(base_name, test_source, use_test_suffix):
    if not use_test_suffix: return base_name
    return f"{base_name}_test_{test_source.replace('+', '_').replace('/', '_').replace('\\', '_')}"

class ModelEMA:
    def __init__(self, model, decay):
        self.decay = decay
        self.shadow = {n: p.detach().clone() for n, p in model.state_dict().items() if torch.is_floating_point(p)}
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

# ==============================================================================
# Functii de vizualizare (Grafice, Grad-CAM, Dataset Grid)
# ==============================================================================
def denormalize_image(tensor):
    image = tensor.detach().cpu().permute(1, 2, 0).numpy()
    return np.clip((image * IMAGENET_STD) + IMAGENET_MEAN, 0, 1)

def show_dataset_samples_grid(dataset_dict, title_prefix=""):
    num_datasets = len(dataset_dict)
    if num_datasets == 0: return
    fig, axes = plt.subplots(num_datasets, 5, figsize=(15, 3 * num_datasets))
    if num_datasets == 1: axes = np.expand_dims(axes, axis=0)
    for row_idx, (source_name, ds) in enumerate(dataset_dict.items()):
        found_classes = {}
        indices = list(range(len(ds)))
        random.shuffle(indices)
        for i in indices[:min(len(ds), 500)]:
            img, label = ds[i]
            lbl = int(label)
            if lbl not in found_classes: found_classes[lbl] = denormalize_image(img)
            if len(found_classes) == 5: break
        for col_idx in range(5):
            ax = axes[row_idx, col_idx]
            if col_idx in found_classes: ax.imshow(found_classes[col_idx])
            else: ax.text(0.5, 0.5, 'Lipsă', ha='center', va='center')
            if row_idx == 0: ax.set_title(f"Clasa {col_idx}")
            ax.axis('off')
            if col_idx == 0: ax.text(-0.1, 0.5, source_name, va='center', ha='right', transform=ax.transAxes, fontsize=12, fontweight='bold', rotation=90)
    plt.suptitle(f"Esantioane - {title_prefix}", fontsize=16)
    plt.tight_layout()
    plt.show()

def save_combined_history(history, path, show=False):
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    axes = axes.ravel()
    metrics = [('Train Loss', 'Val Loss', 'train_loss', 'val_loss', 'Istoric Loss', 'Loss'),
               ('Train Accuracy', 'Val Accuracy', 'train_acc', 'val_acc', 'Istoric Acuratete', 'Acuratete')]
    for i, (l1, l2, k1, k2, tit, ylab) in enumerate(metrics):
        axes[i].plot(history[k1], label=l1, color='blue')
        axes[i].plot(history[k2], label=l2, color='orange')
        axes[i].set_title(tit); axes[i].set_xlabel('Epoca'); axes[i].set_ylabel(ylab); axes[i].legend()
    for i, (l1, k1, tit, ylab, col) in enumerate([('Val AUC', 'val_auc', 'Istoric AUC (Val)', 'AUC', 'green'),
                                                  ('Val QWK', 'val_qwk', 'Istoric QWK (Val)', 'QWK', 'purple'),
                                                  ('Val Macro F1', 'val_macro_f1', 'Istoric Macro F1 (Val)', 'Macro F1', 'red'),
                                                  ('Val Balanced Acc', 'val_balanced_acc', 'Istoric Balanced Accuracy (Val)', 'Balanced Accuracy', 'brown')], start=2):
        axes[i].plot(history[k1], label=l1, color=col)
        axes[i].set_title(tit); axes[i].set_xlabel('Epoca'); axes[i].set_ylabel(ylab); axes[i].legend()
    plt.tight_layout()
    plt.savefig(path, bbox_inches='tight')
    if show: plt.show()
    plt.close()

def save_combined_confusion_matrices(labels, preds, path, show=False):
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    cm = confusion_matrix(labels, preds, labels=list(range(5)))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', xticklabels=CLASS_NAMES, yticklabels=CLASS_NAMES, ax=axes[0], annot_kws={"size": 16, "weight": "bold"})
    axes[0].set_title('Matrice Confuzie (Absoluta)'); axes[0].set_xlabel('Predictie (Model)'); axes[0].set_ylabel('Realitate (Adevar)')
    cm_norm = confusion_matrix(labels, preds, labels=list(range(5)), normalize='true')
    sns.heatmap(cm_norm, annot=True, fmt='.2f', cmap='Blues', xticklabels=CLASS_NAMES, yticklabels=CLASS_NAMES, vmin=0, vmax=1, ax=axes[1], annot_kws={"size": 16, "weight": "bold"})
    axes[1].set_title('Matrice Confuzie (Normalizata)'); axes[1].set_xlabel('Predictie (Model)'); axes[1].set_ylabel('Realitate (Adevar)')
    plt.tight_layout()
    plt.savefig(path, bbox_inches='tight')
    if show: plt.show()
    plt.close()

def save_precision_recall_f1(labels, preds, base_name, results_dirs, show=False):
    precision, recall, f1, support = precision_recall_fscore_support(labels, preds, labels=list(range(5)), zero_division=0)
    x = np.arange(len(CLASS_NAMES)); width = 0.25
    plt.figure(figsize=(10, 6))
    plt.bar(x - width, precision, width, label='Precision'); plt.bar(x, recall, width, label='Recall'); plt.bar(x + width, f1, width, label='F1')
    plt.xticks(x, CLASS_NAMES); plt.ylim(0, 1); plt.xlabel('Clasa'); plt.ylabel('Scor'); plt.title('Precision / Recall / F1 pe clase'); plt.legend(); plt.grid(axis='y', alpha=0.25)
    prf1_path = os.path.join(results_dirs['precision_recall_f1'], f"prf1_{base_name}.png")
    plt.savefig(prf1_path, bbox_inches='tight')
    if show: plt.show()
    plt.close()
    report = classification_report(labels, preds, labels=list(range(5)), target_names=CLASS_NAMES, zero_division=0)
    report_path = os.path.join(results_dirs['classification_reports'], f"classification_report_{base_name}.txt")
    with open(report_path, 'w', encoding='utf-8') as f: f.write(report)
    metrics_path = os.path.join(results_dirs['precision_recall_f1'], f"prf1_{base_name}.csv")
    with open(metrics_path, 'w', encoding='utf-8') as f:
        f.write('class,precision,recall,f1,support\n')
        for c, p, r, f1_val, s in zip(CLASS_NAMES, precision, recall, f1, support): f.write(f'{c},{p:.6f},{r:.6f},{f1_val:.6f},{int(s)}\n')
    return prf1_path, report_path, metrics_path, report

def save_roc_curve(labels, probs, base_name, results_dirs, show=False):
    labels = np.asarray(labels); probs = np.asarray(probs); y_true = label_binarize(labels, classes=list(range(5)))
    plt.figure(figsize=(8, 6)); plotted_any = False
    for i, class_name in enumerate(CLASS_NAMES):
        if y_true[:, i].sum() in [0, len(y_true)]: continue
        fpr, tpr, _ = roc_curve(y_true[:, i], probs[:, i])
        plt.plot(fpr, tpr, label=f'Clasa {class_name} (AUC={auc(fpr, tpr):.3f})')
        plotted_any = True
    if plotted_any:
        try: plt.plot(*roc_curve(y_true.ravel(), probs.ravel())[:2], linestyle='--', color='black', label=f'Micro (AUC={auc(*roc_curve(y_true.ravel(), probs.ravel())[:2]):.3f})')
        except Exception: pass
    plt.plot([0, 1], [0, 1], linestyle=':', color='gray'); plt.xlabel('False Positive Rate'); plt.ylabel('True Positive Rate'); plt.title('Curbe ROC multiclasa'); plt.legend(loc='lower right'); plt.grid(alpha=0.25)
    roc_path = os.path.join(results_dirs['roc'], f"roc_{base_name}.png")
    plt.savefig(roc_path, bbox_inches='tight')
    if show: plt.show()
    plt.close()
    return roc_path

def find_last_conv_layer(model):
    for name, module in model.named_modules():
        if isinstance(module, torch.nn.Conv2d): last_name, last_module = name, module
    try: return last_name, last_module
    except NameError: raise RuntimeError("Nu am gasit niciun strat Conv2d pentru Grad-CAM.")

def save_gradcam_overlay_all_classes(model, data_loader, loss_name, device, base_name, results_dirs, show=False):
    try: layer_name, target_layer = find_last_conv_layer(model)
    except RuntimeError as e: print(f"Grad-CAM sarit: {e}"); return None
    model.eval()
    class_images = {}
    for imgs, labels in data_loader:
        for i, lbl in enumerate(labels.tolist()):
            if lbl not in class_images: class_images[lbl] = imgs[i].unsqueeze(0)
        if len(class_images) == 5: break
    if not class_images: return None

    fig, axes = plt.subplots(2, 5, figsize=(20, 8))
    fig.suptitle(f"Grad-CAM 5 Clase (Layer: {layer_name})", fontsize=16)

    for c in range(5):
        ax_orig, ax_cam = axes[0, c], axes[1, c]
        if c not in class_images:
            ax_orig.axis('off'); ax_cam.axis('off'); continue
        
        img_tensor = class_images[c].to(device)
        activations, gradients = [], []
        fh = target_layer.register_forward_hook(lambda _, __, out: activations.append(out.detach()))
        bh = target_layer.register_full_backward_hook(lambda _, __, gout: gradients.append(gout[0].detach()))

        model.zero_grad(set_to_none=True)
        outputs = model(img_tensor)
        preds = get_predictions(outputs, loss_name)
        outputs[0, c].backward()

        cam = F.relu(torch.sum(gradients[-1][0].mean(dim=(1, 2), keepdim=True) * activations[-1][0], dim=0))
        cam = ((cam - cam.min()) / (cam.max() - cam.min())) if cam.max() > cam.min() else torch.zeros_like(cam)
        cam = F.interpolate(cam.unsqueeze(0).unsqueeze(0), size=img_tensor.shape[-2:], mode='bilinear', align_corners=False).squeeze().cpu().numpy()

        image = denormalize_image(img_tensor[0])
        overlay = np.clip((0.55 * image) + (0.45 * plt.cm.jet(cam)[..., :3]), 0, 1)

        ax_orig.imshow(image); ax_orig.set_title(f'Original (Adevărat: {c})'); ax_orig.axis('off')
        ax_cam.imshow(overlay); ax_cam.set_title(f'Grad-CAM (Predicție: {preds[0].item()})'); ax_cam.axis('off')
        fh.remove(); bh.remove()

    plt.tight_layout()
    gradcam_path = os.path.join(results_dirs['gradcam'], f"gradcam_5clase_{base_name}.png")
    plt.savefig(gradcam_path, bbox_inches='tight')
    if show: plt.show()
    plt.close()
    return gradcam_path

# ==============================================================================
# Inima antrenamentului / evaluarii - run_one_epoch 
# ==============================================================================
def compute_extra_metrics(labels, preds):
    try: qwk = cohen_kappa_score(labels, preds, weights='quadratic')
    except: qwk = 0.0
    try: macro_f1 = f1_score(labels, preds, labels=list(range(5)), average='macro', zero_division=0)
    except: macro_f1 = 0.0
    try: balanced_acc = balanced_accuracy_score(labels, preds)
    except: balanced_acc = 0.0
    return qwk, macro_f1, balanced_acc

def run_one_epoch(model, loader, criterion, optimizer, device, loss_name, train=True, desc="", 
                  scaler=None, use_amp=False, grad_clip=0.0, ema=None, use_tta=False):
    model.train() if train else model.eval()
    
    total_loss, correct, total = 0.0, 0, 0
    all_preds, all_labels, all_probs = [], [], []
    tta_active = use_tta and not train and loss_name.lower() not in ['bce_ordinal', 'ordinal']

    with torch.set_grad_enabled(train):
        progress = tqdm(loader, desc=desc, leave=False)
        for imgs, labels in progress:
            imgs, labels = imgs.to(device), labels.to(device)

            if train and optimizer is not None:
                optimizer.zero_grad(set_to_none=True)

            with torch.amp.autocast(device.type, enabled=use_amp):
                if tta_active:
                    outputs = (model(imgs) + model(torch.flip(imgs, dims=[3]))) / 2.0
                else:
                    outputs = model(imgs)
                loss = compute_loss(criterion, outputs, labels, loss_name, device)

            if train and optimizer is not None and scaler is not None:
                scaler.scale(loss).backward()
                if grad_clip > 0:
                    scaler.unscale_(optimizer)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
                scaler.step(optimizer)
                scaler.update()
                if ema is not None: ema.update(model)

            batch_size = imgs.size(0)
            total_loss += loss.item() * batch_size
            preds = get_predictions(outputs, loss_name)
            correct += (preds == labels).sum().item()
            total += batch_size
            
            if not train:
                all_preds.extend(preds.cpu().numpy())
                all_labels.extend(labels.cpu().numpy())
                all_probs.extend(F.softmax(outputs, dim=1).cpu().numpy())

            progress.set_postfix({'loss': f"{loss.item():.4f}"})

    avg_loss = total_loss / max(total, 1)
    acc = correct / max(total, 1)

    if train:
        return avg_loss, acc
    else:
        try: auc_val = roc_auc_score(all_labels, all_probs, multi_class='ovr', average='macro')
        except: auc_val = 0.0
        qwk, macro_f1, balanced_acc = compute_extra_metrics(all_labels, all_preds)
        return avg_loss, acc, auc_val, qwk, macro_f1, balanced_acc, all_preds, all_labels, all_probs

# ==============================================================================
# Utilitare Metric Monitor / Final Test
# ==============================================================================
def select_metric(metrics, monitor_metric):
    return metrics.get(monitor_metric, metrics['val_loss'])

def is_lower_better_metric(monitor_metric):
    return monitor_metric == 'val_loss'

def metric_improved(metric, best_metric, monitor_metric, min_delta):
    return metric < best_metric - min_delta if is_lower_better_metric(monitor_metric) else metric > best_metric + min_delta

def run_final_test(model, test_source, test_loader, criterion, args, device, base_name, results_dirs, use_test_suffix):
    result_base_name = make_result_base_name(base_name, test_source, use_test_suffix)
    print("\n" + "=" * 50); print(f"START TEST FINAL: {test_source}"); print("=" * 50)

    test_loss, test_acc, test_auc, test_qwk, test_macro_f1, test_balanced_acc, test_preds, test_labels, test_probs = run_one_epoch(
        model, test_loader, criterion, None, device, args.loss_name, train=False, desc=f"Testare model [{test_source}]", use_tta=args.tta_eval
    )

    print("Rezultate testare finala:")
    print(f"   Dataset test: {test_source}\n   Acuratete: {test_acc * 100:.2f}%\n   Scor AUC:  {test_auc:.4f}\n   QWK:       {test_qwk:.4f}")
    print(f"   Macro F1:  {test_macro_f1:.4f}\n   Bal Acc:   {test_balanced_acc:.4f}\n   Loss:      {test_loss:.4f}\n")

    print("Classification report:")
    prf1_path, report_path, metrics_path, report = save_precision_recall_f1(test_labels, test_preds, result_base_name, results_dirs, show=True)
    print(report)

    cm_path = os.path.join(results_dirs['confusion'], f"cm_combined_{result_base_name}.png")
    save_combined_confusion_matrices(test_labels, test_preds, cm_path, show=True)
    roc_path = save_roc_curve(test_labels, test_probs, result_base_name, results_dirs, show=True)
    gradcam_path = save_gradcam_overlay_all_classes(model, test_loader, args.loss_name, device, result_base_name, results_dirs, show=True)

    print(f"Rezultate pentru test={test_source}:")
    print(f"Matrice confuzie combinata: {cm_path}\nPrecision/Recall/F1: {prf1_path}\nRaport clasificare: {report_path}\nMetrici CSV: {metrics_path}\nROC curve: {roc_path}")
    if gradcam_path: print(f"Grad-CAM 5 clase overlay: {gradcam_path}")

    return {
        'source': test_source, 'loss': test_loss, 'acc': test_acc, 'auc': test_auc, 'qwk': test_qwk,
        'macro_f1': test_macro_f1, 'balanced_acc': test_balanced_acc, 'cm_path': cm_path,
        'prf1_path': prf1_path, 'report_path': report_path, 'metrics_path': metrics_path,
        'roc_path': roc_path, 'gradcam_path': gradcam_path,
    }