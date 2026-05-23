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
    classification_report,
    confusion_matrix,
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

from builder import compute_loss, get_loss_function, get_model, get_optimizer, get_predictions
import my_dataset as my_dataset_module

my_dataset_module = importlib.reload(my_dataset_module)
EXPERIMENTS = my_dataset_module.EXPERIMENTS
DATA_SOURCES = my_dataset_module.DATA_SOURCES
make_dataset = my_dataset_module.make_dataset
resolve_experiment = my_dataset_module.resolve_experiment


CLASS_NAMES = ['0', '1', '2', '3', '4']
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406])
IMAGENET_STD = np.array([0.229, 0.224, 0.225])


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


# --- ADAUGAT FUNCTIA LIPSA PENTRU ISTORIC COMBINAT ---
def save_combined_history(history, path, show=False):
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    
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


def save_precision_recall_f1(labels, preds, base_name, grafice_dir, show=False):
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

    prf1_path = os.path.join(grafice_dir, f"prf1_{base_name}.png")
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
    report_path = os.path.join(grafice_dir, f"classification_report_{base_name}.txt")
    with open(report_path, 'w', encoding='utf-8') as report_file:
        report_file.write(report)

    metrics_path = os.path.join(grafice_dir, f"prf1_{base_name}.csv")
    with open(metrics_path, 'w', encoding='utf-8') as metrics_file:
        metrics_file.write('class,precision,recall,f1,support\n')
        for class_name, p, r, f, s in zip(CLASS_NAMES, precision, recall, f1, support):
            metrics_file.write(f'{class_name},{p:.6f},{r:.6f},{f:.6f},{int(s)}\n')

    return prf1_path, report_path, metrics_path, report


def save_roc_curve(labels, probs, base_name, grafice_dir, show=False):
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

    roc_path = os.path.join(grafice_dir, f"roc_{base_name}.png")
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


def save_gradcam_overlay(model, data_loader, loss_name, device, base_name, grafice_dir, show=False):
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

        gradcam_path = os.path.join(grafice_dir, f"gradcam_{base_name}.png")
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


