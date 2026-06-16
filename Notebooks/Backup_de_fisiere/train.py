import argparse
import os
import sys
import time
import torch
from torch.utils.data import DataLoader

try: CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError: CURRENT_DIR = os.getcwd()
PARENT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
PROJECT_ROOT = PARENT_DIR
if PARENT_DIR not in sys.path: sys.path.insert(0, PARENT_DIR)

from builder import count_trainable_parameters, format_lrs, get_loss_function, get_model, get_optimizer, set_backbone_trainable
from my_dataset import make_dataset
import utils

def parse_args():
    parser = argparse.ArgumentParser(description="Antrenament DR - dataseturi custom ImageFolder")
    parser.add_argument('--model', type=str, default='resnet50')
    parser.add_argument('--loss_name', type=str, default='ce')
    parser.add_argument('--optimizer', type=str, default='adam')
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--batch_size', type=int, default=32)
    parser.add_argument('--lr', type=float, default=0.0001)
    parser.add_argument('--img_size', type=int, default=224)
    parser.add_argument('--num_workers', type=int, default=0)
    parser.add_argument('--class_weights', type=float, nargs='+', default=None)
    parser.add_argument('--gamma', type=float, default=1.5)
    parser.add_argument('--monitor_metric', type=str, default='qwk', choices=['qwk', 'macro_f1', 'balanced_acc', 'auc', 'acc', 'val_loss'])
    parser.add_argument('--scheduler', type=str, default='plateau', choices=['plateau', 'cosine', 'none'])
    parser.add_argument('--amp', action='store_true')
    parser.add_argument('--grad_clip', type=float, default=0.0)
    parser.add_argument('--ema_decay', type=float, default=0.0)
    parser.add_argument('--model_dropout', type=float, default=0.0)
    parser.add_argument('--freeze_backbone_epochs', type=int, default=0)
    parser.add_argument('--backbone_lr_mult', type=float, default=1.0)
    parser.add_argument('--tta_eval', action='store_true')
    parser.add_argument('--train_augment', type=str, default='basic', choices=['basic', 'none'])
    parser.add_argument('--early_stopping_patience', type=int, default=0)
    parser.add_argument('--early_stopping_min_delta', type=float, default=0.0)
    parser.add_argument('--train_dataset_roots', type=str, nargs='+', required=True)
    parser.add_argument('--train_dataset_names', type=str, nargs='+', default=None)
    parser.add_argument('--test_dataset_roots', type=str, nargs='+', required=True)
    parser.add_argument('--test_dataset_names', type=str, nargs='+', default=None)
    return parser.parse_args()

