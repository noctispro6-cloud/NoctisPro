"""
ML-powered CT bone segmentation engine.

Architecture: ConvNeXt-Small encoder + 5-stage UNet decoder (2.5D per-slice inference).

Input per slice: 3-channel stack [prev_slice, curr_slice, next_slice], each
  normalised to [-1, 1] using bone window (WW=2000, WL=300).

Inference:  batched axial-slice pass → bone probability volume [0..1].
Fallback:   when no trained weights are present, uses enhanced multi-threshold
            HU segmentation that closely follows the X2B paper's morphological
            pipeline (trabecular capture + 3D closing + per-slice hole fill).

Model weights location: settings.BONE_ML_MODEL_PATH
  - TorchScript (.pt):   torch.jit.load()
  - State-dict (.pth):   BoneSegNet.build() + load_state_dict()
  - Absent / None:       classical fallback (no error, graceful degradation)
"""

import logging

import numpy as np
from scipy import ndimage
from skimage import morphology

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------

def _build_model(pretrained: bool = True):
    """Construct BoneSegNet (ConvNeXt-Small + decoder).  Returns None on import failure."""
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
        from torchvision.models import convnext_small, ConvNeXt_Small_Weights
    except ImportError:
        return None

    class _Decoder(nn.Module):
        def __init__(self):
            super().__init__()
            # 5 bilinear upsamples: 8×8 → 256×256  (32× total)
            self.up1 = nn.Sequential(nn.Conv2d(768, 256, 3, padding=1), nn.GELU(),
                                     nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False))
            self.up2 = nn.Sequential(nn.Conv2d(256, 128, 3, padding=1), nn.GELU(),
                                     nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False))
            self.up3 = nn.Sequential(nn.Conv2d(128,  64, 3, padding=1), nn.GELU(),
                                     nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False))
            self.up4 = nn.Sequential(nn.Conv2d( 64,  32, 3, padding=1), nn.GELU(),
                                     nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False))
            self.up5 = nn.Sequential(nn.Conv2d( 32,  16, 3, padding=1), nn.GELU(),
                                     nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False))
            self.head = nn.Conv2d(16, 1, 1)

        def forward(self, x):
            return torch.sigmoid(self.head(
                self.up5(self.up4(self.up3(self.up2(self.up1(x)))))
            ))

    class _BoneSegNet(nn.Module):
        """2.5D bone segmentation: (B,3,H,W) → (B,1,H,W) probability map."""
        def __init__(self, pretrained: bool):
            super().__init__()
            weights = ConvNeXt_Small_Weights.IMAGENET1K_V1 if pretrained else None
            self.encoder = convnext_small(weights=weights).features  # 768-ch @ 1/32
            self.decoder = _Decoder()

        def forward(self, x):
            orig_h, orig_w = x.shape[2], x.shape[3]
            if orig_h != 256 or orig_w != 256:
                x = F.interpolate(x, size=(256, 256), mode='bilinear', align_corners=False)
            feat = self.encoder(x)          # (B, 768, 8, 8)
            prob = self.decoder(feat)       # (B, 1, 256, 256)
            if orig_h != 256 or orig_w != 256:
                prob = F.interpolate(prob, size=(orig_h, orig_w),
                                     mode='bilinear', align_corners=False)
            return prob

    return _BoneSegNet(pretrained=pretrained)


# ---------------------------------------------------------------------------
# Inference engine (singleton)
# ---------------------------------------------------------------------------

