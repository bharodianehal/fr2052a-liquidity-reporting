import sys, collections, xml.etree.ElementTree as ET
d=sys.argv[1]
tm={"assetInflowReport":"I.A","unsecuredInflowReport":"I.U","securedInflowReport":"I.S","otherInflowReport":"I.O","depositsOutflowReport":"O.D","wholesaleOutflowReport":"O.W","securedOutflowReport":"O.S","otherOutflowReport":"O.O","derivativesAndCollateralSupReport":"S.DC","liquidityRiskMeasurementSupReport":"S.L","balanceSheetSupReport":"S.B","informationalSupplementalReport":"S.I","foreignExchangeSupplementalReport":"S.FX"}
scope={"ACME - Consolidated":"ENT001","ACME - Bank":"ENT002","ACME - Securities":"ENT003"}
cnt=collections.Counter(); amt=collections.defaultdict(float); scopes=set()
for t in ("Primary","Reduced"):
    try: root=ET.parse(f"x_{d}_{t}.xml").getroot()
    except Exception as e: continue
    for el in root:
        if el.tag=="header": continue
        s=el.findtext("reportScope"); scopes.add(s)
        k=(scope.get(s,s), tm.get(el.tag,el.tag)); cnt[k]+=1
        # first amount-bearing element
        for a in el:
            if a.get("unit") is not None or a.tag in ("value",):
                try: amt[k]+=float(a.text); break
                except: pass
db={}
for l in open(f"db_{d}.txt").read().splitlines()[1:]:
    e,t,n,a=[x.strip() for x in l.split("|")]; db[(e,t)]=(int(n),float(a) if a!="None" else 0.0)
print(d,"scopes",scopes)
bad=0
for k in sorted(set(cnt)|set(db)):
    n,a=db.get(k,(0,0.0))
    if n!=cnt[k] or abs(a-amt[k])>0.01: bad+=1; print("MISMATCH",k,"db",n,round(a,4),"xml",cnt[k],round(amt[k],4))
print("tables",len(db),"xml records",sum(cnt.values()),"db records",sum(v[0] for v in db.values()),"mismatches",bad)
