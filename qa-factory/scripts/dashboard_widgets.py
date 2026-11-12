"""Original dashboard components, fed exclusively by the metric projection."""
import html
from datetime import date
from metrics_projection import render as definitions, _display_value
from metric_signals import number


# What `sample_size` counts, per metric family — so a printed denominator names its unit
# instead of being a bare "n=".
DENOMINATOR_UNIT = {'T': 'obligations or result rows', 'A': 'recorded attempts',
                    'F': 'dispatches or events', 'C': 'priced requests'}


def denominator(metric):
    """The status line under a card: the count only when its unit can be named."""
    unit = DENOMINATOR_UNIT.get(str(metric['id'])[0])
    if metric.get('numerator') is not None and metric.get('denominator'):
        return f"{metric['status']} · {metric['numerator']} of {metric['denominator']}"
    if unit and metric.get('sample_size'):
        return f"{metric['status']} · {metric['sample_size']} {unit}"
    return str(metric['status'])


def render(snapshot, prefixes, history):
    from factory_dashboard import card, spark, bars_svg, age_columns_svg
    esc = lambda v: html.escape(str(v), quote=True)
    metrics = {m['id']: m for m in snapshot['metrics']}
    out, cards, charts = [], [], []
    scalar_ids = {'T01','T02','T05','T11','T12','T13','A01','A02','A03','A04','A05','A06','A09','A10',
                  'F04','C04','C05','C07','C10','C14','C15'}
    for mid, m in metrics.items():
        if mid[0] not in prefixes or mid not in scalar_ids or number(m) is None:
            continue
        val = f"{m['value']:,.2f}".rstrip('0').rstrip('.') if isinstance(m['value'], float) else str(m['value'])
        # The footer used to read "available · n=358". `sample_size` means a different thing
        # for every metric (attempts, rows, sessions, dispatches), so the bare number said
        # nothing and invited the reader to compare two incomparable denominators. Either the
        # denominator is named or it is not printed.
        cards.append(card(m['label'], esc(val + (' ' + m['unit'] if m['unit'] != 'count' else '')),
                          esc(denominator(m))))
    if cards:
        out.append('<div class="cards">' + ''.join(cards) + '</div>')
    def widget(mid, body, title=None):
        m = metrics[mid]
        charts.append(f"<div class='wcard' data-metric='{mid}'><h3>{esc(title or m['label'])}</h3>{body}"
                      f"<div class='wleg'>{esc(denominator(m))}</div></div>")
    def bars(mid, field=None, title=None):
        m = metrics[mid]
        if mid[0] not in prefixes or not isinstance(m['value'], dict):
            return
        values = m['value'].get(field) if field else m['value']
        if isinstance(values, dict):
            rows = [(esc(k), v, 0) for k,v in values.items() if type(v) in (int,float)]
            if rows:
                widget(mid, bars_svg(rows), title)
    for mid in ('T07','T08','T10','T14','C12'):
        bars(mid)
    if 'T' in prefixes and isinstance(metrics['T09']['value'], dict):
        rows = [(esc(k), v) for k,v in metrics['T09']['value'].items() if v is not None]
        if rows:
            # The original age chart uses weeks; keep the axis honest.
            widget('T09', age_columns_svg([(k, v / 7) for k,v in rows]), 'Open bug age (weeks)')
    # The Factory tab draws no widget of its own here. F02, F03, F05, F06 and F07 each had a
    # chart in "Quality and outcomes" that repeated a card of "Factory health" one screen
    # above it, with a second set of words for the same number (TP1-15045, owner's reading
    # of the 0.7.13 render). They live in those cards now; the catalogue below still carries
    # every value, formula and sample.
    # A07 ("Run duration and volume") and A08 ("Test health") are not drawn: on TP1-15045
    # 43 of 76 run blocks recorded an end before their start, so every duration in A07 was
    # noise, and A08 duplicated the Factory tab's "Recorded test health", which is its one
    # home. C06 (requests/tools/rework) and C13 (divergence drivers, a duplicate of the
    # Pareto section) went the same way. All four stay in the catalogue below.
    if 'C' in prefixes:
        for mid in ('C11','C14'):
            if isinstance(metrics[mid]['value'], dict):
                widget(mid, _display_value(metrics[mid]['value']))
    if charts:
        out.append('<section><h2>Quality and outcomes</h2><div class="wcards wrap">' + ''.join(charts) + '</div></section>')
    trend_specs = {'T': [('T01',None),('T10','opened'),('T10','closed'),('T11',None),('T12',None),('T13',None)],
                   'A': [('A01',None),('A02',None),('A03',None),('A04',None),('A05',None),('A09',None),('A10',None)],
                   'F': [('F02','rate'),('F03','gate_block'),('F03','unsafe_completion'),('F04',None),('F05','retries'),('F08','token_percent'),('F08','cost_percent')],
                   'C': [('C01',None),('C02',None),('C04',None),('C05',None),('C06','rework_usd'),('C07',None),('C08',None),('C10',None),('C11','MMRE'),('C11','PRED25')]}
    trends=[]
    missing=[]
    for prefix in prefixes:
        for mid, field in trend_specs.get(prefix, []):
            title=metrics[mid]['label'] + (' · '+field.replace('_',' ') if field else '')
            points=[]
            for item in history:
                m=next((x for x in item['metrics'] if x['id']==mid), {})
                compatible = m.get('scope') == metrics[mid].get('scope') and m.get('formula_version') == metrics[mid].get('formula_version')
                value=number(m,field) if m.get('status')=='available' and compatible else None
                points.append((item['as_of'][:10],value))
            # Do not draw a line across unknown observations.
            tail=[]
            for point in reversed(points):
                if point[1] is None: break
                if tail and (date.fromisoformat(tail[0][0])-date.fromisoformat(point[0])).days != 1: break
                tail.insert(0,point)
            if len(tail)<2:
                missing.append(title)
                continue
            values=[p[1] for p in tail]
            trends.append(card(title, esc(f'{values[-1]:,.2f}'), esc(f'{tail[0][0]} → {tail[-1][0]} · {len(tail)} snapshots'),
                               chart=spark(values)))
    out.append('<section><h2>Trends</h2><p class="nd">Daily recorded snapshots of the stated reporting windows. No invented history; gaps break the series.</p>'
               + '<div class="cards">'+''.join(trends)+'</div>'
               + ('<details><summary>History not yet sufficient ('+str(len(missing))+')</summary><p>'+esc('; '.join(missing))+'</p></details>' if missing else '')+'</section>')
    # All 48 contracts remain inspectable, without making catalogue tables the main layout.
    out.append('<details class="formulas"><summary>All metric values, formulas, samples and sources</summary>'
               + definitions(snapshot,prefixes)+'</details>')
    return ''.join(out)


