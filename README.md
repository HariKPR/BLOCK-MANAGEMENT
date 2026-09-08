# Railway Block Management

End-to-end railway maintenance block optimization prototype with a Streamlit dashboard.

## Pipeline

1. Generate simulated BDMS maintenance requests and COA timetable.
2. Calculate transparent priority scores.
3. Merge compatible departmental requests on the same section/date.
4. Schedule blocks using OR-Tools CP-SAT without overlap.
5. Display the optimized schedule and savings in Streamlit.
6. Download generated CSV results.

## Streamlit deployment

The dashboard entry point is `app.py`.

```bash
pip install -r requirements.txt
streamlit run app.py
```

For Streamlit Community Cloud, select:

- **Main file:** `app.py`
- **Python dependencies:** `requirements.txt`

Do not use `main.py` as the Streamlit entry point. `main.py` contains the optimization engine; `app.py` provides the web interface.

## Command-line run

The optimization engine can also be run directly:

```bash
python main.py
```

If you see `ModuleNotFoundError: No module named 'ortools'`, install the dependencies with:

```bash
pip install -r requirements.txt
```