def evaluate(model, data_loader, criterion, loss_name, device, desc):
    model.eval()
    total_loss, correct, total = 0.0, 0, 0
    all_preds, all_labels, all_probs = [], [], []

    with torch.no_grad():
        progress = tqdm(data_loader, desc=desc, leave=False)
        for imgs, labels in progress:
            imgs, labels = imgs.to(device), labels.to(device)
            outputs = model(imgs)
            loss = compute_loss(criterion, outputs, labels, loss_name, device)

            total_loss += loss.item()
            preds = get_predictions(outputs, loss_name)
            correct += (preds == labels).sum().item()
            total += labels.size(0)

            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())
            all_probs.extend(F.softmax(outputs, dim=1).cpu().numpy())

    avg_loss = total_loss / max(len(data_loader), 1)
    acc = correct / max(total, 1)
    try:
        auc = roc_auc_score(all_labels, all_probs, multi_class='ovr', average='macro')
    except Exception:
        auc = 0.0

    return avg_loss, acc, auc, all_preds, all_labels, all_probs


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
    grafice_dir,
    use_test_suffix,
):
    result_base_name = make_result_base_name(base_name, test_source, use_test_suffix)

    print("\n" + "=" * 50)
    print(f"START TEST FINAL: {test_source}")
    print("=" * 50)

    test_loss, test_acc, test_auc, test_preds, test_labels, test_probs = evaluate(
        model,
        test_loader,
        criterion,
        args.loss_name,
        device,
        desc=f"Testare model [{test_source}]",
    )

    print("Rezultate testare finala:")
    print(f"   Dataset test: {test_source}")
    print(f"   Acuratete: {test_acc * 100:.2f}%")
    print(f"   Scor AUC:  {test_auc:.4f}")
    print(f"   Loss:      {test_loss:.4f}\n")

    print("Classification report:")
    prf1_path, report_path, metrics_path, report = save_precision_recall_f1(
        test_labels,
        test_preds,
        result_base_name,
        grafice_dir,
        show=True
    )
    print(report)

    cm_path = os.path.join(grafice_dir, f"cm_{result_base_name}.png")
    save_confusion_matrix(test_labels, test_preds, cm_path, normalized=False, show=True)

    cm_norm_path = os.path.join(grafice_dir, f"cm_norm_{result_base_name}.png")
    save_confusion_matrix(test_labels, test_preds, cm_norm_path, normalized=True, show=True)

    roc_path = save_roc_curve(test_labels, test_probs, result_base_name, grafice_dir, show=True)
    gradcam_path = save_gradcam_overlay(model, test_loader, args.loss_name, device, result_base_name, grafice_dir, show=True)

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
    aptos_root = args.aptos_root or os.path.join(PROJECT_ROOT, 'datasets', 'aptos', 'aptos_ben_graham_matched') # sau aptos_ben_graham
    train_source, test_source = resolve_experiment(args.experiment, args.train_source, args.test_source)
    test_sources = args.test_sources or [test_source]
    val_source = train_source
    experiment_name = args.experiment or f"{train_source}_to_{test_source}"

    rezultate_dir = os.path.join(CURRENT_DIR, "Rezultate")
    modele_dir = os.path.join(rezultate_dir, "modele")
    grafice_dir = os.path.join(rezultate_dir, "grafice")
    os.makedirs(modele_dir, exist_ok=True)
    os.makedirs(grafice_dir, exist_ok=True)

    print(f"Config: {args.model} | Loss: {args.loss_name} | Opt: {args.optimizer} | LR: {args.lr}")
    print(f"Experiment: {experiment_name} | TRAIN/VAL={train_source} | TEST={', '.join(test_sources)}")
    print(f"Train augment: {args.train_augment}")
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

    model = get_model(args.model, num_classes=5).to(device)
    criterion = get_loss_function(args.loss_name, class_weights=args.class_weights, device=device, gamma=args.gamma)
    optimizer = get_optimizer(model, optimizer_name=args.optimizer, lr=args.lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.5, patience=3)

    history = {'train_loss': [], 'val_loss': [], 'val_acc': [], 'val_auc': []}
    best_metric = 0.0
    epochs_without_improvement = 0
    stopped_early = False
    stopped_epoch = None
    base_name = f"{experiment_name}_{args.model}_{args.loss_name}_{args.optimizer}_LR_{args.lr}_Gamma_{args.gamma}"
    model_path = os.path.join(modele_dir, f"best_{base_name}.pth")

    for epoch in range(args.epochs):
        start_time = time.time()
        model.train()
        train_loss = 0.0

        progress = tqdm(train_loader, desc=f"Ep {epoch + 1:02d} [TRAIN]", leave=False)
        for imgs, labels in progress:
            imgs, labels = imgs.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(imgs)
            loss = compute_loss(criterion, outputs, labels, args.loss_name, device)
            loss.backward()
            optimizer.step()

            train_loss += loss.item()
            progress.set_postfix({'loss': f"{loss.item():.4f}"})

        epoch_train_loss = train_loss / max(len(train_loader), 1)
        val_loss, val_acc, val_auc, _, _, _ = evaluate(
            model,
            val_loader,
            criterion,
            args.loss_name,
            device,
            desc=f"Ep {epoch + 1:02d} [VALID]",
        )

        history['train_loss'].append(epoch_train_loss)
        history['val_loss'].append(val_loss)
        history['val_acc'].append(val_acc)
        history['val_auc'].append(val_auc)

        scheduler.step(val_auc)
        metric = val_acc if args.loss_name == 'bce_ordinal' else val_auc
        marker = ""
        if metric > best_metric + args.early_stopping_min_delta:
            best_metric = metric
            epochs_without_improvement = 0
            torch.save(model.state_dict(), model_path)
            marker = "NOU BEST"
        else:
            epochs_without_improvement += 1

        print(
            f"Ep {epoch + 1:02d}/{args.epochs} | "
            f"T_Loss: {epoch_train_loss:.4f} | V_Loss: {val_loss:.4f} | "
            f"V_Acc: {val_acc * 100:.1f}% | V_AUC: {val_auc:.4f} {marker}"
        )
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

    history_path = os.path.join(grafice_dir, f"istoric_combinat_{base_name}.png")
    save_combined_history(history, history_path, show=True)

    loss_path = os.path.join(grafice_dir, f"loss_{base_name}.png")
    save_line_plot(history['train_loss'], 'Loss Antrenament', 'Loss', loss_path, color='blue', label='Train Loss', show=True)

    acc_path = os.path.join(grafice_dir, f"acc_{base_name}.png")
    save_line_plot(history['val_acc'], 'Acuratete Validare', 'Acuratete', acc_path, color='orange', label='Val Acc', show=True)

    auc_path = os.path.join(grafice_dir, f"auc_{base_name}.png")
    save_line_plot(history['val_auc'], 'Scor AUC Validare', 'AUC', auc_path, color='green', label='Val AUC', show=True)

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
            grafice_dir=grafice_dir,
            use_test_suffix=use_test_suffix,
        ))

    print(f"\nGata. Model: {model_path}")
    print(f"Grafic evolutie combinat: {history_path}")
    print(f"Grafic loss: {loss_path}")
    print(f"Grafic acuratete: {acc_path}")
    print(f"Grafic AUC: {auc_path}")
    if stopped_early:
        print(f"Antrenare oprita anticipat la epoca {stopped_epoch}/{args.epochs}.")
    if len(test_results) > 1:
        print("Rezumat testari finale:")
        for result in test_results:
            print(
                f"   {result['source']}: "
                f"Acc={result['acc'] * 100:.2f}% | AUC={result['auc']:.4f} | Loss={result['loss']:.4f}"
            )


if __name__ == '__main__':
    if not hasattr(sys.modules['__main__'], '__spec__'):
        sys.modules['__main__'].__spec__ = None
    main()