def signals_html(receipt, estimate_messages):
    esc = lambda x: html.escape(str(x),quote=True)
    active=[s for s in receipt.get('signals',[]) if s['status']!='resolved']
    rows=[]
    for s in active:
        tab='cost' if s['metric'].startswith('C') else 'factory' if s['metric'].startswith('F') else 'testing'
        # A signal that names sessions (the hot-cache rule) lists the lowest ten, one line each.
        listed=sorted(s.get('sessions') or [], key=lambda x:x['share'])
        lines=''.join(f"<div>{esc(x['session_id'])} · {x['share']:.1f}% · {x['tokens']:,} tokens</div>" for x in listed[:10])
        if len(listed)>10: lines+=f"<div>+{len(listed)-10} more</div>"
        rows.append(f"<li><b>{esc(s['title'])}</b> · {esc(s['status'])}: {esc(str(s['baseline'])+' → ' if s.get('baseline') is not None else '')}{esc(s['current'])}; "
                    f"n={esc(s['sample_size'])}. {esc(s['next_action'])} "
                    f"<a href='#{s['metric']}' data-open-tab='{tab}'>Evidence</a>"
                    f"<details><summary>Window and evaluation</summary>{esc(s['window_start'])} — {esc(s['window_end'])}; "
                    f"{esc(s['evaluation'])}; {esc(s.get('reason',''))}; policy {esc(s['rule_version'])}{lines}</details></li>")
    rows.extend('<li>'+esc(m)+'</li>' for m in estimate_messages)
    banner='<section class="alert"><h2>Metric warnings</h2><ul>'+''.join(rows)+'</ul></section>' if rows else ''
    not_evaluated=sum(e['status']=='not_evaluated' for e in receipt.get('evaluations',[]))
    note='No additional trend thresholds configured' if receipt['status']=='no_configured_rules' else f'{not_evaluated} rules not evaluated'
    return banner+f"<p class='meta'>Metrics checked {esc(receipt['evaluated_at'])} · {esc(note)}. Refresh on factory events or doctor; reopening this file does not recalculate.</p>"
