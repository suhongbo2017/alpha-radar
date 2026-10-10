# -*- coding: utf-8 -*-
import json, sys, datetime
sys.stdout.reconfigure(encoding='utf-8')
def dur_days(s,e): return (datetime.date.fromisoformat(e)-datetime.date.fromisoformat(s)).days
def series(facts, tag, want='annual'):
    for tax in ('us-gaap',):
        if tax in facts and tag in facts[tax]:
            rows={}
            for unit, items in facts[tax][tag]['units'].items():
                if unit!='USD': continue
                for it in items:
                    if 'start' not in it: continue
                    d=dur_days(it['start'],it['end'])
                    if want=='annual' and not (330<=d<=400): continue
                    if want=='quarter' and not (80<=d<=100): continue
                    rows[it['end']]=(it['end'],it['val'],it.get('form'))
            return [rows[k] for k in sorted(rows)]
    return []
def instant(facts, tag):
    if 'us-gaap' in facts and tag in facts['us-gaap']:
        rows={}
        for unit, items in facts['us-gaap'][tag]['units'].items():
            if unit!='USD': continue
            for it in items:
                if 'start' in it: continue
                rows[it['end']]=(it['end'],it['val'],it.get('form'))
        return [rows[k] for k in sorted(rows)]
    return []
def B(v): return v/1e9
def show(title, rows, n=9):
    if not rows: print('\n== %s == (no data)'%title); return
    print('\n== %s ==' % title)
    for r in rows[-n:]:
        print('   %s  %s  %s' % (r[0], ('%.4fB'%B(r[1])) if abs(r[1])>1e7 else r[1], r[2] if len(r)>2 else ''))
if __name__=='__main__':
    d=json.load(open(sys.argv[1],encoding='utf-8')); facts=d['facts']
    print('####',d['entityName'])
    ann=[('Revenues','Revenue'),('RevenueFromContractWithCustomerExcludingAssessedTax','Revenue(contract)'),
     ('GrossProfit','GrossProfit'),('CostOfRevenue','COGS'),('CostOfGoodsAndServicesSold','COGS2'),
     ('OperatingIncomeLoss','OpInc'),('NetIncomeLoss','NetIncome'),
     ('ResearchAndDevelopmentExpense','R&D'),('SellingAndMarketingExpense','S&M'),
     ('SellingGeneralAndAdministrativeExpense','SG&A'),('GeneralAndAdministrativeExpense','G&A'),
     ('ShareBasedCompensation','SBC'),('NetCashProvidedByUsedInOperatingActivities','OCF'),
     ('PaymentsToAcquirePropertyPlantAndEquipment','CapEx'),
     ('DepreciationDepletionAndAmortization','D&A'),
     ('AmortizationOfIntangibleAssets','AmortIntang'),
     ('InterestExpense','InterestExp'),
     ('IncomeTaxExpenseBenefit','Tax'),
     ('EarningsPerShareDiluted','EPSdil'),
     ('WeightedAverageNumberOfDilutedSharesOutstanding','DilShares')]
    for tag,label in ann:
        show(label+' [A]', series(facts,tag,'annual'), 9)
    for tag,label in [('Revenues','Revenue'),('RevenueFromContractWithCustomerExcludingAssessedTax','Revenue(contract)'),
                      ('GrossProfit','GrossProfit'),('OperatingIncomeLoss','OpInc'),
                      ('NetIncomeLoss','NetIncome'),('NetCashProvidedByUsedInOperatingActivities','OCF')]:
        show(label+' [Q]', series(facts,tag,'quarter'), 12)
    for tag,label in [('CashAndCashEquivalentsAtCarryingValue','Cash'),
                      ('MarketableSecuritiesCurrent','MktSecCurr'),
                      ('StockholdersEquity','Equity'),
                      ('LongTermDebtNoncurrent','LTDebt'),
                      ('LongTermDebtCurrent','DebtCurr'),
                      ('LongTermDebt','TotalLTDebt'),
                      ('InventoryNet','Inventory'),
                      ('AccountsReceivableNetCurrent','AR'),
                      ('Assets','TotalAssets'),
                      ('Goodwill','Goodwill'),
                      ('ContractWithCustomerLiabilityCurrent','ContractLiabCurr'),
                      ('ContractWithCustomerLiabilityNoncurrent','ContractLiabNonCurr')]:
        show(label+' [I]', instant(facts,tag), 7)
