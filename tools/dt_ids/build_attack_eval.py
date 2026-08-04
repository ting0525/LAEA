"""Build an attack evaluation set from a delete=false collection.

Normal-flight collection deletes non-success runs (correct: keeps the training
corpus clean). But detector *evaluation* needs the attack runs -- including the
window between attack onset and failure. So attack runs are collected separately
with EXP_DELETE_ON_NON_SUCCESS=false, then filtered here:

  keep a run iff
    - its kpi_log CSV was retained (log_retained == true), AND
    - the attack actually fired (attack_actual_onset_s > 0), AND
    - the run survived to at least the onset (duration_s >= onset) -- otherwise
      SLAM failed on its own *before* the attack and the run is not attributable.

Kept runs are grouped by scenario "<source>_<mode>_<severity>" into a layout that
tuav/evaluate.py consumes directly:

  out/<scenario>/kpi_log_run_XXX.csv
  out/<scenario>/run_manifest.csv     (per-scenario, carries attack_actual_onset_s)
  out/attack_eval_manifest.csv        (keep/reject decision per run)

Companion to build_run_manifest.py (which flags NORMAL-run quality).

    python3 tools/dt_ids/build_attack_eval.py \
        --logs laea_twin_tools/laea_logs/attack_v1 \
        --out  data/attack_eval
"""
import argparse
import glob
import shutil
from pathlib import Path

import pandas as pd


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


_NONE = {"", "none", "nan", "na", "null"}


def _field(row, key):
    v = str(row.get(key, "") or "").strip()
    return "" if v.lower() in _NONE else v


def decide(row):
    """Return (keep: bool, reason: str, onset_rel: float|None, scenario: str)."""
    src = _field(row, "attack_source")
    mode = _field(row, "attack_mode")
    sev = _field(row, "attack_severity")
    scenario = "_".join([p for p in (src, mode, sev) if p]) or "unknown"

    retained = str(row.get("log_retained", "")).strip().lower() == "true"
    onset = _f(row.get("attack_actual_onset_s")) or _f(row.get("attack_scheduled_onset_s"))
    duration = _f(row.get("duration_s"))

    if not src:
        return False, "no_attack (normal run)", onset, scenario
    if not retained:
        return False, "log_deleted (re-collect with EXP_DELETE_ON_NON_SUCCESS=false)", onset, scenario
    if not onset or onset <= 0:
        return False, "attack_never_fired", onset, scenario
    if duration is not None and duration < onset:
        return False, f"failed_before_onset ({duration:.1f}s < {onset:.1f}s): self-caused, not attributable", onset, scenario
    return True, "keep", onset, scenario


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", required=True, help="a laea_logs collection dir (delete=false attack runs)")
    ap.add_argument("--out", required=True, help="output attack-eval dir")
    ap.add_argument("--copy", action="store_true", help="copy CSVs (default: symlink)")
    args = ap.parse_args()

    logs = Path(args.logs)
    manifest_path = logs / "run_manifest.csv"
    if not manifest_path.exists():
        raise SystemExit(f"no run_manifest.csv in {logs}")
    man = pd.read_csv(manifest_path, dtype=str)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    summary = []
    kept_by_scenario = {}
    for _, row in man.iterrows():
        keep, reason, onset, scenario = decide(row)
        run_id = str(row.get("run_id", "")).strip()
        summary.append({"run_id": run_id, "scenario": scenario, "keep": keep,
                        "reason": reason, "onset_rel_s": onset,
                        "outcome": row.get("outcome", "")})
        if not keep:
            continue
        # find this run's kpi CSV
        matches = glob.glob(str(logs / f"kpi_log_{run_id}.csv")) or \
            glob.glob(str(logs / f"kpi_log_*{run_id}*.csv"))
        if not matches:
            summary[-1]["keep"] = False
            summary[-1]["reason"] = "kpi_csv_not_found"
            continue
        sdir = out / scenario
        sdir.mkdir(parents=True, exist_ok=True)
        dst = sdir / Path(matches[0]).name
        if args.copy:
            shutil.copy(matches[0], dst)
        else:
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            dst.symlink_to(Path(matches[0]).resolve())
        kept_by_scenario.setdefault(scenario, []).append(row)

    # per-scenario manifests (evaluate.py reads attack_actual_onset_s from these)
    for scenario, rows in kept_by_scenario.items():
        pd.DataFrame(rows).to_csv(out / scenario / "run_manifest.csv", index=False)

    sdf = pd.DataFrame(summary)
    sdf.to_csv(out / "attack_eval_manifest.csv", index=False)

    total = len(sdf)
    kept = int(sdf["keep"].sum()) if total else 0
    print(f"[attack_eval] {kept}/{total} runs kept -> {out}")
    if total:
        print("  by scenario:")
        for scenario, n in sdf[sdf["keep"]].groupby("scenario").size().items():
            print(f"    {scenario:34} {n}")
        rej = sdf[~sdf["keep"]]
        if len(rej):
            print("  rejected reasons:")
            for reason, n in rej.groupby("reason").size().items():
                print(f"    {n:3}  {reason}")


if __name__ == "__main__":
    main()
