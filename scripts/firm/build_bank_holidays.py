"""Federal Reserve holiday calendar -> reference_data/ref_bank_holidays.csv (the days the Fed - and payment settlement - is closed).

Rules (Federal Reserve holiday schedule): New Year's Day, Birthday of Martin Luther King Jr. (3rd Monday of January), Washington's
Birthday (3rd Monday of February), Memorial Day (last Monday of May), Juneteenth (June 19), Independence Day (July 4), Labor Day
(1st Monday of September), Columbus Day (2nd Monday of October), Veterans Day (November 11), Thanksgiving Day (4th Thursday of
November), Christmas Day (December 25). A fixed-date holiday on a Sunday is observed on the following Monday; one on a Saturday
is not moved (the Reserve Banks are open the Friday before) - the Saturday is already not a business day.
"""
import csv, datetime, pathlib, sys

def nth(y, m, wd, n):          # n-th weekday (0 = Monday) of the month; n = -1 -> the last one
    if n > 0:
        d = datetime.date(y, m, 1)
        d += datetime.timedelta(days=(wd - d.weekday()) % 7)
        return d + datetime.timedelta(weeks=n - 1)
    d = datetime.date(y + (m == 12), m % 12 + 1, 1) - datetime.timedelta(days=1)
    return d - datetime.timedelta(days=(d.weekday() - wd) % 7)

rows = []
for y in range(2025, 2036):
    fixed = [(1, 1, "New Year's Day"), (6, 19, "Juneteenth National Independence Day"), (7, 4, "Independence Day"), (11, 11, "Veterans Day"), (12, 25, "Christmas Day")]
    for m, dd, name in fixed:
        d = datetime.date(y, m, dd)
        if d.weekday() == 6:
            rows.append((d + datetime.timedelta(days=1), name + " (observed)"))
        elif d.weekday() < 5:
            rows.append((d, name))
    rows += [(nth(y, 1, 0, 3), "Birthday of Martin Luther King, Jr."), (nth(y, 2, 0, 3), "Washington's Birthday"), (nth(y, 5, 0, -1), "Memorial Day"),
             (nth(y, 9, 0, 1), "Labor Day"), (nth(y, 10, 0, 2), "Columbus Day"), (nth(y, 11, 3, 4), "Thanksgiving Day")]
out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "reference_data/ref_bank_holidays.csv")
with open(out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["holiday_date", "holiday_name", "calendar"])
    for d, n in sorted(rows):
        w.writerow([d.isoformat(), n, "US Federal Reserve"])
print(len(rows), "holidays ->", out)
