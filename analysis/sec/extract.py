# -*- coding: utf-8 -*-
import json, sys, datetime
sys.stdout.reconfigure(encoding='utf-8')
FILES = {'NOW':'1373715.json','MSFT':'789019.json','CRM':'1108524.json'}
def load(t): return json.load(open(FILES[t], encoding='utf-8'))
def dur_days(s,e):
    return (datetime.date.fromisoformat(e)-datetime.date.fromisoformat(s)).days
def series(facts, tag, want='annual'):
    for tax in ('us-gaap','ifrs-full'):
        if tax in facts and tag in facts[tax]:
            rows={}
            for unit, items in facts[tax][tag]['units'].items():
                if unit!='USD': continue
                for it in items:
                    if 'start' not in it: continue
                    d=dur_days(it['start'],it['end'])
                    if want=='annual' and not (330<=d<=400): continue
                    if want=='quarter' and not (80<=d<=100): continue
                    rows[it['end']]=(it['end'],it['start'],it['val'],it.get('form'),it.get('fy'),it.get('fp'))
            return [rows[k] for k in sorted(rows)]
    return []
def instant(facts, tag):
    for tax in ('us-gaap',):
        if tax in facts and tag in facts[tax]:
            rows={}
            for unit, items in facts[tax][tag]['units'].items():
                if unit!='USD': continue
                for it in items:
                    if 'start' in it: continue
                    rows[it['end']]=(it['end'],it['val'],it.get('form'))
            return [rows[k] for k in sorted(rows)]
    return []
def b(v): return v/1e9
def show(title, rows, n=10):
    if not rows: return
    print('\n== %s ==' % title)
    for r in rows[-n:]:
        print('  end=%s  %.3fB  form=%s fy%s%s' % (r[0], b(r[2]), r[3], r[4], r[5]))
if __name__=='__main__':
    t=sys.argv[1]; d=load(t); facts=d['facts']
    print('#### %s (%s) ####' % (d['entityName'], t))
    ann=[('Revenues','Revenue'),('RevenueFromContractWithCustomerExcludingAssessedTax','Revenue(contract)'),
         ('GrossProfit','GrossProfit'),('CostOfRevenue','COGS'),('OperatingIncomeLoss','OpInc'),
         ('NetIncomeLoss','NetIncome'),('ResearchAndDevelopmentExpense','R&D'),
         ('SellingAndMarketingExpense','S&M'),('ShareBasedCompensation','SBC'),
         ('NetCashProvidedByUsedInOperatingActivities','OCF'),
         ('PaymentsToAcquirePropertyPlantAndEquipment','CapEx'),
         ('DepreciationDepletionAndAmortization','D&A')]
    for tag,label in ann:
        show(label+' [annual]', series(facts,tag,'annual'), 8)
    for tag,label in [('Revenues','Revenue'),('RevenueFromContractWithCustomerExcludingAssessedTax','Revenue(contract)'),
                      ('OperatingIncomeLoss','OpInc'),('NetCashProvidedByUsedInOperatingActivities','OCF')]:
        show(label+' [Q]', series(facts,tag,'quarter'), 8)
    for tag,label in [('DeferredRevenueCurrent','DeferredRevCurr'),('ContractWithCustomerLiabilityCurrent','ContractLiabCurr'),
                      ('CashAndCashEquivalentsAtCarryingValue','Cash'),('StockholdersEquity','Equity'),
                      ('LongTermDebtNoncurrent','LTDebt'),('CommonStockSharesOutstanding','SharesOut')]:
        rows=instant(facts,tag)
        if rows:
            print('\n== %s [instant] ==' % label)
            for r in rows[-6:]:
                v=r[1]
                print('  %s  %s  form=%s' % (r[0], ('%.3fB'%b(v)) if abs(v)>1e8 else v, r[2]))
