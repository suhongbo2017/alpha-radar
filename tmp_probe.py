"""一次性探测器：找出项目里哪些公司的数据落后于最新财报。"""
import json
import glob
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PROXY = os.environ.get('ALPHA_PROXY', 'http://127.0.0.1:7897')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')


def curl(args, ticker):
    cmd = ['curl', '-s', '--max-time', '30', '-A', UA]
    if PROXY:
        cmd += ['-x', PROXY]
    cmd += args
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return r.stdout


def probe(ticker):
    ck = os.path.join(tempfile.gettempdir(), 'yh_probe_%s.txt' % ticker)
    curl(['-c', ck, 'https://fc.yahoo.com', '-o', os.devnull], ticker)
    crumb = curl(['-b', ck, 'https://query1.finance.yahoo.com/v1/test/getcrumb'], ticker).strip()
    if not crumb or '<' in crumb:
        return None, 'crumb失败'
    url = ('https://query1.finance.yahoo.com/v10/finance/quoteSummary/%s'
           '?modules=defaultKeyStatistics,calendarEvents,price&crumb=%s' % (ticker, crumb))
    body = curl(['-b', ck, url], ticker)
    try:
        d = json.loads(body)
        r = (d.get('quoteSummary') or {}).get('result')
    except Exception as e:
        return None, 'JSON失败:%s' % e
    if not r:
        return None, '无结果'
    r = r[0]
    ks = r.get('defaultKeyStatistics', {}) or {}
    ce = r.get('calendarEvents', {}) or {}

    def raw(x):
        return x.get('raw') if isinstance(x, dict) else x

    mrq = raw(ks.get('mostRecentQuarter'))
    last_fy = raw(ks.get('lastFiscalYearEnd'))
    nxt = ((ce.get('earnings') or {}).get('earningsDate') or [])
    nxt = [raw(x) for x in nxt if raw(x)]
    return {
        'mrq': datetime.fromtimestamp(mrq, timezone.utc).strftime('%Y-%m-%d') if mrq else None,
        'last_fy': (datetime.fromtimestamp(last_fy, timezone.utc).strftime('%Y-%m-%d')
                    if last_fy else None),
        'next_earnings': [datetime.fromtimestamp(x, timezone.utc).strftime('%Y-%m-%d')
                          for x in nxt],
    }, None


def main():
    snaps = {}
    for p in sorted(glob.glob('data/research_snapshots/*.json')):
        s = json.load(open(p, encoding='utf-8'))
        snaps[s['ticker']] = s

    rows = []
    for t, s in snaps.items():
        info, err = probe(t)
        if err:
            rows.append((t, s.get('data', {}).get('ttm_period'), None, None, err))
            continue
        rows.append((t, s.get('data', {}).get('ttm_period'), info['mrq'],
                     info.get('last_fy'), ','.join(info['next_earnings'])))

    print('%-6s %-12s %-12s %-12s %-24s %s' % ('TICK', '项目TTM期', 'Yahoo最近季末', '财年末',
                                               '下次财报', '判定'))
    print('-' * 100)
    stale = []
    for t, proj, mrq, fy, extra in rows:
        if mrq is None:
            verdict = '探测失败: %s' % extra
        elif proj is None:
            verdict = '项目无TTM'
        elif proj >= mrq:
            verdict = '最新'
        else:
            verdict = '🔴 落后 %s → %s' % (proj, mrq)
            stale.append((t, proj, mrq))
        print('%-6s %-12s %-12s %-12s %-24s %s' % (t, proj or '—', mrq or '—', fy or '—', extra, verdict))
    print()
    print('需要更新：%d 家' % len(stale))
    for s in stale:
        print('  ', s[0], s[1], '->', s[2])
    json.dump(stale, open('stale.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
