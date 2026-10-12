import json, os, hashlib
B=os.path.expanduser('~/mnt/capstone/itms')
nb=json.load(open(f'{B}/notebooks/m8_fire_smoke_v5_step1.ipynb'))
cells=nb['cells']
def code(src):
    return {"cell_type":"code","metadata":{},"execution_count":None,"outputs":[],"source":src.splitlines(True)}
def md(src):
    return {"cell_type":"markdown","metadata":{},"source":src.splitlines(True)}
intro=md("""# ITMS M8: fire and smoke detector, box-level metrics for v4 weights at the v5 Step 1 thresholds

**Nothing is trained or chosen here.** This notebook re-uses the v5 Step 1 setup (same Drive folder, so the cached dataset and
`fire_report.json` are re-used) and adds: mAP50, mAP50-95, per-class precision / recall / F1 (Ultralytics validation on the
D-Fire test split), and box-level precision / recall / F1 at the v5 thresholds (match: same class, IoU >= 0.5).
Everything is *reported, not judged*. Run all cells; the results zip downloads at the end.
""")
out=[intro]
for i in range(1,9):
    c=json.loads(json.dumps(cells[i]))
    if i==1:
        s=''.join(c['source']).replace('ZIP_NAME = "itms_fire_v5_step1_results.zip"','ZIP_NAME = "itms_fire_v5_metrics_results.zip"')
        assert 'metrics_results' in s
        c['source']=s.splitlines(True)
    out.append(c)
out.append(code(open(os.path.expanduser('~/v5build/metrics_cell.py')).read()))
out.append(code('''# ---- Package and download ----
zp = f"{OUT}/{ZIP_NAME}"
with zipfile.ZipFile(zp + ".part", "w", zipfile.ZIP_DEFLATED) as z:
    z.write(f"{OUT}/box_metrics.json", "box_metrics.json")
    for root, _, fs in os.walk(f"{OUT}/val_test"):
        for fn in fs:
            full = os.path.join(root, fn)
            z.write(full, os.path.relpath(full, OUT))
os.replace(zp + ".part", zp)
print("saved", zp, f"({os.path.getsize(zp) / 1e6:.1f} MB)")
try:
    from google.colab import files as _files
    _files.download(zp)
except Exception:  # noqa: BLE001
    print("Download it from Drive: folder", os.path.basename(OUT))
'''))
nb['cells']=out
dst=f'{B}/notebooks/m8_fire_smoke_v5_metrics.ipynb'
json.dump(nb,open(dst,'w'),indent=1)
print(dst,hashlib.md5(open(dst,'rb').read()).hexdigest(),len(out),'cells')
# syntax check of every code cell
for i,c in enumerate(out):
    if c['cell_type']=='code':
        compile(''.join(c['source']),f'cell{i}','exec')
print('syntax ok')
