// Activity page — live log tail (polls /api/v1/activity?since= every 2s)

const fmtTime = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};

const fmtFieldValue = (v) => {
  if (v === null || v === undefined) return '∅';
  if (typeof v === 'string') return v.length > 80 ? v.slice(0, 77) + '…' : v;
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
};

const MAX_INLINE_CHIPS = 3;

const ActivityPage = () => {
  const [level, setLevel] = React.useState('All');
  const [autoScroll, setAutoScroll] = React.useState(true);
  const [search, setSearch] = React.useState('');
  const [lines, setLines] = React.useState([]);
  const [expanded, setExpanded] = React.useState(() => new Set());
  const sinceRef = React.useRef(0);
  const logBodyRef = React.useRef(null);

  React.useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const data = await window.API.activity(sinceRef.current);
        if (cancelled) return;
        // Server restart detection: if latestSeq dropped below our cursor,
        // the buffer was reset — discard the stale client state.
        if (data.latestSeq < sinceRef.current) {
          sinceRef.current = 0;
          setLines(data.lines);
          if (data.lines.length > 0) sinceRef.current = data.latestSeq;
          return;
        }
        if (data.lines.length > 0) {
          sinceRef.current = data.latestSeq;
          setLines(prev => [...prev.slice(-1700), ...data.lines].slice(-2000));
        } else {
          sinceRef.current = data.latestSeq;
        }
      } catch (_) { /* swallow until next tick */ }
    };
    poll();
    const id = setInterval(poll, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  React.useEffect(() => {
    if (autoScroll && logBodyRef.current) {
      logBodyRef.current.scrollTop = logBodyRef.current.scrollHeight;
    }
  }, [lines, autoScroll]);

  const handleScroll = (e) => {
    const el = e.target;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 20;
    setAutoScroll(atBottom);
  };

  const toggleExpand = (seq) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(seq)) next.delete(seq); else next.add(seq);
      return next;
    });
  };

  const filtered = lines.filter(l => {
    if (level !== 'All' && l.level !== level) return false;
    if (search) {
      const hay = `${l.src} ${l.message} ${l.humanMessage || ''} ${l.event || ''}`.toLowerCase();
      if (!hay.includes(search.toLowerCase())) return false;
    }
    return true;
  });

  const counts = { All: lines.length };
  ['INFO', 'DEBUG', 'WARNING', 'ERROR'].forEach(lvl => {
    counts[lvl] = lines.filter(l => l.level === lvl).length;
  });
  // Buttons show short labels; API uses standard logging level names.
  const LEVELS = [
    { label: 'All', value: 'All' },
    { label: 'DEBUG', value: 'DEBUG' },
    { label: 'INFO', value: 'INFO' },
    { label: 'WARN', value: 'WARNING' },
    { label: 'ERROR', value: 'ERROR' },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Activity</h1>
          <div className="sub">Live tail of the container stdout. ~2,000 lines kept in memory; full log on disk.</div>
        </div>
        <div className="actions">
          <a href={window.API.activityDownloadUrl()} download>
            <Button variant="ghost" icon="download">Download full log</Button>
          </a>
        </div>
      </div>

      <div className="log-shell">
        <div className="log-toolbar">
          <div className="live-dot">LIVE</div>

          <div className="level-pills">
            {LEVELS.map(lvl => (
              <button key={lvl.value} className={`level-pill ${level === lvl.value ? 'active' : ''}`} onClick={() => setLevel(lvl.value)}>
                {lvl.label} <span style={{ opacity: 0.5 }}>{counts[lvl.value] ?? 0}</span>
              </button>
            ))}
          </div>

          <div className="search" style={{ flex: 1, maxWidth: 320 }}>
            <Icon name="search" />
            <input className="input sm" placeholder="Filter log lines…" value={search} onChange={e => setSearch(e.target.value)} style={{ paddingLeft: 32 }} />
          </div>

          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>Auto-scroll</span>
            <Switch on={autoScroll} onChange={setAutoScroll} />
          </div>
        </div>

        <div className="log-body" ref={logBodyRef} onScroll={handleScroll}>
          {filtered.map((l) => {
            const fields = l.fields || {};
            const fieldEntries = Object.entries(fields);
            const hasExc = !!l.excInfo;
            const hasDetail = !!l.event || fieldEntries.length > 0 || hasExc;
            const isOpen = expanded.has(l.seq);
            const lvlClass = l.level === 'WARNING' ? 'warn' : l.level.toLowerCase();
            const inlineChips = fieldEntries.slice(0, MAX_INLINE_CHIPS);
            const overflowCount = Math.max(0, fieldEntries.length - inlineChips.length);
            return (
              <React.Fragment key={l.seq}>
                <div
                  className={`log-line ${lvlClass}${hasDetail ? ' has-detail' : ''}`}
                  onClick={hasDetail ? () => toggleExpand(l.seq) : undefined}
                >
                  <span className="ts">{fmtTime(l.ts)}</span>
                  <span className="lvl">{l.level === 'WARNING' ? 'WARN' : l.level}</span>
                  <span className="src">[{l.src}]</span>
                  <span className="msg">{l.humanMessage || l.message}</span>
                  <span className="log-line-chips">
                    {inlineChips.map(([k, v]) => (
                      <span key={k} className="log-line-chip" title={`${k}=${fmtFieldValue(v)}`}>
                        <span className="k">{k}=</span>{fmtFieldValue(v)}
                      </span>
                    ))}
                    {overflowCount > 0 && (
                      <span className="log-line-chip more">+{overflowCount}</span>
                    )}
                    {hasExc && <span className="log-line-chip trace">trace</span>}
                    {hasDetail && <span className="log-line-caret">{isOpen ? '▾' : '▸'}</span>}
                  </span>
                </div>
                {isOpen && hasDetail && (
                  <div className="log-line-expanded">
                    {l.event && (
                      <div className="row">
                        <span className="label">event</span>
                        <span className="event">{l.event}</span>
                      </div>
                    )}
                    {fieldEntries.length > 0 && (
                      <div className="row">
                        <span className="label">fields</span>
                        <div className="log-line-fields">
                          {fieldEntries.map(([k, v]) => (
                            <React.Fragment key={k}>
                              <span className="fk">{k}</span>
                              <span className="fv">{fmtFieldValue(v)}</span>
                            </React.Fragment>
                          ))}
                        </div>
                      </div>
                    )}
                    {hasExc && (
                      <div className="row">
                        <span className="label">trace</span>
                        <pre className="log-line-trace">{l.excInfo}</pre>
                      </div>
                    )}
                  </div>
                )}
              </React.Fragment>
            );
          })}
          {filtered.length === 0 && (
            <div style={{ padding: '40px 24px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 13, fontFamily: 'var(--font-sans)' }}>
              No log lines match the current filter.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

window.ActivityPage = ActivityPage;
