"""
Django management command: train a chest X-ray multi-label classifier.

Strategy: fine-tune DenseNet-121 (ImageNet pretrained, via torchvision) for
14-class CXR pathology detection using one of two label sources:

  1. NIH ChestX-ray14 CSV  (--nih-csv path/to/Data_Entry_2017.csv)
     + image directory     (--nih-images path/to/images/)
     The official NIH dataset (112,120 frontal CXR, 14 labels). Available at
     https://nihcc.app.box.com/v/ChestXray-NIHCC or via Kaggle.

  2. --download  (no extra files needed)
     Auto-downloads public CXR datasets from HuggingFace Hub:
       a) hf-vision/chest-xray-pneumonia  (~1.3 GB, Normal/Pneumonia labels)
       b) alkzar90/NIH-Chest-X-ray-dataset  (if small enough to cache, 14 labels)
     Images are cached in HuggingFace's local cache (~/.cache/huggingface/).

  3. Pseudo-label mode (no extra flags, uses DICOMs already in PACS)
     Uses CXR DICOMs already stored in the PACS database. A pretrained
     CheXNet-style model from Hugging Face auto-labels each image so that
     at least some supervision is available even without external data.

All sources can be combined; just specify multiple options.

Labels (NIH ChestX-ray14 / CheXNet standard):
    Atelectasis, Cardiomegaly, Consolidation, Edema, Effusion, Emphysema,
    Fibrosis, Hernia, Infiltration, Mass, Nodule, Pleural_Thickening,
    Pneumonia, Pneumothorax

DISCLAIMER: The AI determines the PRESENCE of findings; it never modifies
pixel data. DICOM images are read-only throughout training and inference.

Usage
-----
    # Auto-download public data + PACS DICOMs:
    python manage.py train_cxr_classifier --download

    # Quick test run (downloads ~1.3 GB, uses 500 samples):
    python manage.py train_cxr_classifier --download --max-samples 500 --epochs 5

    # NIH full dataset:
    python manage.py train_cxr_classifier --nih-csv /data/Data_Entry_2017.csv \\
        --nih-images /data/images --epochs 30

    # Custom output:
    python manage.py train_cxr_classifier --download --output /media/models/cxr_v1.pth

After training, set CXR_ML_MODEL_PATH to the .pth (or .pt TorchScript) file.
"""

from __future__ import annotations

import csv
import logging
import os
import time
from pathlib import Path
from typing import List, Tuple, Optional

import numpy as np
import pydicom
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 14 standard CheXNet / NIH pathology labels
# ---------------------------------------------------------------------------
CXR_LABELS: List[str] = [
    "Atelectasis", "Cardiomegaly", "Consolidation", "Edema",
    "Effusion", "Emphysema", "Fibrosis", "Hernia",
    "Infiltration", "Mass", "Nodule", "Pleural_Thickening",
    "Pneumonia", "Pneumothorax",
]
NUM_CLASSES = len(CXR_LABELS)
TARGET_SIZE = 224   # DenseNet-121 standard input size


# ---------------------------------------------------------------------------
# DICOM pixel loading helpers
# ---------------------------------------------------------------------------

def _dicom_to_uint8(fpath: str) -> Optional[np.ndarray]:
    """
    Read a DICOM file and return a (H, W) uint8 greyscale array, or None on
    failure.  Only pixel data is extracted — DICOM tags are never written.
    """
    try:
        ds = pydicom.dcmread(fpath, stop_before_pixels=False)
        arr = ds.pixel_array.astype(np.float32)
        # Rescale to HU when applicable
        slope = float(getattr(ds, 'RescaleSlope', 1) or 1)
        intercept = float(getattr(ds, 'RescaleIntercept', 0) or 0)
        arr = arr * slope + intercept
        # Normalise to 0-255 using the 2nd/98th percentile
        p2, p98 = np.percentile(arr, 2), np.percentile(arr, 98)
        if p98 > p2:
            arr = np.clip((arr - p2) / (p98 - p2) * 255.0, 0, 255)
        else:
            arr = np.zeros_like(arr)
        return arr.astype(np.uint8)
    except Exception as exc:
        logger.debug("skip %s: %s", fpath, exc)
        return None


