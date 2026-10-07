# ---- Step 2: train the crop classifier (fixed recipe from TARGETS_LOCKED.md; the LAST epoch is used) ----
import torch.nn as nn, torch.nn.functional as Fnn
from torchvision import models
CLS_PATH = f"{S2}/s2_cls.pt"
EPOCHS, BATCH_C, LR, WD = 8, 64, 3e-4, 1e-4
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)

def make_model(pretrained=True):
    w = models.EfficientNet_B0_Weights.IMAGENET1K_V1 if pretrained else None
    m = models.efficientnet_b0(weights=w)
    m.classifier[1] = nn.Linear(m.classifier[1].in_features, 3)
    return m

def to_tensor(xb):                 # uint8 BGR (N, H, W, 3) -> normalised RGB float (N, 3, H, W)
    t = torch.from_numpy(xb[..., ::-1].copy()).permute(0, 3, 1, 2).float() / 255.0
    return (t - MEAN) / STD

def augment(t, gen):
    n = t.shape[0]
    flip = torch.rand(n, generator=gen) < 0.5
    t[flip] = torch.flip(t[flip], dims=[3])
    out = torch.empty_like(t)
    for i in range(n):                                   # a random crop of 85-100 % of the side, resized back
        s = int(CROP * (0.85 + 0.15 * torch.rand(1, generator=gen).item()))
        a = int(torch.randint(0, CROP - s + 1, (1,), generator=gen).item())
        b = int(torch.randint(0, CROP - s + 1, (1,), generator=gen).item())
        out[i] = Fnn.interpolate(t[i:i + 1, :, a:a + s, b:b + s], size=(CROP, CROP), mode="bilinear", align_corners=False)[0]
    k = 1 + 0.4 * (torch.rand(n, 1, 1, 1, generator=gen) - 0.5)          # contrast +-20 %
    c = 0.4 * (torch.rand(n, 1, 1, 1, generator=gen) - 0.5)              # brightness +-0.2 (in normalised units)
    return out * k + c

CDEV = torch.device("cuda" if torch.cuda.is_available() else "cpu")
clf = make_model(pretrained=not r2.get("_no_pretrained")).to(CDEV)

@torch.no_grad()
def crop_probs(X, bs=256):
    clf.eval()
    out = []
    for s in range(0, len(X), bs):
        out.append(torch.softmax(clf(to_tensor(X[s:s + bs]).to(CDEV)), 1).cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, 3), np.float32)

if os.path.exists(CLS_PATH):
    clf.load_state_dict(torch.load(CLS_PATH, map_location=CDEV))
    print("classifier restored from Drive:", CLS_PATH)
else:
    gen = torch.Generator().manual_seed(SEED)
    torch.manual_seed(SEED)
    cnt = np.bincount(y_tr, minlength=3).astype(np.float32)
    wts = torch.tensor(cnt.sum() / (3 * np.maximum(cnt, 1)), dtype=torch.float32).to(CDEV)
    opt = torch.optim.AdamW(clf.parameters(), lr=LR, weight_decay=WD)
    steps = EPOCHS * int(np.ceil(len(X_tr) / BATCH_C))
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=steps)
    hist = []
    for ep in range(EPOCHS):
        clf.train()
        perm = torch.randperm(len(X_tr), generator=gen).numpy()
        tot, nb_ = 0.0, 0
        for s in range(0, len(perm), BATCH_C):
            ix = perm[s:s + BATCH_C]
            xb = augment(to_tensor(X_tr[ix]), gen).to(CDEV)
            yb = torch.from_numpy(y_tr[ix]).to(CDEV)
            loss = Fnn.cross_entropy(clf(xb), yb, weight=wts, label_smoothing=0.1)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            tot += float(loss); nb_ += 1
        pv = crop_probs(X_va)
        acc = float((pv.argmax(1) == y_va).mean()) if len(y_va) else None
        hist.append({"epoch": ep + 1, "train_loss": round(tot / max(nb_, 1), 4), "val_crop_accuracy": None if acc is None else round(acc, 4)})
        print(hist[-1], flush=True)
    torch.save(clf.state_dict(), CLS_PATH + ".part")
    os.replace(CLS_PATH + ".part", CLS_PATH)
    r2["train_history"] = hist
pv = crop_probs(X_va)
per = {n: (float((pv[y_va == i].argmax(1) == i).mean()) if (y_va == i).any() else None) for i, n in enumerate(["fire", "smoke", "not"])}
r2["val_crops"] = {"accuracy": float((pv.argmax(1) == y_va).mean()) if len(y_va) else None, "per_class_recall": per, "n": int(len(y_va))}
r2["classifier_sha256"] = sha256_file(CLS_PATH)
save_r2()
print("validation crops (reported only):", json.dumps(r2["val_crops"]), "| classifier sha256:", r2["classifier_sha256"][:16])
