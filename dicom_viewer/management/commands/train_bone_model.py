"""
Django management command: train the BoneSegNet bone-segmentation model.

Strategy: pseudo-label training
  1. Load CT DICOM series from the database (or a supplied directory).
  2. For each series, generate bone masks using the classical HU pipeline
     (BoneMLEngine._segment_classical) — these become the training targets.
  3. Train BoneSegNet (ConvNeXt-Small encoder + UNet decoder) to replicate
     and generalise the classical pipeline.
  4. Save the best checkpoint (.pth state-dict) and a TorchScript export (.pt).

2.5D input: 3 axial slices stacked [prev, curr, next] → (3, H, W) tensor.
Loss: 0.5 × BCE + 0.5 × Dice (handles class imbalance without pos_weight tuning).

Usage
-----
    python manage.py train_bone_model
    python manage.py train_bone_model --epochs 100 --lr 5e-5 --batch 8
    python manage.py train_bone_model --output /data/media/models/bone_seg.pth
    python manage.py train_bone_model --series-ids 31 32 33
    python manage.py train_bone_model --series-ids 31,32,33

After training set BONE_ML_MODEL_PATH to the .pth (or .pt) output path.
"""

import os
import logging
import time

import numpy as np
import pydicom
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DICOM volume loader (mirrors logic in reconstruction.py)
# ---------------------------------------------------------------------------

def _load_series_volume(series):
    """Load a DicomImage queryset into a float32 HU ndarray (Z, H, W)."""
    from worklist.models import DicomImage
    media_root = settings.MEDIA_ROOT
    images = DicomImage.objects.filter(series=series).order_by(
        'instance_number', 'slice_location'
    )
    slices = []
    for img in images:
        fpath = os.path.join(media_root, str(img.file_path))
        if not os.path.exists(fpath):
            continue
        try:
            ds = pydicom.dcmread(fpath, stop_before_pixels=False)
            arr = ds.pixel_array.astype(np.float32)
            slope = float(getattr(ds, 'RescaleSlope', 1))
            intercept = float(getattr(ds, 'RescaleIntercept', 0))
            arr = arr * slope + intercept   # → Hounsfield units
            slices.append(arr)
        except Exception as exc:
            logger.debug('skip %s: %s', fpath, exc)
    if not slices:
        return None
    return np.stack(slices, axis=0)   # (Z, H, W)


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

class _BoneDataset:
    """
    In-memory 2.5D slice dataset built from a list of (volume, mask) pairs.

    Each sample: x=(3,256,256) float32 in [-1,1], y=(1,256,256) float32 in [0,1]
    """

    TARGET_SIZE = 256

    def __init__(self, volumes_masks, augment=True):
        import torch
        self._augment = augment
        self._items = []   # list of (x_tensor, y_tensor)
        self._build(volumes_masks)

    def _norm_slice(self, sl):
        """Bone-window normalisation WW=2000 WL=300 → [-1, 1]."""
        return np.clip((sl.astype(np.float32) - 300.0) / 1000.0, -1.0, 1.0)

    def _resize(self, arr, size):
        """Resize (H, W) array to (size, size) using bilinear interpolation."""
        from scipy.ndimage import zoom
        h, w = arr.shape
        if h == size and w == size:
            return arr
        return zoom(arr, (size / h, size / w), order=1)

    def _build(self, volumes_masks):
        import torch
        S = self.TARGET_SIZE
        for vol, mask in volumes_masks:
            n = vol.shape[0]
            for i in range(n):
                prev = self._norm_slice(vol[max(0, i - 1)])
                curr = self._norm_slice(vol[i])
                nxt  = self._norm_slice(vol[min(n - 1, i + 1)])

                prev = self._resize(prev, S)
                curr = self._resize(curr, S)
                nxt  = self._resize(nxt, S)
                msk  = self._resize(mask[i].astype(np.float32), S)

                x = torch.tensor(
                    np.stack([prev, curr, nxt], axis=0), dtype=torch.float32
                )
                y = torch.tensor(msk[None], dtype=torch.float32)
                self._items.append((x, y))

    def __len__(self):
        return len(self._items)

    def __getitem__(self, idx):
        x, y = self._items[idx]
        if self._augment:
            x, y = self._maybe_augment(x, y)
        return x, y

    @staticmethod
    def _maybe_augment(x, y):
        import torch
        # horizontal flip
        if np.random.rand() < 0.5:
            x = torch.flip(x, dims=[-1])
            y = torch.flip(y, dims=[-1])
        # vertical flip
        if np.random.rand() < 0.5:
            x = torch.flip(x, dims=[-2])
            y = torch.flip(y, dims=[-2])
        # brightness jitter (±10 %)
        x = x + (np.random.rand() - 0.5) * 0.2
        x = torch.clamp(x, -1.0, 1.0)
        return x, y


