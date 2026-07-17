import json

with open('dashboard/data.json') as f:
    d = json.load(f)
trades = d['trade_logs']
wins   = [t for t in trades if t['status']=='WIN']
losses = [t for t in trades if t['status']=='LOSS']
stops  = [t for t in trades if t['exit_reason']=='STOP']

by_pattern = {}
for t in trades:
    p = t.get('pattern','?')
    if p not in by_pattern: by_pattern[p] = {'w':0,'l':0,'pnl':0}
    by_pattern[p]['pnl'] += t['profit_loss']
    if t['status']=='WIN': by_pattern[p]['w']+=1
    else: by_pattern[p]['l']+=1

for p,v in sorted(by_pattern.items(), key=lambda x:-x[1]['pnl']):
    tot = v['w']+v['l']

if wins:   pass
if losses: pass
gross_win  = sum(t['profit_loss'] for t in wins)
gross_loss = abs(sum(t['profit_loss'] for t in losses))

by_sig = {}
for t in trades:
    s = t.get('signal','?')
    if s not in by_sig: by_sig[s] = {'w':0,'l':0,'pnl':0}
    if t['status']=='WIN': by_sig[s]['w']+=1
    else: by_sig[s]['l']+=1
    by_sig[s]['pnl'] += t['profit_loss']

for s,v in by_sig.items():
    tot = v['w']+v['l']

by_volconf = {'confirmed':{'w':0,'l':0,'pnl':0}, 'unconfirmed':{'w':0,'l':0,'pnl':0}}
for t in trades:
    k = 'confirmed' if t.get('vol_confirmed') else 'unconfirmed'
    if t['status']=='WIN': by_volconf[k]['w']+=1
    else: by_volconf[k]['l']+=1
    by_volconf[k]['pnl'] += t['profit_loss']
for k,v in by_volconf.items():
    tot = v['w']+v['l']
    if tot: pass

risks = [t for t in trades if t.get('stop_loss')]
risk_pcts = [abs(t['entry_price']-t['stop_loss'])/t['entry_price']*100 for t in risks]
buckets = {'<2%':{'w':0,'l':0}, '2-5%':{'w':0,'l':0}, '5-10%':{'w':0,'l':0}, '>10%':{'w':0,'l':0}}
for t,r in zip(risks, risk_pcts, strict=False):
    if r < 2:   k='<2%'
    elif r < 5: k='2-5%'
    elif r < 10: k='5-10%'
    else:        k='>10%'
    if t['status']=='WIN': buckets[k]['w']+=1
    else: buckets[k]['l']+=1
for k,v in buckets.items():
    tot = v['w']+v['l']
    if tot: pass