# ---------------------------------------------------------------------------
# Dataset classes
# ---------------------------------------------------------------------------

class _CXRDataset:
    """
    In-memory CXR dataset. Each sample:
        x: (3, 224, 224) float32 ImageNet-normalised
        y: (14,) float32 multi-hot label vector
    """

    _MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    _STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def __init__(self, samples: List[Tuple[str, np.ndarray]], augment: bool = True):
        """
        Parameters
        ----------
        samples : list of (image_path_or_sentinel, label_vector_14)
            image_path_or_sentinel — absolute path to a DICOM *or* PNG/JPEG file.
        augment : add random horizontal flips.
        """
        self.samples = samples
        self.augment = augment

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int):
        import torch
        from PIL import Image
        from torchvision import transforms as T

        path, label_vec = self.samples[idx]

        # Load image
        img_arr = None
        ext = os.path.splitext(path)[1].lower()
        if ext in ('.dcm', '.dicom', ''):
            img_arr = _dicom_to_uint8(path)
        if img_arr is None:
            try:
                pil = Image.open(path).convert('L')
                img_arr = np.array(pil, dtype=np.uint8)
            except Exception:
                img_arr = np.zeros((TARGET_SIZE, TARGET_SIZE), dtype=np.uint8)

        # Resize
        pil = Image.fromarray(img_arr, mode='L').resize(
            (TARGET_SIZE, TARGET_SIZE), Image.BILINEAR
        )
        # Convert to 3-channel
        arr = np.array(pil, dtype=np.float32) / 255.0
        arr = np.stack([arr, arr, arr], axis=0)   # (3, H, W)

        # Augmentation: random horizontal flip
        if self.augment and np.random.random() < 0.5:
            arr = np.flip(arr, axis=2).copy()

        # ImageNet normalise
        for c in range(3):
            arr[c] = (arr[c] - self._MEAN[c]) / self._STD[c]

        x = torch.from_numpy(arr)
        y = torch.from_numpy(label_vec.astype(np.float32))
        return x, y


# ---------------------------------------------------------------------------
# NIH CSV loader
# ---------------------------------------------------------------------------

def _load_nih_samples(csv_path: str, images_dir: str) -> List[Tuple[str, np.ndarray]]:
    """Parse Data_Entry_2017.csv into (image_path, label_vector) pairs."""
    label_to_idx = {l: i for i, l in enumerate(CXR_LABELS)}
    samples = []
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            fname = row.get('Image Index', '').strip()
            if not fname:
                continue
            fpath = os.path.join(images_dir, fname)
            if not os.path.exists(fpath):
                continue
            findings_str = row.get('Finding Labels', 'No Finding').strip()
            vec = np.zeros(NUM_CLASSES, dtype=np.float32)
            if findings_str != 'No Finding':
                for finding in findings_str.split('|'):
                    idx = label_to_idx.get(finding.strip())
                    if idx is not None:
                        vec[idx] = 1.0
            samples.append((fpath, vec))
    return samples


# ---------------------------------------------------------------------------
# HuggingFace dataset downloader
# ---------------------------------------------------------------------------

