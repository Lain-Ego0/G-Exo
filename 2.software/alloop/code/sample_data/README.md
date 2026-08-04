English | [中文](README.zh-CN.md)

# Sample Data

Two CSV files covering **14 consecutive days** of ring history data, so you can build
visualizations, analytics, and algorithms without wearing a device for two weeks first.

| File | Rows | Interval | Content |
| --- | --- | --- | --- |
| `sample_14days_Measurement.csv` | ~7,900 | 2.5 min | Heart rate, HRV, SpO2, respiration rate |
| `sample_14days_Activity.csv` | ~1,300 | 15 min | Battery, steps, active seconds, skin temperature |

> **These files are synthetic**, generated to match the statistical distributions and
> timing behaviour of real device captures. They are not recorded from an actual person.
> The column format is **identical** to what the app writes on History Data sync, so you
> can mix these files with your own exports and parse both with the same code.

---

## Measurement — `sample_14days_Measurement.csv`

Header: `time,hr,hrv,spo2,respRate,hrSuccess,spo2Success`

| Column | Type | Notes |
| --- | --- | --- |
| `time` | ISO8601 UTC | e.g. `2026-07-01T00:02:30.000Z` |
| `hr` | int | Heart rate (bpm). See "Reading the validity flags" below. |
| `hrv` | int | Heart rate variability. `0` when there is no valid reading. |
| `spo2` | int | Blood oxygen (%). See "Reading the validity flags" below. |
| `respRate` | int | Respiration rate **stored x10** — `124` means 12.4 breaths/min. `0` when invalid. |
| `hrSuccess` | `true`/`false` | Whether `hr` in this row is a real reading |
| `spo2Success` | `true`/`false` | Whether `spo2` in this row is a real reading |

### Reading the validity flags — important

Rows are written every **2.5 minutes**, but the sensors do not produce a value in every
slot. This mirrors real device behaviour:

- **Heart rate** is measured roughly every **5 minutes**, so about half the rows carry no
  real HR.
- **SpO2** is measured roughly every **15 minutes**. While the wearer is awake the cadence
  drifts (a heart-rate measurement can preempt it); during sleep it is steady.

When a slot has no reading, the value column contains the device's placeholder `18` and
the matching `*Success` column is `false`.

**Always filter on the flags rather than the values** (the `18` placeholder is not a real
measurement):

```python
# Python / pandas
df = pd.read_csv('sample_14days_Measurement.csv')
# pandas parses the true/false column as a real boolean, so it can filter directly:
valid_hr = df[df.hrSuccess]['hr']            # real heart-rate readings
valid_spo2 = df[df.spo2Success]['spo2']      # real SpO2 readings
resp_bpm = df[df.spo2Success]['respRate'] / 10   # respRate is stored x10
```

```dart
// Dart — read the CSV and keep only rows with a real heart-rate reading.
// Each line is: time,hr,hrv,spo2,respRate,hrSuccess,spo2Success
final lines = await File('sample_14days_Measurement.csv').readAsLines();
final validHr = <int>[];
for (final line in lines.skip(1)) {          // skip the header row
  final c = line.split(',');
  if (c[5] == 'true') validHr.add(int.parse(c[1]));   // c[5]=hrSuccess, c[1]=hr
}
```

---

## Activity — `sample_14days_Activity.csv`

Header: `time,batteryPercent,steps,activeSeconds,temperaturesC`

| Column | Type | Notes |
| --- | --- | --- |
| `time` | ISO8601 UTC | 15-minute interval |
| `batteryPercent` | int 0–100 | Ring battery |
| `steps` | int | Steps **within this 15-minute interval** (a delta, not a running total) |
| `activeSeconds` | int | Active seconds within this interval (0–900; 900 = the full window) |
| `temperaturesC` | float list | 15 skin-temperature samples (one per minute), semicolon-separated, e.g. `33.4;33.5;33.2` |

```python
# Daily step totals
df = pd.read_csv('sample_14days_Activity.csv', parse_dates=['time'])
daily = df.groupby(df.time.dt.date)['steps'].sum()   # ~7k-12k per day

# Skin temperature: expand the semicolon-separated samples
temps = df.temperaturesC.str.split(';').explode().astype(float)
```

---

## What the data looks like

Realistic patterns are built in, so charts and algorithms produce sensible results:

- **Circadian heart rate** — lower during sleep (~58 bpm), higher during the day, with
  occasional activity peaks. Valid range 51–107.
- **SpO2** — mostly 94–99, with mild dips during sleep. Valid range 86–99.
- **HRV** — inversely tracks heart rate, higher during sleep. Range 21–104.
- **Steps** — concentrated in daytime, near zero overnight, ~7k–12k per day.
- **Battery** — drains over several days and recharges periodically.
- **Gaps** — the ring is off the finger while charging (~1 hour, every other day), so
  **there are no rows at all in those windows**. Real syncs look like this too — make sure
  your charts handle missing time ranges.

All values stay within physiologically plausible ranges. Real captures occasionally contain
sensor glitches (implausible temperatures, out-of-range heart rates); those are deliberately
**not** reproduced here so they don't look like bugs in your own code.

**Combining the two files:** they share the same UTC time axis but different intervals
(measurement every 2.5 min, activity every 15 min). To analyse them together — e.g. "was
heart rate elevated during high-step periods?" — resample or bucket both to a common window
(15 min works well) on the `time` column before joining.

> Large files: prefer streaming/chunked reading if your tooling struggles with the
> measurement file (~380 KB, ~7.9k rows).