def main():
    args = parse_args()
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    train_roots = [utils.resolve_dataset_path(path, PROJECT_ROOT) for path in args.train_dataset_roots]
    test_roots = [utils.resolve_dataset_path(path, PROJECT_ROOT) for path in args.test_dataset_roots]
    train_names = [utils.safe_source_name(args.train_dataset_names[i] if args.train_dataset_names else f"train_{i+1}") for i in range(len(train_roots))]
    test_sources = [utils.safe_source_name(args.test_dataset_names[i] if args.test_dataset_names else f"test_{i+1}") for i in range(len(test_roots))]
    test_roots_by_source = dict(zip(test_sources, test_roots))
    train_source = '+'.join(train_names)
    experiment_name = f"{train_source}_to_{'_'.join(test_sources)}"

    train_datasets_viz = {name: make_dataset(root, 'train', args.img_size, args.train_augment) for name, root in zip(train_names, train_roots)}
    test_datasets = {src: make_dataset(root, 'test', args.img_size, args.train_augment) for src, root in test_roots_by_source.items()}

    print("Vizualizam esantioane din seturile de antrenament:")
    utils.show_dataset_samples_grid(train_datasets_viz, title_prefix="Date Antrenament (TRAIN)")
    print("Vizualizam esantioane din seturile de testare:")
    utils.show_dataset_samples_grid(test_datasets, title_prefix="Date Testare (TEST)")

    rezultate_dir = os.path.abspath(os.path.join(CURRENT_DIR, "..", "Rezultate", "New"))
    modele_dir = os.path.join(rezultate_dir, "modele")
    os.makedirs(modele_dir, exist_ok=True)
    results_dirs = utils.make_results_dirs(os.path.join(rezultate_dir, "grafice"))

    print(f"Config: {args.model} | Loss: {args.loss_name} | Opt: {args.optimizer} | LR: {args.lr}")
    print(f"Experiment: {experiment_name} | TRAIN/VAL={train_source} | TEST={', '.join(test_sources)}")
    print(f"Train augment: {args.train_augment} | Monitor metric: {args.monitor_metric} | Scheduler: {args.scheduler}")
    print(f"AMP: {args.amp} | Grad clip: {args.grad_clip} | EMA decay: {args.ema_decay} | TTA eval: {args.tta_eval}")
    print(f"Model dropout: {args.model_dropout} | Freeze backbone epochs: {args.freeze_backbone_epochs} | Backbone LR mult: {args.backbone_lr_mult}")

    train_ds = make_dataset(train_roots, split='train', image_size=args.img_size, train_augment=args.train_augment)
    val_ds = make_dataset(train_roots, split='val', image_size=args.img_size, train_augment=args.train_augment)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)
    test_loaders = {src: DataLoader(ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers) for src, ds in test_datasets.items()}

    if args.loss_name == 'focal_loss': print(f"Focal Loss activat cu gamma={args.gamma}")
    test_sizes = ' | '.join([f"TESTARE[{src}]={len(ds)}" for src, ds in test_datasets.items()])
    print(f"Distributie date: TRAIN={len(train_ds)} | VALIDARE={len(val_ds)} | {test_sizes}")

    model = get_model(args.model, num_classes=5, drop_rate=args.model_dropout).to(device)
    if args.freeze_backbone_epochs > 0:
        set_backbone_trainable(model, trainable=False)
        print(f"Backbone inghetat pentru primele {args.freeze_backbone_epochs} epoci. Parametri antrenabili initial: {count_trainable_parameters(model):,}")

    criterion = get_loss_function(args.loss_name, class_weights=args.class_weights, device=device, gamma=args.gamma)
    optimizer = get_optimizer(model, optimizer_name=args.optimizer, lr=args.lr, backbone_lr_mult=args.backbone_lr_mult)
    
    if args.scheduler == 'plateau':
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min' if utils.is_lower_better_metric(args.monitor_metric) else 'max', factor=0.75, patience=5)
    elif args.scheduler == 'cosine':
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(args.epochs, 1), eta_min=args.lr * 0.01)
    else: scheduler = None

    use_amp = args.amp and device.type == 'cuda'
    scaler = torch.amp.GradScaler(device.type, enabled=use_amp)
    ema = utils.ModelEMA(model, args.ema_decay) if args.ema_decay > 0 else None

    history = {'train_loss': [], 'train_acc': [], 'val_loss': [], 'val_acc': [], 'val_auc': [], 'val_qwk': [], 'val_macro_f1': [], 'val_balanced_acc': []}
    best_metric = float('inf') if utils.is_lower_better_metric(args.monitor_metric) else -float('inf')
    epochs_without_improvement, stopped_early = 0, False
    base_name = utils.make_experiment_base_name(experiment_name, args)
    model_path = os.path.join(modele_dir, f"best_{base_name}.pth")

    # ==============================================================================
    # BUCLA DE ANTRENAMENT (Curata, bazata exclusiv pe run_one_epoch)
    # ==============================================================================
    for epoch in range(args.epochs):
        start_time = time.time()
        if args.freeze_backbone_epochs > 0 and epoch == args.freeze_backbone_epochs:
            set_backbone_trainable(model, trainable=True)
            print(f"Backbone deblocat la epoca {epoch + 1}.")
            
        # 1. ANTRENAMENT
        epoch_train_loss, epoch_train_acc = utils.run_one_epoch(
            model, train_loader, criterion, optimizer, device, args.loss_name, train=True, 
            desc=f"Ep {epoch + 1:02d} [TRAIN]", scaler=scaler, use_amp=use_amp, grad_clip=args.grad_clip, ema=ema
        )
        
        # 2. VALIDARE
        if ema is not None: ema.apply_shadow(model)
        val_loss, val_acc, val_auc, val_qwk, val_macro_f1, val_balanced_acc, _, _, _ = utils.run_one_epoch(
            model, val_loader, criterion, None, device, args.loss_name, train=False, 
            desc=f"Ep {epoch + 1:02d} [VALID]", use_tta=args.tta_eval
        )
        if ema is not None: ema.restore(model)

        history['train_loss'].append(epoch_train_loss); history['train_acc'].append(epoch_train_acc)
        history['val_loss'].append(val_loss); history['val_acc'].append(val_acc); history['val_auc'].append(val_auc)
        history['val_qwk'].append(val_qwk); history['val_macro_f1'].append(val_macro_f1); history['val_balanced_acc'].append(val_balanced_acc)

        metrics = {'acc': val_acc, 'auc': val_auc, 'qwk': val_qwk, 'macro_f1': val_macro_f1, 'balanced_acc': val_balanced_acc, 'val_loss': val_loss}
        metric = utils.select_metric(metrics, args.monitor_metric)
        if scheduler is not None: scheduler.step(metric) if args.scheduler == 'plateau' else scheduler.step()
            
        marker = ""
        if utils.metric_improved(metric, best_metric, args.monitor_metric, args.early_stopping_min_delta):
            best_metric = metric; epochs_without_improvement = 0
            if ema is not None: ema.apply_shadow(model)
            torch.save(model.state_dict(), model_path)
            if ema is not None: ema.restore(model)
            marker = "NOU BEST"
        else: epochs_without_improvement += 1

        print(f"Ep {epoch + 1:02d}/{args.epochs} | T_Loss: {epoch_train_loss:.4f} | V_Loss: {val_loss:.4f} | "
              f"T_Acc: {epoch_train_acc * 100:.1f}% | V_Acc: {val_acc * 100:.1f}% | V_AUC: {val_auc:.4f} | "
              f"V_QWK: {val_qwk:.4f} | V_F1: {val_macro_f1:.4f} | V_BalAcc: {val_balanced_acc:.4f} | "
              f"Best[{args.monitor_metric}]={best_metric:.4f} {marker}")
        print(f"LR curent: {format_lrs(optimizer)}\nDurata epoca: {(time.time() - start_time) / 60:.2f} min")
        
        if args.early_stopping_patience > 0:
            print(f"Early stopping: {epochs_without_improvement}/{args.early_stopping_patience} epoci fara imbunatatire")
            if epochs_without_improvement >= args.early_stopping_patience:
                stopped_early = True
                print(f"Early stopping activat la epoca {epoch + 1}.")
                break

    # ==============================================================================
    # TESTARE FINALA
    # ==============================================================================
    model.load_state_dict(torch.load(model_path, map_location=device))
    history_path = os.path.join(results_dirs['history'], f"istoric_combinat_{base_name}.png")
    utils.save_combined_history(history, history_path, show=True)

    use_test_suffix = len(test_loaders) > 1
    test_results = [utils.run_final_test(model, src, loader, criterion, args, device, base_name, results_dirs, use_test_suffix) for src, loader in test_loaders.items()]

    print(f"\nGata. Model: {model_path}\nGrafic evolutie combinat: {history_path}")
    if stopped_early: print(f"Antrenare oprita anticipat la epoca {epoch + 1}/{args.epochs}.")
    if len(test_results) > 1:
        print("Rezumat testari finale:")
        for r in test_results: print(f"   {r['source']}: Acc={r['acc'] * 100:.2f}% | AUC={r['auc']:.4f} | QWK={r['qwk']:.4f} | F1={r['macro_f1']:.4f}")

if __name__ == '__main__':
    if not hasattr(sys.modules['__main__'], '__spec__'): sys.modules['__main__'].__spec__ = None
    main()
