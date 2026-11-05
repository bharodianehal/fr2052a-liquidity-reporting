"""usage: check_6g_business_rules.py <6G Business Requirements.xlsx> <6G xml>...

6G Business Requirements file-rejection checks on generated 6G XML (BR General #19-21, 23, Counterparty Required, G-SIB)."""
import collections, sys, openpyxl
from lxml import etree
BR, *files = sys.argv[1:]
wb = openpyxl.load_workbook(BR, read_only=True, data_only=True)
rows = lambda n: [[("" if c is None else str(c).strip()) for c in r] for r in list(wb[n].iter_rows(values_only=True))[1:] if any(r)]
cp_req = {(r[1], r[3]) for r in rows("Counterparty Required")}
coll_req = {(r[1], r[4]) for r in rows("Collateral Class Required")}
enum = rows("Enumerations")
# G-SIB names are not in the XSD; the BR Enumerations tab lists them (column 5) and FRS enforces them
gsibs = {r[5] for r in enum if len(r) > 5 and r[2] == "gsib"}
for f in files:
    doc = etree.parse(f).getroot(); fails = collections.Counter(); keys = collections.Counter(); ids = collections.Counter()
    for rec in (e for e in doc[1:] if isinstance(e.tag, str)):
        rt = etree.QName(rec).localname
        prod = next(c.text for c in rec if isinstance(c.tag, str) and etree.QName(c).localname.endswith("Product"))
        ids[(rt, rec.get("reportID"))] += 1
        key = [(k, v) for k, v in sorted(rec.attrib.items()) if k != "reportID"]
        amts = []
        for c in (x for x in rec if isinstance(x.tag, str)):
            n = etree.QName(c).localname
            if c.get("unitMultiplier"):
                amts.append(float(c.text)); key.append((n + "@", c.get("unit"), c.get("converted")))
            elif n != "comment":
                key.append((n, etree.tostring(c)))
        keys[(rt, tuple(key))] += 1
        names = {etree.QName(c).localname for c in rec if isinstance(c.tag, str)}
        if amts and all(a == 0 for a in amts) and rt not in ("liquidityRiskMeasurementSupReport",):
            fails["all amounts zero"] += 1
        if (rt, prod) in cp_req and "counterpartySector" not in names:
            fails[f"counterparty required: {prod}"] += 1
        if (rt, prod) in coll_req and "collateralClass" not in names:
            fails[f"collateral class required: {prod}"] += 1
        if "gsib" in names and "counterpartySector" not in names:
            fails["G-SIB without counterparty"] += 1
        g = rec.find("gsib")
        if g is not None and gsibs and g.text not in gsibs:
            fails[f"G-SIB not in BR list: {g.text}"] += 1
    fails["duplicate report key"] = sum(n - 1 for n in keys.values() if n > 1)
    fails["duplicate reportID"] = sum(n - 1 for n in ids.values() if n > 1)
    print(f"{f.split('/')[-1]}: BR G-SIB list has {len(gsibs)} names")
    for k, v in sorted(fails.items()):
        print(f"  {'FAIL' if v else 'ok  '} {v:3d}  {k}")
