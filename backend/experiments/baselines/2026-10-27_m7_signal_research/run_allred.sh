cd ./scripts
for net in random_lh arterial_lh grid4_rh_turns berlin_adlershof vijayawada_district amaravati_v2; do
  for mode in fixed ite; do
    if [ $mode = ite ]; then export SIGNAL_ALL_RED=ite; else unset SIGNAL_ALL_RED; fi
    ITMS_SCENARIO=./scenarios/generated/$net python3 m8_closed_loop_gate.py --arms truth --levels light,medium --seed-list 101,102,103 --workers 2 --resume --out baselines/2026-10-27_m7_signal_research/results/${net}_${mode}.json > baselines/2026-10-27_m7_signal_research/results/${net}_${mode}.log 2>&1
  done
done
echo AR_DONE > baselines/2026-10-27_m7_signal_research/results/DONE
