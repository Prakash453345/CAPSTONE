import json, os, hashlib
B=os.path.expanduser('~/mnt/capstone/itms')
nb=json.load(open(f'{B}/notebooks/m8_fire_smoke_v5_step1.ipynb'))
cells=nb['cells']
def code(src):
    return {"cell_type":"code","metadata":{},"execution_count":None,"outputs":[],"source":src.splitlines(True)}
def md(src):
    return {"cell_type":"markdown","metadata":{},"source":src.splitlines(True)}
intro=md("""# ITMS M8: false positives and false negatives of the v4 weights at the v5 Step 1 thresholds (VALIDATION images only)

**Nothing is trained or chosen here, and no test image is used.** Using the validation split only keeps the test sets clean, so fixes
designed from this analysis can still be judged fairly later. It reports where the false positives (duplicate, wrong class, poorly placed,
background) and false negatives (nothing found, found below threshold, found as the other class) come from, by class and box size,
plus a gallery of the 24 most confident false positives and 24 RANDOM misses (seeded, not picked by eye).
""")
out=[intro]
for i in range(1,9):
    c=json.loads(json.dumps(cells[i]))
    if i==1:
        s=''.join(c['source']).replace('ZIP_NAME = "itms_fire_v5_step1_results.zip"','ZIP_NAME = "itms_fire_v5_errors_results.zip"')
        assert 'errors_results' in s
        c['source']=s.splitlines(True)
    out.append(c)
out.append(code(open(os.path.expanduser('~/v5build/errors_cell.py')).read()))
out.append(code('''# ---- Package and download ----
zp = f"{OUT}/{ZIP_NAME}"
with zipfile.ZipFile(zp + ".part", "w", zipfile.ZIP_DEFLATED) as z:
    for fn in ("errors_val.json", "val_false_positive_boxes.json", "val_fp_top24.jpg", "val_fn_random24.jpg"):
        if os.path.exists(f"{OUT}/{fn}"):
            z.write(f"{OUT}/{fn}", fn)
os.replace(zp + ".part", zp)
print("saved", zp, f"({os.path.getsize(zp) / 1e6:.1f} MB)")
try:
    from google.colab import files as _files
    _files.download(zp)
except Exception:  # noqa: BLE001
    print("Download it from Drive: folder", os.path.basename(OUT))
'''))
nb['cells']=out
dst=f'{B}/notebooks/m8_fire_smoke_v5_errors.ipynb'
json.dump(nb,open(dst,'w'),indent=1)
print(dst,hashlib.md5(open(dst,'rb').read()).hexdigest(),len(out),'cells')
# syntax check of every code cell
for i,c in enumerate(out):
    if c['cell_type']=='code':
        compile(''.join(c['source']),f'cell{i}','exec')
print('syntax ok')
