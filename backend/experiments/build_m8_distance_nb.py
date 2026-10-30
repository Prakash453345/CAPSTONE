import json, os, hashlib
B=os.path.expanduser('~/mnt/capstone/itms')
nb=json.load(open(f'{B}/notebooks/m8_fire_smoke_v5_step1.ipynb'))
cells=nb['cells']
def code(src): return {"cell_type":"code","metadata":{},"execution_count":None,"outputs":[],"source":src.splitlines(True)}
def md(src): return {"cell_type":"markdown","metadata":{},"source":src.splitlines(True)}
intro=md("""# ITMS M8: how far is validation from training? (v4 weights, v5 Step 1 thresholds)

**Nothing is trained or chosen, and no test image is scored.** D-Fire's own validation split shares videos with its training split, so validation
recall (97%) is well above test recall (89%). This notebook measures how far each validation image is from its nearest training image (dhash,
256 bits), reports recall and false alarms by distance (near-copy, probably the same video, an unseen scene), and compares those distances with
the D-Fire test images (distances only). It also saves the list of validation images that are an unseen scene, for a stricter validation set later.
""")
out=[intro]
for i in range(1,10):
    c=json.loads(json.dumps(cells[i]))
    if i==1:
        s=''.join(c['source']).replace('ZIP_NAME = "itms_fire_v5_step1_results.zip"','ZIP_NAME = "itms_fire_v5_distance_results.zip"')
        assert 'distance_results' in s
        c['source']=s.splitlines(True)
    out.append(c)
out.append(code(open(os.path.expanduser('~/v5build/dist_cell.py')).read()))
out.append(code('''# ---- Package and download ----
zp = f"{OUT}/{ZIP_NAME}"
with zipfile.ZipFile(zp + ".part", "w", zipfile.ZIP_DEFLATED) as z:
    for fn in ("val_distance.json", "val_unseen_scene_stems.json"):
        z.write(f"{OUT}/{fn}", fn)
os.replace(zp + ".part", zp)
print("saved", zp)
try:
    from google.colab import files as _files
    _files.download(zp)
except Exception:  # noqa: BLE001
    print("Download it from Drive: folder", os.path.basename(OUT))
'''))
nb['cells']=out
dst=f'{B}/notebooks/m8_fire_smoke_v5_distance.ipynb'
json.dump(nb,open(dst,'w'),indent=1)
print(dst,hashlib.md5(open(dst,'rb').read()).hexdigest(),len(out),'cells')
for i,c in enumerate(out):
    if c['cell_type']=='code': compile(''.join(c['source']),f'cell{i}','exec')
print('syntax ok')