def _load_hf_samples(max_samples: int = 0) -> List[Tuple[str, np.ndarray]]:
    """
    Download and cache CXR datasets from HuggingFace Hub.

    Tries datasets in order:
      1. hf-vision/chest-xray-pneumonia  (~1.3 GB, split=train+test)
         Labels: NORMAL → zero vector; PNEUMONIA → Pneumonia=1
      2. alkzar90/NIH-Chest-X-ray-dataset (large; only loads if config available)
         Labels: mapped to the 14-class NIH label set

    Returns list of (tmp_image_path, label_vector) pairs.
    Images are PIL images converted to temp PNG bytes — no DICOM involved.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        raise ImportError(
            "The 'datasets' package is required for --download.\n"
            "Install it with:  pip install datasets"
        )

    import tempfile
    pneumonia_idx = CXR_LABELS.index("Pneumonia")
    samples = []
    _tmpdir = tempfile.mkdtemp(prefix="cxr_hf_")

    # ── 1. hf-vision/chest-xray-pneumonia ────────────────────────────────────
    try:
        print("Downloading hf-vision/chest-xray-pneumonia …")
        ds = load_dataset("hf-vision/chest-xray-pneumonia", split="train+test",
                          trust_remote_code=True)
        label_col = "label" if "label" in ds.column_names else "labels"
        img_col   = "image" if "image" in ds.column_names else "img"
        added = 0
        for i, row in enumerate(ds):
            if max_samples and added >= max_samples:
                break
            try:
                pil_img = row[img_col]
                lbl     = row[label_col]
                vec = np.zeros(NUM_CLASSES, dtype=np.float32)
                # label 1 == PNEUMONIA in this dataset
                if int(lbl) == 1:
                    vec[pneumonia_idx] = 1.0
                # Save PIL to temp PNG
                tmp_path = os.path.join(_tmpdir, f"hf_cxrp_{i}.png")
                pil_img.convert("L").save(tmp_path)
                samples.append((tmp_path, vec))
                added += 1
            except Exception:
                pass
        print(f"  chest-xray-pneumonia: {added} samples loaded.")
    except Exception as exc:
        print(f"  chest-xray-pneumonia download failed: {exc}")

    # ── 2. NIH 14-class subset via HuggingFace ────────────────────────────────
    if not max_samples or len(samples) < max_samples:
        label_to_idx = {l: i for i, l in enumerate(CXR_LABELS)}
        remaining = (max_samples - len(samples)) if max_samples else 0
        try:
            print("Downloading alkzar90/NIH-Chest-X-ray-dataset (streaming) …")
            ds_nih = load_dataset("alkzar90/NIH-Chest-X-ray-dataset",
                                  "image-classification", split="train",
                                  streaming=True, trust_remote_code=True)
            added = 0
            for i, row in enumerate(ds_nih):
                if remaining and added >= remaining:
                    break
                try:
                    pil_img = row.get("image") or row.get("img")
                    lbl_str = str(row.get("labels", row.get("label", "No Finding")))
                    vec = np.zeros(NUM_CLASSES, dtype=np.float32)
                    if lbl_str != "No Finding":
                        for part in lbl_str.replace("|", " ").split():
                            idx = label_to_idx.get(part)
                            if idx is not None:
                                vec[idx] = 1.0
                    tmp_path = os.path.join(_tmpdir, f"hf_nih_{i}.png")
                    pil_img.convert("L").save(tmp_path)
                    samples.append((tmp_path, vec))
                    added += 1
                except Exception:
                    pass
            print(f"  NIH-Chest-X-ray-dataset: {added} samples loaded.")
        except Exception as exc:
            print(f"  NIH-Chest-X-ray-dataset download failed (non-fatal): {exc}")

    return samples


# ---------------------------------------------------------------------------
# Pseudo-label generation using a pretrained model from HuggingFace
# ---------------------------------------------------------------------------

def _pseudo_label_samples(dicom_paths: List[str], device) -> List[Tuple[str, np.ndarray]]:
    """
    Use torchvision DenseNet-121 pretrained on ImageNet (with a randomly
    initialised head) to produce "soft" pseudo-labels. In the absence of
    a fine-tuned CheXNet, we fall back to zero vectors (no-finding) and
    rely solely on NIH CSV data if provided. This stub is overridden when
    a fine-tuned HF model is available.
    """
    import torch
    from torchvision import models as tv_models

    logger.info("Generating pseudo-labels for %d DICOMs …", len(dicom_paths))

    # Try to load a published CheXNet-like model from HuggingFace Hub
    pretrained_pipeline = None
    try:
        from transformers import pipeline as hf_pipeline
        # DenseNet-CXR model — if not cached, auto-downloads (~30 MB)
        pretrained_pipeline = hf_pipeline(
            "image-classification",
            model="lxyuan/chest-xray-classification",
            device=0 if device.type == "cuda" else -1,
        )
        logger.info("HuggingFace CXR model loaded for pseudo-labelling.")
    except Exception as exc:
        logger.warning("HF CXR model unavailable (%s); using zero pseudo-labels.", exc)

    hf_label_map = {
        "PNEUMONIA": CXR_LABELS.index("Pneumonia"),
        "NORMAL": -1,
    }

    samples = []
    for fpath in dicom_paths:
        vec = np.zeros(NUM_CLASSES, dtype=np.float32)
        if pretrained_pipeline is not None:
            try:
                from PIL import Image as _PILImage
                arr = _dicom_to_uint8(fpath)
                if arr is not None:
                    pil = _PILImage.fromarray(arr).convert("RGB")
                    preds = pretrained_pipeline(pil, top_k=3)
                    for p in preds:
                        lbl = str(p.get("label", "")).upper()
                        score = float(p.get("score", 0))
                        if score > 0.4 and lbl in hf_label_map and hf_label_map[lbl] >= 0:
                            vec[hf_label_map[lbl]] = 1.0
            except Exception:
                pass
        samples.append((fpath, vec))
    return samples


# ---------------------------------------------------------------------------
# Model: DenseNet-121 with 14-class multi-label head
# ---------------------------------------------------------------------------

def _build_model(device, resume_path: Optional[str] = None):
    """
    DenseNet-121 with a 14-class head.

    If resume_path is given, weights are loaded from that checkpoint instead
    of (re-)downloading ImageNet weights — faster and works offline, which
    matters when "continuing" training on a low-bandwidth server.
    """
    import torch
    import torch.nn as nn
    from torchvision import models as tv_models

    if resume_path:
        model = tv_models.densenet121(weights=None)
        in_features = model.classifier.in_features
        model.classifier = nn.Linear(in_features, NUM_CLASSES)
        ckpt = torch.load(resume_path, map_location=device)
        state_dict = ckpt.get('model_state_dict', ckpt) if isinstance(ckpt, dict) else ckpt
        model.load_state_dict(state_dict, strict=False)
    else:
        model = tv_models.densenet121(weights=tv_models.DenseNet121_Weights.IMAGENET1K_V1)
        in_features = model.classifier.in_features
        model.classifier = nn.Linear(in_features, NUM_CLASSES)
    return model.to(device)


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

def _train(model, train_ds, val_ds, epochs: int, lr: float, batch: int,
           device, output_path: str, freeze_epochs: int = 5,
           early_stop_patience: int = 7):
    import torch
    import torch.nn as nn

    def _make_loader(ds, shuffle):
        return torch.utils.data.DataLoader(
            ds, batch_size=batch, shuffle=shuffle,
            num_workers=0, pin_memory=(device.type == "cuda"),
        )

    train_loader = _make_loader(train_ds, shuffle=True)
    val_loader   = _make_loader(val_ds,   shuffle=False) if val_ds else None

    criterion = nn.BCEWithLogitsLoss()
    params_head = list(model.classifier.parameters())
    params_enc  = [p for n, p in model.named_parameters() if 'classifier' not in n]

    optimizer = torch.optim.Adam([
        {'params': params_enc,  'lr': lr * 0.1},
        {'params': params_head, 'lr': lr},
    ], weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    best_val_loss = float('inf')
    best_state = None
    no_improve = 0  # epochs since last val_loss improvement (early stopping)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    def _save_checkpoint(state):
        torch.save({
            'model_state_dict': state,
            'labels': CXR_LABELS,
            'num_classes': NUM_CLASSES,
            'input_size': TARGET_SIZE,
        }, output_path)

    for epoch in range(1, epochs + 1):
        # Freeze encoder for first `freeze_epochs`
        for p in params_enc:
            p.requires_grad = (epoch > freeze_epochs)

        model.train()
        total_loss = 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            logits = model(x)
            loss = criterion(logits, y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            total_loss += loss.item() * x.size(0)
        scheduler.step()
        avg_train = total_loss / max(len(train_ds), 1)

        val_str = ""
        improved = False
        if val_loader is not None:
            model.eval()
            vl = 0.0
            with torch.no_grad():
                for x, y in val_loader:
                    x, y = x.to(device), y.to(device)
                    vl += criterion(model(x), y).item() * x.size(0)
            avg_val = vl / max(len(val_ds), 1)
            val_str = f"  val_loss={avg_val:.4f}"
            if avg_val < best_val_loss:
                best_val_loss = avg_val
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                _save_checkpoint(best_state)  # save immediately — safe against Ctrl+C
                val_str += "  ✓ saved"
                no_improve = 0
                improved = True
            else:
                no_improve += 1
        else:
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            _save_checkpoint(best_state)

        print(f"Epoch {epoch:3d}/{epochs}  train_loss={avg_train:.4f}{val_str}")

        # Early stopping: halt if val_loss hasn't improved for patience epochs
        if val_loader is not None and no_improve >= early_stop_patience:
            print(f"Early stopping: val_loss flat for {no_improve} epochs.")
            break

    print(f"Best val_loss: {best_val_loss:.4f}  →  {output_path}")

    # TorchScript export
    ts_path = output_path.replace('.pth', '_scripted.pt')
    try:
        if best_state:
            model.load_state_dict(best_state)
        model.eval()
        example = torch.zeros(1, 3, TARGET_SIZE, TARGET_SIZE).to(device)
        scripted = torch.jit.trace(model, example)
        scripted.save(ts_path)
        print(f"TorchScript export  → {ts_path}")
    except Exception as exc:
        logger.warning("TorchScript export failed: %s", exc)

    return best_state


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Train a DenseNet-121 chest X-ray classifier (14-class multi-label)"

    def add_arguments(self, parser):
        parser.add_argument('--epochs',       type=int,   default=30,
                            help='Total training epochs (default: 30)')
        parser.add_argument('--lr',           type=float, default=1e-4,
                            help='Peak learning rate (default: 1e-4)')
        parser.add_argument('--batch',        type=int,   default=16,
                            help='Batch size (default: 16)')
        parser.add_argument('--freeze-epochs', type=int,  default=5,
                            help='Epochs to keep encoder frozen (default: 5)')
        parser.add_argument('--val-split',    type=float, default=0.15,
                            help='Fraction reserved for validation (default: 0.15)')
        parser.add_argument('--download',     action='store_true',
                            help='Auto-download public CXR datasets from HuggingFace Hub')
        parser.add_argument('--nih-csv',      type=str,   default='',
                            help='Path to NIH Data_Entry_2017.csv')
        parser.add_argument('--nih-images',   type=str,   default='',
                            help='Directory of NIH CXR images (alongside --nih-csv)')
        parser.add_argument('--output',       type=str,   default='',
                            help='Output .pth path (default: <MEDIA_ROOT>/models/cxr_classifier.pth)')
        parser.add_argument('--max-samples',  type=int,   default=0,
                            help='Cap total samples for quick test runs (0=unlimited)')
        parser.add_argument('--cpu',          action='store_true',
                            help='Force CPU training')
        parser.add_argument('--resume',       type=str,   default=None,
                            help='Path to an existing .pth checkpoint to resume/fine-tune '
                                 'from (continuous learning). If omitted, auto-resumes from '
                                 '--output when that file already exists.')

    def handle(self, *args, **options):
        import torch

        # ── Device ──────────────────────────────────────────────────────────
        if options['cpu'] or not torch.cuda.is_available():
            device = torch.device('cpu')
        else:
            device = torch.device('cuda')
        print(f"Device: {device}")

        # ── Output path ──────────────────────────────────────────────────────
        media_root = str(getattr(settings, 'MEDIA_ROOT', '.'))
        output_path = options['output'] or os.path.join(
            media_root, 'models', 'cxr_classifier.pth'
        )

        # ── Resume / continuous-learning checkpoint ──────────────────────────
        resume_path = options.get('resume')
        if resume_path and os.path.exists(resume_path):
            print(f"Resuming from checkpoint: {resume_path}")
        elif resume_path:
            self.stderr.write(f"Warning: resume path not found ({resume_path}); starting fresh.")
            resume_path = None
        elif os.path.exists(output_path):
            resume_path = output_path
            print(f"Continuous learning: resuming from existing {output_path}")

        # ── Collect samples ──────────────────────────────────────────────────
        samples = []

        # 1. HuggingFace auto-download
        if options['download']:
            try:
                hf_max = options['max_samples'] if options['max_samples'] else 0
                hf_samples = _load_hf_samples(max_samples=hf_max)
                print(f"HuggingFace samples: {len(hf_samples)}")
                samples.extend(hf_samples)
            except Exception as exc:
                self.stderr.write(f"HF download error: {exc}")

        # 3. NIH CSV
        nih_csv    = options['nih_csv'].strip()
        nih_images = options['nih_images'].strip()
        if nih_csv and os.path.exists(nih_csv):
            if not nih_images or not os.path.isdir(nih_images):
                raise CommandError(
                    "--nih-images must point to the NIH images directory "
                    "when --nih-csv is provided."
                )
            print("Loading NIH ChestX-ray14 CSV …")
            nih_samples = _load_nih_samples(nih_csv, nih_images)
            print(f"  NIH samples loaded: {len(nih_samples)}")
            samples.extend(nih_samples)

        # 4. CXR DICOMs already in the PACS database (pseudo-labelled)
        try:
            from worklist.models import DicomImage, Series
            cxr_modalities = ('CR', 'DX')
            cxr_series = Series.objects.filter(modality__in=cxr_modalities)
            dicom_paths = []
            for s in cxr_series:
                for img in DicomImage.objects.filter(series=s).order_by('instance_number')[:1]:
                    fpath = os.path.join(media_root, str(img.file_path))
                    if os.path.exists(fpath):
                        dicom_paths.append(fpath)
            if dicom_paths:
                print(f"Found {len(dicom_paths)} CXR DICOMs in PACS — pseudo-labelling …")
                pacs_samples = _pseudo_label_samples(dicom_paths, device)
                samples.extend(pacs_samples)
                print(f"  PACS pseudo-label samples: {len(pacs_samples)}")
        except Exception as exc:
            logger.warning("Could not query PACS for CXR DICOMs: %s", exc)

        if not samples:
            raise CommandError(
                "No training data found.\n"
                "Options:\n"
                "  1. Upload chest X-ray DICOMs to the PACS system.\n"
                "  2. Download NIH ChestX-ray14 from https://nihcc.app.box.com/v/ChestXray-NIHCC\n"
                "     then run:  python manage.py train_cxr_classifier \\\n"
                "         --nih-csv /path/to/Data_Entry_2017.csv \\\n"
                "         --nih-images /path/to/images/"
            )

        # Cap sample count for quick test runs
        max_n = options['max_samples']
        if max_n and max_n < len(samples):
            np.random.shuffle(samples)
            samples = samples[:max_n]
            print(f"Capped to {max_n} samples.")

        # ── Train / val split ────────────────────────────────────────────────
        np.random.shuffle(samples)
        val_n = max(1, int(len(samples) * options['val_split']))
        val_samples   = samples[:val_n]
        train_samples = samples[val_n:]
        print(f"Training: {len(train_samples)}  Validation: {len(val_samples)}")

        train_ds = _CXRDataset(train_samples, augment=True)
        val_ds   = _CXRDataset(val_samples,   augment=False)

        # ── Build model ──────────────────────────────────────────────────────
        print("Building DenseNet-121 …" if resume_path else
              "Building DenseNet-121 (ImageNet pretrained) …")
        model = _build_model(device, resume_path=resume_path)
        total_params = sum(p.numel() for p in model.parameters())
        trainable    = sum(p.numel() for p in model.parameters() if p.requires_grad)
        print(f"  Parameters: {total_params:,}  (trainable head: {trainable:,})")

        # ── Train ─────────────────────────────────────────────────────────────
        print(f"\nTraining for {options['epochs']} epoch(s) …\n"
              f"Labels: {', '.join(CXR_LABELS)}\n")
        t0 = time.time()
        _train(
            model, train_ds, val_ds,
            epochs=options['epochs'],
            lr=options['lr'],
            batch=options['batch'],
            device=device,
            output_path=output_path,
            freeze_epochs=options['freeze_epochs'],
        )
        elapsed = time.time() - t0
        print(f"\nTraining complete in {elapsed/60:.1f} min.")
        print(f"Set CXR_ML_MODEL_PATH={output_path}")
        print("Labels order preserved in checkpoint['labels'] key.")
