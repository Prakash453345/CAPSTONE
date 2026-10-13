# ---- Package and download ----
zp = f"{OUT}/{ZIP_NAME}"
with zipfile.ZipFile(zp + ".part", "w", zipfile.ZIP_DEFLATED) as z:
    for fn in ("s2_report.json", "s2_training_crops_sample.jpg", "s2_test_misses.jpg", "s2_test4_review.jpg", "bengaluru_test4.tar", "bengaluru_test4.json"):
        if os.path.exists(f"{OUT}/{fn}"):
            z.write(f"{OUT}/{fn}", fn)
    z.write(CLS_PATH, "s2_cls.pt")
os.replace(zp + ".part", zp)
print("saved", zp, f"({os.path.getsize(zp) / 1e6:.0f} MB)")
try:
    from google.colab import files as _files
    _files.download(zp)
except Exception:  # noqa: BLE001
    print("Download it from Drive: folder", os.path.basename(OUT))