class BoneMLEngine:
    """
    Singleton bone segmentation engine.

    Call BoneMLEngine.get() to obtain the shared instance.
    Call .segment(hu_volume, spacing) to get a float32 [0..1] probability volume.
    """

    _instance = None

    @classmethod
    def get(cls) -> 'BoneMLEngine':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._model = None
        self._device = 'cpu'
        self._load()

    def _load(self):
        try:
            import torch
        except ImportError:
            logger.info('BoneMLEngine: torch not available — classical segmentation active')
            return

        self._device = 'cuda' if torch.cuda.is_available() else 'cpu'

        from django.conf import settings
        model_path = getattr(settings, 'BONE_ML_MODEL_PATH', None)

        if not model_path:
            logger.info('BoneMLEngine: BONE_ML_MODEL_PATH not set — classical segmentation active')
            return

        import os
        if not os.path.exists(model_path):
            logger.warning('BoneMLEngine: model path %s missing — classical fallback', model_path)
            return

        # Attempt 1: TorchScript
        try:
            model = torch.jit.load(model_path, map_location=self._device)
            model.eval()
            self._model = model
            logger.info('BoneMLEngine: loaded TorchScript from %s on %s', model_path, self._device)
            return
        except Exception:
            pass

        # Attempt 2: state-dict for BoneSegNet
        try:
            model = _build_model(pretrained=False)
            if model is None:
                return
            state = torch.load(model_path, map_location=self._device, weights_only=True)
            model.load_state_dict(state)
            model.eval()
            self._model = model.to(self._device)
            logger.info('BoneMLEngine: loaded BoneSegNet weights from %s on %s', model_path, self._device)
        except Exception as exc:
            logger.error('BoneMLEngine: failed to load model: %s', exc)

    @property
    def using_ml(self) -> bool:
        return self._model is not None

    def segment(self, hu_volume: np.ndarray, spacing=None) -> np.ndarray:
        """
        Segment bone in a CT HU volume.

        Parameters
        ----------
        hu_volume : ndarray (Z, H, W)  float32 or int16, Hounsfield units
        spacing   : list/tuple (dz, dy, dx) in mm — used only by classical path

        Returns
        -------
        prob_volume : ndarray (Z, H, W) float32 in [0, 1]
        """
        if self.using_ml:
            try:
                return self._infer_ml(hu_volume)
            except Exception as exc:
                logger.warning('ML inference failed, falling back to classical: %s', exc)
        return self._segment_classical(hu_volume, spacing)

    # ------------------------------------------------------------------
    # ML path
    # ------------------------------------------------------------------

    def _infer_ml(self, hu_volume: np.ndarray) -> np.ndarray:
        import torch

        n, H, W = hu_volume.shape
        # Bone window normalisation: WW=2000, WL=300  →  HU ∈ [-700, 1300] → [-1, 1]
        vol = np.clip((hu_volume.astype(np.float32) - 300.0) / 1000.0, -1.0, 1.0)

        prob_vol = np.zeros((n, H, W), dtype=np.float32)
        batch = 8

        with torch.no_grad():
            for start in range(0, n, batch):
                end = min(start + batch, n)
                slices = []
                for i in range(start, end):
                    prev = vol[max(0, i - 1)]
                    curr = vol[i]
                    nxt  = vol[min(n - 1, i + 1)]
                    slices.append(np.stack([prev, curr, nxt], axis=0))

                x = torch.tensor(np.stack(slices, axis=0),
                                 dtype=torch.float32, device=self._device)
                probs = self._model(x)          # (B, 1, H, W) or (B, H, W)
                if probs.dim() == 4:
                    probs = probs.squeeze(1)
                probs_np = probs.cpu().numpy()

                for j, i in enumerate(range(start, end)):
                    prob_vol[i] = probs_np[j]

        return prob_vol

    # ------------------------------------------------------------------
    # Classical fallback — enhanced multi-threshold pipeline (X2B-inspired)
    # ------------------------------------------------------------------

    @staticmethod
    def _segment_classical(hu_volume: np.ndarray, spacing=None) -> np.ndarray:
        """
        Enhanced bone segmentation without a trained model.

        Pipeline (mirrors X2B morphological approach):
          1. Compact bone mask (> 300 HU)
          2. Trabecular capture: (150–300 HU) inside dilated compact bone
          3. 3D binary_opening (ball-1) + binary_closing (ball-3)
          4. Per-slice 2D hole fill  ← critical for medullary canal
          5. Gaussian field (σ=1.5) → smooth marching-cubes boundary
        """
        vol = hu_volume.astype(np.float32)

        # Primary: cortical / dense bone
        compact = vol > 300

        # Secondary: trabecular / spongy bone
        trabecular = (vol > 150) & (vol <= 300)
        compact_dilated = ndimage.binary_dilation(compact, iterations=2)
        bone_mask = compact | (trabecular & compact_dilated)

        # 3-D cleanup
        bone_mask = morphology.opening(bone_mask, morphology.ball(1))
        bone_mask = morphology.closing(bone_mask, morphology.ball(3))

        # Per-slice hole fill (recovers medullary canal and enclosed trabecular spaces)
        for i in range(bone_mask.shape[0]):
            bone_mask[i] = ndimage.binary_fill_holes(bone_mask[i])

        # Smooth boundary field for marching cubes
        prob = ndimage.gaussian_filter(bone_mask.astype(np.float32), sigma=1.5)
        return np.clip(prob, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Training scaffold (run standalone to fine-tune on CT data)
# ---------------------------------------------------------------------------

def build_for_training(pretrained: bool = True):
    """
    Return an untrained or ImageNet-pretrained BoneSegNet ready for fine-tuning.

    Usage
    -----
        model = build_for_training(pretrained=True)
        # freeze encoder for first N epochs, train decoder only
        for p in model.encoder.parameters():
            p.requires_grad = False
        optimizer = torch.optim.AdamW(
            filter(lambda p: p.requires_grad, model.parameters()), lr=1e-4
        )
        # loss: BCE + Dice on (B,1,H,W) masks

    Save for inference
    ------------------
        torch.save(model.state_dict(), 'bone_seg.pth')
        # OR export as TorchScript for faster loading:
        scripted = torch.jit.script(model)
        scripted.save('bone_seg.pt')
    """
    model = _build_model(pretrained=pretrained)
    if model is None:
        raise ImportError('torch / torchvision not installed')
    return model
