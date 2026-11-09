import sys, time
from audit_lib import RESULTS, dump
import audit_tests2 as T
test = sys.argv[1]
t0 = time.time()
if test == "D":
    r = T.test_D(sys.argv[2], int(sys.argv[3]), sys.argv[4]); name = f"D_{sys.argv[2]}_s{sys.argv[3]}_{sys.argv[4]}"
elif test == "E1":
    r = T.test_E1(sys.argv[2], int(sys.argv[3])); name = f"E1_{sys.argv[2]}_s{sys.argv[3]}"
elif test == "E2":
    r = T.test_E2(sys.argv[2], int(sys.argv[3])); name = f"E2_{sys.argv[2]}_s{sys.argv[3]}"
elif test == "E3":
    r = T.test_E3(sys.argv[2], int(sys.argv[3])); name = f"E3_{sys.argv[2]}_s{sys.argv[3]}"
elif test == "F":
    r = T.test_F(sys.argv[2], int(sys.argv[3])); name = f"F_{sys.argv[2]}_s{sys.argv[3]}"
elif test == "F3":
    r = T.test_F3(); name = "F3_coverage"
r["wall_s"] = round(time.time() - t0, 1)
dump(r, RESULTS / f"{name}.json")
print(name, "done", r["wall_s"], "s")
