import json, os, glob, hashlib, types, shutil
import numpy as np, cv2, torch, torch.nn as nn
nb = json.load(open('m8_fire_smoke_v5_step2b.ipynb'))
S = lambda c: ''.join(c['source'])
code = [S(c) for c in nb['cells'] if c['cell_type']=='code']
get = lambda p: next(c for c in code if c.startswith(p))
OUT='/home/claude/f2b/out2'; shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT+'/s2')
from torchvision import models
def make_model(pretrained=True):
    m = models.efficientnet_b0(weights=None); m.classifier[1] = nn.Linear(m.classifier[1].in_features, 3); return m
CDEV = torch.device('cpu')
clf = make_model(); clf_old = make_model()
torch.save(clf.state_dict(), OUT+'/s2/s2_cls.pt')
sha = lambda p: hashlib.sha256(open(p,'rb').read()).hexdigest()
json.dump({'classifier_sha256': sha(OUT+'/s2/s2_cls.pt'), 'choice': {'chosen': {'p_fire': .8, 'p_smoke': .9}},
           'test': {'recall_any': .9, 'false_alarms_on_negatives': .08, 'precision': .91}, 'heldout': {'street_recall': .97}, 'test4': {'alarms': 1}}, open(OUT+'/s2_report.json','w'))
class R:
    def __init__(s, n): s.boxes = types.SimpleNamespace(cls=types.SimpleNamespace(tolist=lambda: [0]*n), xyxy=types.SimpleNamespace(tolist=lambda: [[10,10,90,90]]*n))
class Det:
    def predict(s, imgs, **k): return [R(1) for _ in imgs]
fr = sorted(glob.glob('/home/claude/w/data/fresh/val_sample/*.jpg'))
T5 = fr[:40]; STREET = fr[40:75]
def to_tensor(xb):
    MEAN = torch.tensor([0.485,0.456,0.406]).view(1,3,1,1); STD = torch.tensor([0.229,0.224,0.225]).view(1,3,1,1)
    t = torch.from_numpy(xb[..., ::-1].copy()).permute(0,3,1,2).float()/255.0; return (t-MEAN)/STD
def crop_box(img, b): x1,y1,x2,y2 = map(int,b); return cv2.resize(img[y1:y2, x1:x2], (112,112))
exec(get('# ---- Step 2b: picture degradations').split('# a look at')[0], g := dict(np=np, cv2=cv2))
alarm_src = get('# ---- Step 2: image scores'); 
exec(alarm_src[alarm_src.index('def alarm2'):alarm_src.index('if "choice" not in r2')], h := {'np': np, 'PF': .8, 'PS': .9})
G = dict(np=np, cv2=cv2, torch=torch, os=os, json=json, OUT=OUT, sha256_file=sha, make_model=make_model, CDEV=CDEV, clf=clf, det=Det(),
         SIZE=640, DET_CONF=.05, crop_box=crop_box, to_tensor=to_tensor, alarm2=h['alarm2'], PF=.8, PS=.9, T5=T5,
         CONDITIONS=g['CONDITIONS'], TV_FP=np.zeros((3,32),np.uint8), NEAR_HELDOUT_BITS=40,
         r2={'test': {'recall_any': .9,'false_alarms_on_negatives':.08,'precision':.92}, 'heldout': {'street_recall': .95}, 'test4': {'alarms': 1}},
         save_r2=lambda: None, TARGET_A_DFIRE_RECALL=.85, TARGET_C_STREET_RECALL=.8, TARGET_N_DFIRE_FA=.1, TARGET_P_PRECISION=.9)
sel = {'heldout': [{'stem': os.path.basename(p)[:-4], 'label': 'V'} for p in STREET]}
G['extract_fasdd'] = lambda: ('/x', sel)
G['dhash16'] = lambda img: np.full(32, 255, np.uint8)
G['hamming_min'] = lambda a, b: np.full(len(a), 200)
import cv2 as _c
orig = _c.imread
_c.imread = lambda p, *a: orig(p if os.path.exists(p) else STREET[int(os.path.basename(p)[:-4][-1]) % len(STREET)] if False else p, *a)
# heldout paths: map '/x/heldout/images/<stem>.jpg' to the real file
real = {os.path.basename(p): p for p in STREET}
_c.imread = lambda p, *a: orig(real.get(os.path.basename(p), p), *a)
src = get('# ---- Step 2b: the judged comparison')
G['T5'] = T5[:40]
exec(src, G)
print(json.dumps(G['r2']['verdict_2b'])[:600])
