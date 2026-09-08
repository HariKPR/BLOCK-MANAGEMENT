# Railway Block Management

End-to-end railway maintenance block optimization prototype.

## Pipeline

1. Generate simulated BDMS maintenance requests and COA timetable.
2. Calculate transparent priority scores.
3. Merge compatible departmental requests on the same section/date.
4. Schedule blocks using OR-Tools CP-SAT without overlap.
5. Export optimized results to CSV.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

If `ModuleNotFoundError: No module named 'ortools'` appears, install the dependencies first with the command above.
