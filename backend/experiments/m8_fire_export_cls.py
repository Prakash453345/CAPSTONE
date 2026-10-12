"""Export the Step 2 crop classifier (s2_cls.pt, torch) to ONNX and check it.

    python scripts/m8_fire_export_cls.py \
        itms_fire_v5_step2_results/s2_cls.pt data/models/itms_fire_cls_112.onnx

Checks, and fails loudly on any: the .pt file's sha256 is the one the
Step 2 verdict was made with; the ONNX softmax agrees with the torch softmax to
1e-4 on 64 random crops (batch sizes 1 and 64, so the batch axis really is
dynamic). Needs torch + torchvision + onnx + onnxruntime."""

from __future__ import annotations

import hashlib
import sys

import numpy as np

EXPECTED_SHA256 = "8aa47d958095a976a3afda28d70285d5846bff7a1087952fb7d61603737e4388"


def main(src: str, dst: str) -> None:
    import onnxruntime as ort
    import torch
    from torch import nn
    from torchvision import models

    sha = hashlib.sha256(open(src, "rb").read()).hexdigest()
    if sha != EXPECTED_SHA256:
        raise SystemExit(f"{src}: sha256 {sha} is not the Step 2 classifier ({EXPECTED_SHA256})")
    m = models.efficientnet_b0(weights=None)
    m.classifier[1] = nn.Linear(m.classifier[1].in_features, 3)
    m.load_state_dict(torch.load(src, map_location="cpu"))
    m.eval()
    x = torch.randn(2, 3, 112, 112)
    torch.onnx.export(m, x, dst, input_names=["x"], output_names=["logits"],
                      dynamic_axes={"x": {0: "n"}, "logits": {0: "n"}}, opset_version=17,
                      dynamo=False)
    sess = ort.InferenceSession(dst, providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(0)
    for n in (1, 64):
        xb = rng.normal(size=(n, 3, 112, 112)).astype(np.float32)
        with torch.no_grad():
            a = torch.softmax(m(torch.from_numpy(xb)), 1).numpy()
        b = np.exp(sess.run(None, {"x": xb})[0])
        b = b / b.sum(1, keepdims=True)
        err = float(np.abs(a - b).max())
        print(f"batch {n}: max |softmax difference| = {err:.2e}")
        if err > 1e-4:
            raise SystemExit("ONNX export does not match the torch model")
    print("ok:", dst, hashlib.sha256(open(dst, "rb").read()).hexdigest())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
