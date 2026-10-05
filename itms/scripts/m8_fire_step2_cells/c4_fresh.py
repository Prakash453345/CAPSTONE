# ---- NEW Bengaluru test frames (B4): never used, other cameras than everything any step saw (B3 included) ----
V4F = f"{WORK}/v4fresh"
if not os.path.isdir(V4F):
    os.makedirs(V4F, exist_ok=True)
    subprocess.run(["tar", "-xf", f"{V4}/bengaluru_fresh.tar", "-C", V4F], check=True)

def _fps(paths):
    return np.stack([dhash16(cv2.imread(p)) for p in paths]) if paths else np.zeros((0, 32), np.uint8)

V4_TEST2 = sorted(glob.glob(f"{V4F}/test2/*.jpg"))
V4_OTHER = sorted(glob.glob(f"{V4F}/val/*.jpg") + glob.glob(f"{V4F}/pool/*.jpg"))
assert len(V4_TEST2) == N_V4_TEST2, len(V4_TEST2)
B3_TAR = f"{OUT}/bengaluru_test3.tar"
if not os.path.exists(B3_TAR):
    raise SystemExit(f"STOP: the B3 frames are not in {OUT} (bengaluru_test3.tar). B4 must be far from them; put the Step 1 folder back.")
B3_DIR = f"{WORK}/uvh_v5"
if not os.path.isdir(f"{B3_DIR}/test3"):
    os.makedirs(B3_DIR, exist_ok=True)
    subprocess.run(["tar", "-xf", B3_TAR, "-C", B3_DIR], check=True)
B3 = sorted(glob.glob(f"{B3_DIR}/test3/*.jpg"))
assert len(B3) == N_TEST3, len(B3)
blr_idx = [i for i in range(len(TV_STEM)) if str(TV_STEM[i]).startswith(("blr_", "blrh_"))]
BANK = np.vstack([TEST_FPS, TV_FP[blr_idx], _fps(V4_TEST2), _fps(V4_OTHER), _fps(B3)])
print("camera bank (old test, training/validation Bengaluru, v4 fresh, B3):", BANK.shape[0])
T4_DIR = f"{WORK}/uvh_s2"
T4_CACHE, T4_INFO = f"{OUT}/bengaluru_test4.tar", f"{OUT}/bengaluru_test4.json"
B3_NAMES = {os.path.basename(p) for p in B3}

def _fresh_test4():
    from concurrent.futures import ThreadPoolExecutor
    files = hf_list()
    pool = sorted(set(files) - set(TEST["sha256"]) - B3_NAMES)
    random.Random(SEED + 7).shuffle(pool)
    os.makedirs(f"{T4_DIR}/test4", exist_ok=True)
    kept, skipped, i, t0 = [], Counter(), 0, time.time()
    bank = BANK
    cand = pool[:MAX_CANDIDATES]
    with ThreadPoolExecutor(8) as ex:
        while len(kept) < N_TEST4 and i < len(cand):
            chunk = cand[i:i + 48]
            i += len(chunk)
            for name, data in ex.map(lambda n: (n, hf_get(files[n])), chunk):
                if len(kept) >= N_TEST4:
                    break
                if data is None:
                    skipped["file missing"] += 1
                    continue
                if hashlib.sha256(data).hexdigest() in TEST_SHA:
                    skipped["identical to an old test frame"] += 1
                    continue
                img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    skipped["does not open"] += 1
                    continue
                fp = dhash16(img)
                d = hamming_min(fp[None], bank)[0]
                if d <= DUP_BITS:
                    skipped["duplicate of a frame already known"] += 1
                    continue
                if d <= SAME_CAMERA_BITS:
                    skipped["same camera as a known frame"] += 1
                    continue
                bank = np.vstack([bank, fp[None]])
                write_image(img, f"{T4_DIR}/test4/{os.path.splitext(name)[0]}.jpg")
                kept.append(name)
            print(f"  new test frames: {len(kept)}/{N_TEST4} kept, {i} looked at, {sum(skipped.values())} skipped, {time.time() - t0:.0f} s", flush=True)
    return {"source": f"Hugging Face {UVH_REPO} UVH-26-Train/data", "kept": kept, "looked_at": i, "skipped": dict(skipped)}

if os.path.exists(T4_CACHE) and os.path.exists(T4_INFO):
    T4_I = json.load(open(T4_INFO))
    if not os.path.isdir(f"{T4_DIR}/test4"):
        os.makedirs(T4_DIR, exist_ok=True)
        subprocess.run(["tar", "-xf", T4_CACHE, "-C", T4_DIR], check=True)
else:
    try:
        T4_I = _fresh_test4()
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"STOP: could not get the new Bengaluru test frames ({e!r}). They are this step's test; check that this runtime can reach huggingface.co and Run all again (it resumes).")
    if len(T4_I["kept"]) < N_TEST4:
        raise SystemExit(f"STOP: only {len(T4_I['kept'])} frames of {N_TEST4} are far enough from every known camera after {T4_I['looked_at']} looked at ({T4_I['skipped']}). No verdict. Tell Claude.")
    subprocess.run(["tar", "-cf", T4_CACHE + ".part", "-C", T4_DIR, "test4"], check=True)
    os.replace(T4_CACHE + ".part", T4_CACHE)
    json.dump(T4_I, open(T4_INFO, "w"), indent=1)
T4 = sorted(glob.glob(f"{T4_DIR}/test4/*.jpg"))
assert len(T4) == N_TEST4, len(T4)
assert hamming_min(_fps(T4), BANK).min() > SAME_CAMERA_BITS, "a new test frame is the same camera as a known frame"
assert not (B3_NAMES & {os.path.basename(p) for p in T4}), "B4 overlaps B3"
print("B4 frames:", len(T4), "| skipped:", T4_I["skipped"], "| looked at:", T4_I["looked_at"])
r2["test4_source"] = {"looked_at": T4_I["looked_at"], "skipped": T4_I["skipped"], "frames": [os.path.basename(p) for p in T4]}
save_r2()
