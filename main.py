"""Railway Block Management - integrated optimization pipeline.

Pipeline
--------
1. Generate simulated BDMS maintenance requests and COA timetable.
2. Calculate transparent, rule-based priority scores.
3. Merge compatible departmental requests on the same section/date.
4. Use OR-Tools CP-SAT to schedule the resulting blocks without overlap.
5. Save the complete decision-ready schedule to CSV.

Run:
    python main.py

For the Streamlit dashboard:
    streamlit run app.py
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

try:
    from ortools.sat.python import cp_model
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError(
        "OR-Tools is required. Install dependencies with: pip install -r requirements.txt"
    ) from exc


DEPARTMENTS = ("Engineering", "TRD", "S&T")
SECTIONS = tuple(f"SEC-{i}" for i in range(1, 6))
TRAIN_PRIORITIES = ("Rajdhani", "Express", "Passenger", "Freight")
DURATION_OPTIONS = (1, 2, 3, 4, 6, 8)
DEFAULT_START_DATE = "2026-09-10"
DAY_HOURS = 24
OUTPUT_DIR = Path(".")


def _parse_date(start_date: str) -> datetime:
    try:
        return datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(
            f"start_date must use YYYY-MM-DD format; received {start_date!r}"
        ) from exc


def generate_block_requests(
    n: int = 15,
    seed: int | None = None,
    start_date: str = DEFAULT_START_DATE,
) -> pd.DataFrame:
    if n < 0:
        raise ValueError("n must be >= 0")

    base = _parse_date(start_date)
    rng = random.Random(seed)

    return pd.DataFrame(
        {
            "request_id": [f"REQ-{i + 1:03}" for i in range(n)],
            "department": [rng.choice(DEPARTMENTS) for _ in range(n)],
            "section_id": [rng.choice(SECTIONS) for _ in range(n)],
            "requested_date": [
                (base + timedelta(days=rng.randint(0, 6))).strftime("%Y-%m-%d")
                for _ in range(n)
            ],
            "duration_hours": [rng.choice(DURATION_OPTIONS) for _ in range(n)],
            "safety_flag": [rng.choice((0, 0, 0, 1)) for _ in range(n)],
            "days_since_last_maintenance": [rng.randint(5, 180) for _ in range(n)],
        }
    )


def generate_timetable(
    n: int = 40,
    seed: int | None = None,
    start_date: str = DEFAULT_START_DATE,
) -> pd.DataFrame:
    if n < 0:
        raise ValueError("n must be >= 0")

    base = _parse_date(start_date)
    rng = random.Random(seed)

    return pd.DataFrame(
        {
            "train_id": [f"TRN-{i + 1:03}" for i in range(n)],
            "section_id": [rng.choice(SECTIONS) for _ in range(n)],
            "date": [
                (base + timedelta(days=rng.randint(0, 6))).strftime("%Y-%m-%d")
                for _ in range(n)
            ],
            "train_priority": [rng.choice(TRAIN_PRIORITIES) for _ in range(n)],
        }
    )


def score_all_requests(
    requests_df: pd.DataFrame,
    timetable_df: pd.DataFrame,
) -> pd.DataFrame:
    required_requests = {
        "request_id", "department", "section_id", "requested_date",
        "duration_hours", "safety_flag", "days_since_last_maintenance",
    }
    missing_requests = required_requests.difference(requests_df.columns)
    if missing_requests:
        raise ValueError(f"Missing request columns: {sorted(missing_requests)}")
    if "section_id" not in timetable_df.columns:
        raise ValueError("Missing timetable columns: ['section_id']")

    scored = requests_df.copy()
    density = timetable_df["section_id"].value_counts()
    scored["traffic_density"] = scored["section_id"].map(density).fillna(0).astype(int)
    scored["priority_score"] = (
        scored["safety_flag"] * 50
        + scored["days_since_last_maintenance"] * 0.3
        - scored["traffic_density"] * 0.5
    ).round(2)

    return scored.sort_values("priority_score", ascending=False).reset_index(drop=True)


def merge_compatible_requests(scored_df: pd.DataFrame) -> pd.DataFrame:
    required = {
        "request_id", "department", "section_id", "requested_date",
        "duration_hours", "priority_score",
    }
    missing = required.difference(scored_df.columns)
    if missing:
        raise ValueError(f"Missing merge columns: {sorted(missing)}")
    if scored_df.empty:
        return scored_df.copy()

    grouped = scored_df.groupby(
        ["section_id", "requested_date"], sort=True, dropna=False
    )
    summary = grouped.agg(
        departments=("department", lambda s: tuple(sorted(set(s)))),
        request_ids=("request_id", lambda s: ", ".join(map(str, s))),
        request_count=("request_id", "size"),
        duration_hours=("duration_hours", "max"),
        original_duration_hours=("duration_hours", "sum"),
        priority_score=("priority_score", "max"),
    ).reset_index()

    summary["department_count"] = summary["departments"].map(len)
    summary["is_joint_block"] = summary["department_count"] >= 2
    summary["departments"] = summary["departments"].map(lambda d: ", ".join(d))
    summary["hours_saved"] = (
        summary["original_duration_hours"] - summary["duration_hours"]
    )
    summary["block_id"] = [f"BLK-{i + 1:03}" for i in range(len(summary))]
    summary["block_type"] = summary["is_joint_block"].map(
        {True: "JOINT", False: "SINGLE"}
    )

    return summary[
        [
            "block_id", "section_id", "requested_date", "departments",
            "request_ids", "request_count", "block_type", "duration_hours",
            "original_duration_hours", "hours_saved", "priority_score",
        ]
    ]


def schedule_blocks(blocks_df: pd.DataFrame, day_hours: int = DAY_HOURS) -> pd.DataFrame:
    required = {
        "block_id", "section_id", "requested_date", "duration_hours", "priority_score"
    }
    missing = required.difference(blocks_df.columns)
    if missing:
        raise ValueError(f"Missing scheduler columns: {sorted(missing)}")
    if day_hours <= 0:
        raise ValueError("day_hours must be > 0")
    if blocks_df.empty:
        result = blocks_df.copy()
        result["scheduled_start_hr"] = pd.Series(dtype=int)
        result["scheduled_end_hr"] = pd.Series(dtype=int)
        return result

    scheduled_rows: list[dict] = []

    for (section, date), day_df in blocks_df.groupby(
        ["section_id", "requested_date"], sort=True, dropna=False
    ):
        day_df = day_df.reset_index(drop=True)
        durations = day_df["duration_hours"].astype(int).tolist()

        if any(duration <= 0 for duration in durations):
            raise ValueError("duration_hours must contain only positive values")
        if sum(durations) > day_hours:
            raise ValueError(
                f"No feasible {day_hours}-hour schedule for {section} on {date}: "
                f"{sum(durations)} hours requested."
            )

        model = cp_model.CpModel()
        count = len(day_df)
        starts = [model.NewIntVar(0, day_hours, f"start_{i}") for i in range(count)]
        ends = [model.NewIntVar(0, day_hours, f"end_{i}") for i in range(count)]
        intervals = []

        for i, duration in enumerate(durations):
            model.Add(ends[i] == starts[i] + duration)
            intervals.append(model.NewIntervalVar(
                starts[i], duration, ends[i], f"interval_{i}"
            ))

        model.AddNoOverlap(intervals)

        scores = day_df["priority_score"].astype(float).tolist()
        minimum = min(scores)
        shift = abs(minimum) + 1 if minimum < 0 else 0
        weights = [max(1, int(round((score + shift) * 10))) for score in scores]
        model.Minimize(sum(starts[i] * weights[i] for i in range(count)))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise RuntimeError(f"CP-SAT could not schedule {section} on {date}")

        for i in range(count):
            row = day_df.loc[i].to_dict()
            row["scheduled_start_hr"] = solver.Value(starts[i])
            row["scheduled_end_hr"] = solver.Value(ends[i])
            scheduled_rows.append(row)

    return pd.DataFrame(scheduled_rows).sort_values(
        ["section_id", "requested_date", "scheduled_start_hr"]
    ).reset_index(drop=True)


def run_pipeline(
    request_count: int = 15,
    timetable_count: int = 40,
    seed: int = 42,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)

    requests = generate_block_requests(request_count, seed=seed)
    timetable = generate_timetable(timetable_count, seed=seed)
    scored = score_all_requests(requests, timetable)
    blocks = merge_compatible_requests(scored)
    scheduled = schedule_blocks(blocks)

    requests.to_csv(output_dir / "block_requests.csv", index=False)
    timetable.to_csv(output_dir / "timetable.csv", index=False)
    scored.to_csv(output_dir / "scored_requests.csv", index=False)
    blocks.to_csv(output_dir / "merged_blocks.csv", index=False)
    scheduled.to_csv(output_dir / "scheduled_blocks.csv", index=False)

    return {
        "requests": requests,
        "timetable": timetable,
        "scored": scored,
        "blocks": blocks,
        "scheduled": scheduled,
    }


def print_summary(results: dict[str, pd.DataFrame]) -> None:
    requests = results["requests"]
    blocks = results["blocks"]
    scheduled = results["scheduled"]

    total_original = blocks["original_duration_hours"].sum()
    total_optimized = blocks["duration_hours"].sum()
    total_saved = blocks["hours_saved"].sum()
    joint_count = (blocks["block_type"] == "JOINT").sum()

    print("\n=== BLOCK MANAGEMENT OPTIMIZATION ===")
    print(f"Requests generated : {len(requests)}")
    print(f"Blocks after merge : {len(blocks)}")
    print(f"Joint blocks       : {joint_count}")
    print(f"Original hours     : {total_original}")
    print(f"Optimized hours    : {total_optimized}")
    print(f"Hours saved        : {total_saved}")
    print("\n=== FINAL SCHEDULE ===")

    columns = [
        "block_id", "section_id", "requested_date", "departments",
        "block_type", "duration_hours", "scheduled_start_hr",
        "scheduled_end_hr", "priority_score",
    ]
    print(scheduled[columns].to_string(index=False))


if __name__ == "__main__":
    results = run_pipeline()
    print_summary(results)
