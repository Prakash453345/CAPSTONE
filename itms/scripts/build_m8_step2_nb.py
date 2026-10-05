"""Build notebooks/m8_fire_smoke_v5_step2.ipynb from the v5 Step 1 notebook's setup cells plus the Step 2 cells.
Usage: python build_m8_step2_nb.py [SRC_NOTEBOOK] [CELLS_DIR] [DEST]   (defaults: the repo's Step 1 notebook, m8_fire_step2_cells/ next to this script, notebooks/)"""
import hashlib, json, os, sys
B = os.path.expanduser('~/mnt/capstone/itms')
src = sys.argv[1] if len(sys.argv) > 1 else f'{B}/notebooks/m8_fire_smoke_v5_step1.ipynb'
cdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'm8_fire_step2_cells')
dst = sys.argv[3] if len(sys.argv) > 3 else f'{B}/notebooks/m8_fire_smoke_v5_step2.ipynb'
nb = json.load(open(src))
cells = nb['cells']
def code(s): return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.splitlines(True)}
def md(s): return {"cell_type": "markdown", "metadata": {}, "source": s.splitlines(True)}
intro = md("""# ITMS M8: fire and smoke detector, version 5, Step 2 (a second-stage crop classifier on the version 4 detector)

Targets were written down BEFORE this run: `itms/baselines/2026-10-03_m8_fire_v5_step2/TARGETS_LOCKED.md`. They do not change after it starts.

The detector (version 4 weights) proposes boxes at a low confidence. A small EfficientNet-B0 looks at each box and says fire, smoke or not.
An image alarms only if the classifier agrees with the detector. The classifier is trained on TRAINING images only: negatives come from
images with no fire or smoke label (detector false alarms, flame-coloured blobs in Bengaluru frames, random boxes); detector boxes inside
labelled images that match no label are ignored (they may be fire nobody boxed). The two probability thresholds are chosen on
VALIDATION only. Then A, N, P (D-Fire test), C (held-out FASDD street fires) and B4 (250 NEW Bengaluru frames) are scored once.

Run all cells, in order. It needs the Step 1 Drive folder `itms_fire_v5_step1` (it re-uses its caches and the B3 frames) and the v4 inputs as before.
""")
out = [intro]
for i in range(1, 10):
    c = json.loads(json.dumps(cells[i]))
    if i == 1:
        s = ''.join(c['source']).replace('ZIP_NAME = "itms_fire_v5_step1_results.zip"', 'ZIP_NAME = "itms_fire_v5_step2_results.zip"')
        assert 'step2_results' in s
        s += ('\n# ---- Step 2 (locked in TARGETS_LOCKED.md) ----\nN_TEST4 = 250                    # NEW Bengaluru test frames (B4), scored once\n'
              'TARGET_N_DFIRE_FA = 0.10         # N: D-Fire test images with no fire or smoke that alarm\n'
              'TARGET_P_PRECISION = 0.90        # P: image-level precision on the D-Fire test\n'
              'TARGET_B4_MAX_SHARE = 0.01       # 250 frames: at most 2 may alarm\n')
        c['source'] = s.splitlines(True)
    out.append(c)
for f in ('c1_crops.py', 'c2_train.py', 'c3_select.py', 'c4_fresh.py', 'c5_score.py', 'c6_pack.py'):
    out.append(code(open(os.path.join(cdir, f)).read()))
nb['cells'] = out
json.dump(nb, open(dst, 'w'), indent=1)
for i, c in enumerate(out):
    if c['cell_type'] == 'code':
        compile(''.join(c['source']), f'cell{i}', 'exec')
print(dst, hashlib.md5(open(dst, 'rb').read()).hexdigest(), len(out), 'cells, syntax ok')
