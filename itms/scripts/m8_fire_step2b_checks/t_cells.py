import json, os, sys, glob, hashlib, types
import numpy as np, cv2, torch
ip, ipd = types.ModuleType("IPython"), types.ModuleType("IPython.display")
ipd.Image = ipd.display = lambda *a, **k: None
nb = json.load(open('m8_fire_smoke_v5_step2b.ipynb'))
S = lambda c: ''.join(c['source'])
code = [S(c) for c in nb['cells'] if c['cell_type']=='code']
get = lambda p: next(c for c in code if c.startswith(p))
OUT = '/home/claude/f2b/out'; os.makedirs(OUT+'/s2b', exist_ok=True)
g = dict(np=np, cv2=cv2, torch=torch, os=os, json=json, display=lambda *a, **k: None, _Img=lambda *a, **k: None,
         OUT=OUT, SEED=26, CROP=112, S2=OUT+'/s2b', time=__import__('time'))
fr = sorted(glob.glob('/home/claude/w/data/fresh/val_sample/*.jpg'))[:40]
rng = np.random.RandomState(0); X, y = [], []
for k, p in enumerate(fr):
    img = cv2.imread(p); h, w = img.shape[:2]
    for _ in range(8):
        x1, y1 = rng.randint(0, w-200), rng.randint(0, h-200)
        X.append(cv2.resize(img[y1:y1+150, x1:x1+150], (112, 112))); y.append(k % 3)
X = np.stack(X); y = np.array(y)
g.update(X_tr=X[:240], y_tr=y[:240], X_va=X[240:], y_va=y[240:], r2={'_no_pretrained': True}, save_r2=lambda: None,
         sha256_file=lambda p: hashlib.sha256(open(p,'rb').read()).hexdigest())
exec(get('# ---- Step 2b: picture degradations'), g)
print('aug sheet', os.path.exists(OUT+'/s2b_aug_sample.jpg'))
# degrade on a full frame for every condition
im = cv2.imread(fr[0])
for n, fn in g['CONDITIONS'].items():
    o = fn(im, np.random.default_rng(1)); assert o.shape == im.shape and o.dtype == np.uint8, n
g['EPOCHS_OVERRIDE'] = 1
src = get('# ---- Step 2b: train').replace('EPOCHS, BATCH_C, LR, WD = 8, 64, 3e-4, 1e-4', 'EPOCHS, BATCH_C, LR, WD = 1, 32, 3e-4, 1e-4')
exec(src, g)
print('trained, val', g['r2']['val_crops'])