# ---------------------------------------------------------------------------
# Loss
# ---------------------------------------------------------------------------

def _bce_dice_loss(pred, target, eps=1e-6):
    """0.5 × BCE + 0.5 × Dice.  Both inputs are (B, 1, H, W) in [0, 1]."""
    import torch.nn.functional as F
    bce = F.binary_cross_entropy(pred, target, reduction='mean')
    pred_flat   = pred.view(-1)
    target_flat = target.view(-1)
    intersection = (pred_flat * target_flat).sum()
    dice = 1.0 - (2.0 * intersection + eps) / (
        pred_flat.sum() + target_flat.sum() + eps
    )
    return 0.5 * bce + 0.5 * dice


# ---------------------------------------------------------------------------
# Internet dataset downloader for bone CT volumes
# ---------------------------------------------------------------------------

def _download_bone_volumes(tmpdir: str):
    """
    Download publicly available CT volumes with bone content from HuggingFace Hub
    to supplement locally uploaded PACS data.

    Current sources:
      - TOTALSEGMENTATOR_DATASET (sampled subset via HF datasets)
        provides abdomen/thorax CT scans from which bone masks are derived
        using the classical HU pipeline (same pseudo-label strategy).
      - Falls back to synthetic random bone phantoms when no network access.

    Returns list of float32 ndarrays (Z, H, W) representing HU volumes.
    """
    import os
    import tempfile
    import numpy as np

    downloaded = []

    # Try TotalSegmentator subset on HuggingFace (no auth required)
    try:
        from datasets import load_dataset
        print("  Downloading CT bone volumes from HuggingFace (streaming) …")
        ds = load_dataset(
            "drguilhermedossantos/BodyCT-segmentation",
            split="train",
            streaming=True,
            trust_remote_code=True,
        )
        added = 0
        for row in ds:
            if added >= 5:   # limit to 5 volumes per download run
                break
            try:
                import SimpleITK as sitk
                from io import BytesIO
                # Dataset may provide image bytes or PIL images
                img_bytes = row.get("image") or row.get("ct") or row.get("nifti")
                if img_bytes is None:
                    continue
                if hasattr(img_bytes, "tobytes"):
                    raw = img_bytes.tobytes()
                elif isinstance(img_bytes, (bytes, bytearray)):
                    raw = bytes(img_bytes)
                else:
                    continue
                tmp_path = os.path.join(tmpdir, f"dl_{added}.nii.gz")
                with open(tmp_path, "wb") as f:
                    f.write(raw)
                sitk_img = sitk.ReadImage(tmp_path)
                vol = sitk.GetArrayFromImage(sitk_img).astype(np.float32)
                if vol.ndim == 3 and vol.shape[0] >= 16:
                    downloaded.append(vol)
                    added += 1
            except Exception as inner:
                logger.debug("HF row error: %s", inner)
        print(f"  Downloaded {len(downloaded)} CT volume(s) from HuggingFace.")
    except Exception as exc:
        logger.warning("HuggingFace bone download failed (%s); using synthetic phantoms.", exc)

    # Synthetic fallback: build simple bone phantom for minimal testing
    if not downloaded:
        print("  Generating synthetic bone phantoms (fallback) …")
        yy, xx = np.mgrid[0:256, 0:256]
        for _ in range(3):
            vol = np.random.uniform(-500, 200, (32, 256, 256)).astype(np.float32)
            # Insert synthetic cortical bone cylinder (vectorised — avoids a
            # 32*256*256 pure-Python triple loop, which is both slow and
            # unnecessary on constrained/CPU-only hardware)
            cy, cx, r = 128, 128, 40
            d = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
            cortical = (d > r - 4) & (d < r)
            marrow = d < r - 4
            vol[:, cortical] = 700.0   # cortical bone HU
            vol[:, marrow] = 100.0     # marrow
            downloaded.append(vol)

    return downloaded


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = 'Train BoneSegNet on CT DICOM data using pseudo-label segmentation.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--epochs', type=int, default=50,
            help='Number of training epochs (default: 50).'
        )
        parser.add_argument(
            '--lr', type=float, default=1e-4,
            help='Learning rate (default: 1e-4).'
        )
        parser.add_argument(
            '--batch', type=int, default=4,
            help='Batch size (default: 4; reduce if OOM).'
        )
        parser.add_argument(
            '--output', default=None,
            help='Output path for state-dict (.pth).  Default: <MEDIA_ROOT>/models/bone_seg.pth'
        )
        parser.add_argument(
            '--series-ids', default=None,
            help='Comma-separated series IDs to train on.  Default: all CT series with ≥16 slices.'
        )
        parser.add_argument(
            '--freeze-epochs', type=int, default=10,
            help='Epochs to train decoder only (encoder frozen).  Default: 10.'
        )
        parser.add_argument(
            '--min-slices', type=int, default=16,
            help='Minimum slice count to include a series.  Default: 16.'
        )
        parser.add_argument(
            '--val-split', type=float, default=0.15,
            help='Fraction of slices held out for validation.  Default: 0.15.'
        )
        parser.add_argument(
            '--download', action='store_true',
            help='Download public CT bone datasets from HuggingFace/web to supplement PACS data.'
        )
        parser.add_argument(
            '--resume', default=None,
            help='Path to an existing .pth checkpoint to resume/fine-tune from (continuous learning).'
        )

    def handle(self, *args, **options):
        try:
            import torch
            from torch.utils.data import DataLoader, Subset
        except ImportError:
            raise CommandError('PyTorch not installed.  Run: pip install torch torchvision')

        output_path = options['output'] or os.path.join(
            settings.MEDIA_ROOT, 'models', 'bone_seg.pth'
        )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        ts_path = output_path.replace('.pth', '.pt')

        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.stdout.write(f'Device: {device}')

        # ── 0. Resume / continuous-learning checkpoint ────────────────────
        resume_path = options.get('resume')
        if resume_path and os.path.exists(resume_path):
            self.stdout.write(f'Resuming from checkpoint: {resume_path}')
        elif resume_path:
            self.stderr.write(f'Warning: resume path not found ({resume_path}); starting fresh.')
            resume_path = None
        else:
            # Auto-detect latest checkpoint for continuous learning
            auto_ckpt = output_path
            if os.path.exists(auto_ckpt):
                resume_path = auto_ckpt
                self.stdout.write(f'Continuous learning: resuming from existing {auto_ckpt}')

        # ── 1. Gather series ──────────────────────────────────────────────
        from worklist.models import Series, DicomImage
        from dicom_viewer.bone_ml import BoneMLEngine

        if options['series_ids']:
            ids = [int(x.strip()) for x in options['series_ids'].replace(',', ' ').split()]
            queryset = Series.objects.filter(id__in=ids)
        else:
            queryset = Series.objects.filter(modality__in=['CT', 'CTA', 'CBCT'])

        eligible = []
        for s in queryset:
            cnt = DicomImage.objects.filter(series=s).count()
            if cnt >= options['min_slices']:
                eligible.append((s, cnt))

        if not eligible:
            raise CommandError(
                'No eligible CT series found.  Upload CT studies first, '
                'or lower --min-slices.'
            )

        self.stdout.write(f'Found {len(eligible)} eligible series:')
        for s, cnt in eligible:
            self.stdout.write(f'  Series {s.id}: {s.series_description!r}  ({cnt} slices)')

        # ── 2. Load volumes + generate pseudo-labels ──────────────────────
        self.stdout.write('\nGenerating pseudo-labels (classical bone segmentation)...')
        volumes_masks = []
        for s, cnt in eligible:
            self.stdout.write(f'  Loading series {s.id} ({cnt} slices)...', ending=' ')
            self.stdout.flush()
            t0 = time.time()
            vol = _load_series_volume(s)
            if vol is None or vol.shape[0] < options['min_slices']:
                self.stdout.write('SKIP (failed to load)')
                continue
            mask_prob = BoneMLEngine._segment_classical(vol, spacing=None)
            mask_bin  = (mask_prob >= 0.5).astype(np.float32)
            bone_frac = mask_bin.mean()
            elapsed = time.time() - t0
            self.stdout.write(
                f'OK  shape={vol.shape}  bone={bone_frac:.1%}  {elapsed:.1f}s'
            )
            volumes_masks.append((vol, mask_bin))

        # ── 2b. Download public bone CT data from internet ────────────────
        if options.get('download'):
            import tempfile
            self.stdout.write('\nDownloading public CT bone volumes from internet …')
            tmpdir = tempfile.mkdtemp(prefix='bone_dl_')
            try:
                dl_vols = _download_bone_volumes(tmpdir)
                self.stdout.write(f'  Received {len(dl_vols)} extra volume(s); pseudo-labelling …')
                for vol in dl_vols:
                    try:
                        if vol is None or vol.ndim != 3 or vol.shape[0] < options['min_slices']:
                            continue
                        mask_prob = BoneMLEngine._segment_classical(vol, spacing=None)
                        mask_bin  = (mask_prob >= 0.5).astype(np.float32)
                        volumes_masks.append((vol, mask_bin))
                        self.stdout.write(
                            f'    Added downloaded volume shape={vol.shape}  '
                            f'bone={mask_bin.mean():.1%}'
                        )
                    except Exception as exc:
                        self.stdout.write(f'    Skip: {exc}')
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f'  Download step failed: {exc}'))

        if not volumes_masks:
            raise CommandError('All series failed to load.  Check MEDIA_ROOT and file paths.')

        total_slices = sum(v.shape[0] for v, _ in volumes_masks)
        self.stdout.write(f'\nTotal slices for training: {total_slices}')

        # ── 3. Build dataset + split ──────────────────────────────────────
        self.stdout.write('Building 2.5D slice dataset...')
        full_ds = _BoneDataset(volumes_masks, augment=True)
        n_total = len(full_ds)
        n_val   = max(1, int(n_total * options['val_split']))
        n_train = n_total - n_val

        indices = np.random.permutation(n_total)
        train_idx = indices[:n_train].tolist()
        val_idx   = indices[n_train:].tolist()

        train_ds = Subset(full_ds, train_idx)
        val_ds   = Subset(full_ds, val_idx)

        # validation set without augmentation
        val_ds_clean = _BoneDataset(volumes_masks, augment=False)
        val_ds_clean = Subset(val_ds_clean, val_idx)

        train_loader = DataLoader(train_ds, batch_size=options['batch'],
                                  shuffle=True,  num_workers=0, pin_memory=False)
        val_loader   = DataLoader(val_ds_clean, batch_size=options['batch'],
                                  shuffle=False, num_workers=0, pin_memory=False)

        self.stdout.write(
            f'Train: {n_train} slices | Val: {n_val} slices | '
            f'Batch: {options["batch"]}'
        )

        # ── 4. Build model (with optional resume for continuous learning) ─
        from dicom_viewer.bone_ml import build_for_training
        self.stdout.write('\nBuilding BoneSegNet (ConvNeXt-Small + UNet decoder)...')
        model = build_for_training(pretrained=(resume_path is None)).to(device)
        if resume_path and os.path.exists(resume_path):
            try:
                ckpt = torch.load(resume_path, map_location=device)
                if isinstance(ckpt, dict) and 'model_state_dict' in ckpt:
                    ckpt = ckpt['model_state_dict']
                model.load_state_dict(ckpt, strict=False)
                self.stdout.write(
                    self.style.SUCCESS(f'  Weights loaded from {resume_path} (continuous learning)')
                )
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(f'  Could not load checkpoint ({exc}); training from scratch.')
                )

        # Freeze encoder for first N epochs (warm-up decoder)
        freeze_epochs = min(options['freeze_epochs'], options['epochs'])
        for p in model.encoder.parameters():
            p.requires_grad = False
        decoder_params = [p for p in model.parameters() if p.requires_grad]
        self.stdout.write(
            f'Encoder frozen for first {freeze_epochs} epoch(s); '
            f'decoder-only params: {sum(p.numel() for p in decoder_params):,}'
        )

        optimizer = torch.optim.AdamW(decoder_params, lr=options['lr'],
                                      weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=options['epochs'] - freeze_epochs, eta_min=1e-6
        )

        best_val_loss = float('inf')
        best_state    = None

        # ── 5. Training loop ──────────────────────────────────────────────
        self.stdout.write('\n' + '─' * 60)
        self.stdout.write(
            f'{"Epoch":>5} | {"Train loss":>10} | {"Val loss":>10} | '
            f'{"Val Dice":>9} | {"LR":>8}'
        )
        self.stdout.write('─' * 60)

        for epoch in range(1, options['epochs'] + 1):
            # Unfreeze encoder after warm-up
            if epoch == freeze_epochs + 1:
                for p in model.encoder.parameters():
                    p.requires_grad = True
                all_params = list(model.parameters())
                optimizer = torch.optim.AdamW(all_params, lr=options['lr'] * 0.1,
                                              weight_decay=1e-4)
                scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
                    optimizer,
                    T_max=options['epochs'] - freeze_epochs,
                    eta_min=1e-6
                )
                self.stdout.write(
                    f'  → Epoch {epoch}: encoder unfrozen, LR reset to '
                    f'{options["lr"] * 0.1:.2e}'
                )

            # Train
            model.train()
            train_losses = []
            for xb, yb in train_loader:
                xb, yb = xb.to(device), yb.to(device)
                optimizer.zero_grad()
                pred = model(xb)
                loss = _bce_dice_loss(pred, yb)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                train_losses.append(loss.item())

            if epoch > freeze_epochs:
                scheduler.step()

            # Validate
            model.eval()
            val_losses, val_dices = [], []
            with torch.no_grad():
                for xb, yb in val_loader:
                    xb, yb = xb.to(device), yb.to(device)
                    pred = model(xb)
                    val_losses.append(_bce_dice_loss(pred, yb).item())
                    # per-batch Dice
                    p_flat = (pred >= 0.5).float().view(-1)
                    y_flat = yb.view(-1)
                    inter  = (p_flat * y_flat).sum()
                    dice   = (2 * inter + 1e-6) / (p_flat.sum() + y_flat.sum() + 1e-6)
                    val_dices.append(dice.item())

            tr_loss  = np.mean(train_losses)
            vl_loss  = np.mean(val_losses)
            vl_dice  = np.mean(val_dices)
            cur_lr   = optimizer.param_groups[0]['lr']

            self.stdout.write(
                f'{epoch:>5} | {tr_loss:>10.4f} | {vl_loss:>10.4f} | '
                f'{vl_dice:>9.4f} | {cur_lr:>8.2e}'
            )
            self.stdout.flush()

            if vl_loss < best_val_loss:
                best_val_loss = vl_loss
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                # Save checkpoint immediately so training can be interrupted
                torch.save(best_state, output_path)

        # ── 6. Save final weights ─────────────────────────────────────────
        self.stdout.write('─' * 60)
        if best_state is None:
            raise CommandError('Training produced no valid checkpoint.')

        torch.save(best_state, output_path)
        self.stdout.write(self.style.SUCCESS(f'\nBest checkpoint saved → {output_path}'))

        # TorchScript export for faster inference
        try:
            model.load_state_dict(best_state)
            model.eval().to('cpu')
            dummy = torch.zeros(1, 3, 256, 256)
            scripted = torch.jit.trace(model, dummy)
            scripted.save(ts_path)
            self.stdout.write(self.style.SUCCESS(f'TorchScript export saved → {ts_path}'))
        except Exception as exc:
            self.stdout.write(
                self.style.WARNING(f'TorchScript export failed (state-dict .pth still usable): {exc}')
            )

        self.stdout.write(
            f'\nBest val loss: {best_val_loss:.4f}'
            f'\n\nTo activate the trained model, set in .env.docker or .env:'
            f'\n  BONE_ML_MODEL_PATH={ts_path}'
            f'\n\nThen restart the web and celery services.'
        )
