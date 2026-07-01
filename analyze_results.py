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

print('--- Win rate by pattern ---')
for p,v in sorted(by_pattern.items(), key=lambda x:-x[1]['pnl']):
    tot = v['w']+v['l']
    print(f"  {p:<28s} {v['w']}/{tot} wins  PnL={v['pnl']:+.0f}")

print()
print('--- Exit breakdown ---')
print(f"  Stops: {len(stops)}  Times: {len(trades)-len(stops)}")
if wins:   print(f"  Avg win:  {sum(t['profit_loss_pct'] for t in wins)/len(wins):.1%}")
if losses: print(f"  Avg loss: {sum(t['profit_loss_pct'] for t in losses)/len(losses):.1%}")
gross_win  = sum(t['profit_loss'] for t in wins)
gross_loss = abs(sum(t['profit_loss'] for t in losses))
print(f"  Profit factor: {gross_win/gross_loss:.2f}x" if gross_loss else "  Profit factor: inf")

by_sig = {}
for t in trades:
    s = t.get('signal','?')
    if s not in by_sig: by_sig[s] = {'w':0,'l':0,'pnl':0}
    if t['status']=='WIN': by_sig[s]['w']+=1
    else: by_sig[s]['l']+=1
    by_sig[s]['pnl'] += t['profit_loss']

print()
print('--- Win rate by signal type ---')
for s,v in by_sig.items():
    tot = v['w']+v['l']
    print(f"  {s:<14s} {v['w']}/{tot} ({v['w']/tot:.0%})  PnL={v['pnl']:+.0f}")

by_volconf = {'confirmed':{'w':0,'l':0,'pnl':0}, 'unconfirmed':{'w':0,'l':0,'pnl':0}}
for t in trades:
    k = 'confirmed' if t.get('vol_confirmed') else 'unconfirmed'
    if t['status']=='WIN': by_volconf[k]['w']+=1
    else: by_volconf[k]['l']+=1
    by_volconf[k]['pnl'] += t['profit_loss']
print()
print('--- Win rate by volume confirmation ---')
for k,v in by_volconf.items():
    tot = v['w']+v['l']
    if tot: print(f"  {k:<14s} {v['w']}/{tot} ({v['w']/tot:.0%})  PnL={v['pnl']:+.0f}")

risks = [t for t in trades if 'stop_loss' in t and t['stop_loss']]
risk_pcts = [abs(t['entry_price']-t['stop_loss'])/t['entry_price']*100 for t in risks]
print()
print(f"--- Risk% distribution ---")
buckets = {'<2%':{'w':0,'l':0}, '2-5%':{'w':0,'l':0}, '5-10%':{'w':0,'l':0}, '>10%':{'w':0,'l':0}}
for t,r in zip(risks, risk_pcts):
    if r < 2:   k='<2%'
    elif r < 5: k='2-5%'
    elif r < 10: k='5-10%'
    else:        k='>10%'
    if t['status']=='WIN': buckets[k]['w']+=1
    else: buckets[k]['l']+=1
for k,v in buckets.items():
    tot = v['w']+v['l']
    if tot: print(f"  {k:<8s} {v['w']}/{tot} ({v['w']/tot:.0%})")
