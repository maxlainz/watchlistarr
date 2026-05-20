// Activity page — live log tail (polls /api/v1/activity?since= every 2s)

const fmtTime = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};

const ActivityPage = () => {
  const [level, setLevel] = React.useState('All');
  const [autoScroll, setAutoScroll] = React.useState(true);
  const [search, setSearch] = React.useState('');
  const [lines, setLines] = React.useState([]);
  const sinceRef = React.useRef(0);
  const logBodyRef = React.useRef(null);

  React.useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const data = await window.API.activity(sinceRef.current);
        if (cancelled) return;
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

  const filtered = lines.filter(l => {
    if (level !== 'All' && l.level !== level) return false;
    if (search && !`${l.src} ${l.message}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const counts = { All: lines.length };
  ['INFO', 'DEBUG', 'WARNING', 'ERROR'].forEach(lvl => {
    counts[lvl] = lines.filter(l => l.level === lvl).length;
  });
  // The buttons display short labels; the API uses standard logging level names.
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
          {filtered.map((l) => (
            <div key={l.seq} className={`log-line ${l.level === 'WARNING' ? 'warn' : l.level.toLowerCase()}`}>
              <span className="ts">{fmtTime(l.ts)}</span>
              <span className="lvl">{l.level === 'WARNING' ? 'WARN' : l.level}</span>
              <span className="src">[{l.src}]</span>
              <span>{l.message}</span>
            </div>
          ))}
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
