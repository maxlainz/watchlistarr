// Dashboard page — stat cards + recent activity feed + next scheduled queue.

const Dashboard = ({ navigate, dashboard, refreshDashboard, users, customLists }) => {
  const { formatRelative } = window.MOCK;
  const stats = dashboard.stats;
  const activity = dashboard.recentActivity || [];
  const upcoming = dashboard.upcoming || [];

  React.useEffect(() => {
    const id = setInterval(() => { refreshDashboard().catch(() => {}); }, 15000);
    return () => clearInterval(id);
  }, [refreshDashboard]);

  // Real data has no trend history; show a flat-ish line so cards keep their shape.
  const flatSpark = (val) => {
    const n = Math.max(1, Math.round(val));
    return Array.from({ length: 11 }, () => n);
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <div className="sub">
            At a glance — {activity[0] ? `last activity ${formatRelative(activity[0].ts)}` : 'no activity yet'}.
          </div>
        </div>
        <div className="actions">
          <Button icon="refresh" variant="ghost" onClick={() => refreshDashboard()}>Refresh</Button>
          <Button icon="plus" variant="primary" onClick={() => navigate('users')}>Add user</Button>
        </div>
      </div>

      {stats.recentErrors > 0 && (
        <div className="banner error">
          <Icon name="alert" />
          <div>
            <strong>{stats.recentErrors} scrape error{stats.recentErrors === 1 ? '' : 's'}</strong> in the last hour.
          </div>
          <Button variant="ghost" size="sm" className="banner-action" onClick={() => navigate('activity')}>
            View logs <Icon name="arrowRight" />
          </Button>
        </div>
      )}

      <div className="stat-grid">
        <div className="stat" onClick={() => navigate('users')}>
          <div className="stat-label"><Icon name="users" />Users registered</div>
          <div className="stat-value">{stats.usersCount}</div>
          <div className="stat-meta">{users.length === 0 ? 'add your first one' : `${users.length} tracked`}</div>
          <Sparkline data={flatSpark(stats.usersCount)} />
        </div>
        <div className="stat" onClick={() => navigate('lists')}>
          <div className="stat-label"><Icon name="list" />Lists monitored</div>
          <div className="stat-value">{stats.listsCount}</div>
          <div className="stat-meta">across {stats.usersCount} user{stats.usersCount === 1 ? '' : 's'}</div>
          <Sparkline data={flatSpark(stats.listsCount)} />
        </div>
        <div className="stat" onClick={() => navigate('custom-lists')}>
          <div className="stat-label"><Icon name="layers" />Custom lists active</div>
          <div className="stat-value">{stats.customCount}</div>
          <div className="stat-meta">{stats.itemsServed} items served</div>
          <Sparkline data={flatSpark(stats.customCount)} />
        </div>
        <div className="stat">
          <div className="stat-label"><Icon name="eye" />Items served (all lists)</div>
          <div className="stat-value">{stats.itemsServed.toLocaleString()}</div>
          <div className="stat-meta">cumulative across custom lists</div>
          <Sparkline data={flatSpark(stats.itemsServed)} />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16 }}>
        <Card
          title="Recent activity"
          sub="Latest sync runs and rotations"
          padded={false}
          actions={<Button variant="ghost" size="sm" onClick={() => navigate('activity')}>Open Activity <Icon name="arrowRight" /></Button>}
        >
          <div>
            {activity.length === 0 && (
              <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-dim)' }}>
                Nothing yet. Add a user to kick off discovery.
              </div>
            )}
            {activity.map((a, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '11px 16px',
                borderBottom: i < activity.length - 1 ? '1px solid var(--border-subtle)' : 'none',
              }}>
                <div style={{
                  width: 26, height: 26, borderRadius: 7,
                  background: a.status === 'error' ? 'var(--red-soft)' : a.status === 'info' ? 'var(--blue-soft)' : 'var(--green-soft)',
                  color: a.status === 'error' ? 'var(--red)' : a.status === 'info' ? 'var(--blue)' : 'var(--green)',
                  display: 'grid', placeItems: 'center', flexShrink: 0,
                }}>
                  <Icon name={a.kind === 'rotation' ? 'rotation' : a.kind === 'error' ? 'alert' : a.kind === 'watched' ? 'eye' : 'refresh'} size={13} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, color: 'var(--text)' }}>{a.text}</div>
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--text-faint)' }}>
                  {formatRelative(a.ts)}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Next scheduled" sub="Worker queue">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {upcoming.length === 0 && (
              <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-dim)', fontSize: 12 }}>
                No jobs scheduled.
              </div>
            )}
            {upcoming.map((row, i) => (
              <ScheduledRow key={i} label={row.label} detail={row.detail} eta={row.eta} kind={row.kind} />
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
};

const ScheduledRow = ({ label, detail, eta, kind }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
    <div style={{
      width: 24, height: 24, borderRadius: 6, flexShrink: 0,
      background: kind === 'error' ? 'var(--red-soft)' : kind === 'rotation' ? 'var(--accent-soft)' : 'var(--surface-2)',
      color: kind === 'error' ? 'var(--red)' : kind === 'rotation' ? 'var(--accent)' : 'var(--text-dim)',
      display: 'grid', placeItems: 'center', border: '1px solid var(--border-subtle)',
    }}>
      <Icon name={kind === 'rotation' ? 'rotation' : kind === 'watched' ? 'eye' : kind === 'error' ? 'refresh' : 'refresh'} size={12} />
    </div>
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 13, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</div>
      <div style={{ fontSize: 11.5, color: 'var(--text-dim)' }}>{detail}</div>
    </div>
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)' }}>{eta}</div>
  </div>
);

window.Dashboard = Dashboard;
