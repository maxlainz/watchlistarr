// Main app — sidebar shell, routing, tweaks

const NAV = [
  { id: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
  { id: 'users', label: 'Users', icon: 'users' },
  { id: 'lists', label: 'Lists', icon: 'list' },
  { id: 'custom-lists', label: 'Custom Lists', icon: 'layers' },
  { id: 'activity', label: 'Activity', icon: 'activity' },
];

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#e6b95a",
  "density": "cozy"
}/*EDITMODE-END*/;

const ACCENT_PRESETS = {
  '#e6b95a': { h: 60,  hf: 60,  fg: '0.18 0.02 60'  }, // amber
  '#b389f5': { h: 290, hf: 295, fg: '0.18 0.04 290' }, // violet
  '#5dc4d8': { h: 195, hf: 200, fg: '0.18 0.03 195' }, // teal
  '#e88a8a': { h: 15,  hf: 20,  fg: '0.18 0.04 15'  }, // rose
};
const ACCENT_OPTIONS = Object.keys(ACCENT_PRESETS);

const LoadingShell = ({ error }) => (
  <div className="app">
    <main className="main">
      <div className="page" style={{ padding: 48, color: 'var(--text-dim)' }}>
        {error ? (
          <>
            <h1>Failed to load</h1>
            <p>{error.message || String(error)}</p>
          </>
        ) : (
          'Loading…'
        )}
      </div>
    </main>
  </div>
);

const App = () => {
  const [page, setPage] = React.useState('dashboard');
  const [pageParam, setPageParam] = React.useState(null);
  const [users, setUsers] = React.useState(null);
  const [customLists, setCustomLists] = React.useState(null);
  const [dashboard, setDashboard] = React.useState(null);
  const [bootstrapError, setBootstrapError] = React.useState(null);
  const [toastMsg, setToastMsg] = React.useState(null);
  const [tweaks, setTweak] = window.useTweaks(TWEAK_DEFAULTS);

  const refreshUsers = React.useCallback(async () => {
    const fresh = await window.API.listUsers();
    setUsers(fresh);
    return fresh;
  }, []);

  const refreshCustomLists = React.useCallback(async () => {
    const fresh = await window.API.listCustomLists();
    setCustomLists(fresh);
    return fresh;
  }, []);

  const refreshDashboard = React.useCallback(async () => {
    const fresh = await window.API.dashboard();
    setDashboard(fresh);
    return fresh;
  }, []);

  React.useEffect(() => {
    let mounted = true;
    window.API.bootstrap()
      .then(data => {
        if (!mounted) return;
        setUsers(data.users);
        setCustomLists(data.customLists);
        setDashboard(data.dashboard);
      })
      .catch(err => mounted && setBootstrapError(err));
    return () => { mounted = false; };
  }, []);

  // Apply accent tweak whenever the picker changes
  React.useEffect(() => {
    const preset = ACCENT_PRESETS[tweaks.accent] || ACCENT_PRESETS['#e6b95a'];
    const root = document.documentElement;
    root.style.setProperty('--accent', `oklch(0.78 0.14 ${preset.h})`);
    root.style.setProperty('--accent-2', `oklch(0.70 0.16 ${preset.hf})`);
    root.style.setProperty('--accent-soft', `oklch(0.78 0.14 ${preset.h} / 0.14)`);
    root.style.setProperty('--accent-fg', `oklch(${preset.fg})`);
    root.setAttribute('data-density', tweaks.density);
  }, [tweaks.accent, tweaks.density]);

  const navigate = (id, param = null) => {
    setPage(id);
    setPageParam(param);
    window.scrollTo(0, 0);
  };

  const showToast = (msg) => setToastMsg(msg);

  if (bootstrapError) return <LoadingShell error={bootstrapError} />;
  if (users === null || customLists === null || dashboard === null) {
    return <LoadingShell />;
  }

  const counts = {
    users: users.length,
    lists: users.reduce((s, u) => s + u.enabledCount, 0),
    'custom-lists': customLists.length,
  };

  let body;
  switch (page) {
    case 'dashboard':
      body = <window.Dashboard navigate={navigate} dashboard={dashboard} refreshDashboard={refreshDashboard} users={users} customLists={customLists} />;
      break;
    case 'users':
      body = <window.UsersPage navigate={navigate} users={users} refreshUsers={refreshUsers} showToast={showToast} />;
      break;
    case 'user-detail':
      body = <window.UserDetailPage navigate={navigate} users={users} refreshUsers={refreshUsers} userId={pageParam} showToast={showToast} />;
      break;
    case 'lists':
      body = <window.ListsPage users={users} refreshUsers={refreshUsers} showToast={showToast} />;
      break;
    case 'custom-lists':
      body = <window.CustomListsPage navigate={navigate} customLists={customLists} refreshCustomLists={refreshCustomLists} showToast={showToast} />;
      break;
    case 'custom-list-editor':
      body = <window.CustomListEditor navigate={navigate} users={users} customLists={customLists} refreshCustomLists={refreshCustomLists} editingSlug={pageParam} showToast={showToast} />;
      break;
    case 'activity':
      body = <window.ActivityPage />;
      break;
    default:
      body = <div className="page">Unknown page</div>;
  }

  const crumbs = (() => {
    const base = NAV.find(n => n.id === page);
    if (page === 'user-detail') {
      const u = users.find(uu => uu.id === pageParam);
      return ['Users', u ? '@' + u.username : 'User'];
    }
    if (page === 'custom-list-editor') {
      return ['Custom Lists', pageParam === 'new' ? 'New' : 'Edit'];
    }
    return [base ? base.label : 'Watchlistarr'];
  })();

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">W</div>
          <div>
            <div className="brand-name">Watchlistarr</div>
            <div className="brand-sub">letterboxd → radarr</div>
          </div>
        </div>

        <div className="nav-section-label">Navigate</div>
        {NAV.map(n => (
          <div key={n.id} className={`nav-item ${page === n.id || (page === 'user-detail' && n.id === 'users') || (page === 'custom-list-editor' && n.id === 'custom-lists') ? 'active' : ''}`} onClick={() => navigate(n.id)}>
            <Icon name={n.icon} />
            <span>{n.label}</span>
            {counts[n.id] !== undefined && <span className="nav-count">{counts[n.id]}</span>}
          </div>
        ))}

        <div className="sidebar-footer">
          <span className="status-dot" />
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-2)', fontWeight: 500 }}>
              {dashboard.stats.recentErrors > 0 ? `${dashboard.stats.recentErrors} error${dashboard.stats.recentErrors === 1 ? '' : 's'} last hour` : 'All systems normal'}
            </div>
            <div style={{ fontSize: 10.5, color: 'var(--text-faint)', fontFamily: 'var(--font-mono)' }}>
              {dashboard.stats.itemsServed} items served
            </div>
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="crumb">
            {crumbs.map((c, i) => (
              <React.Fragment key={i}>
                <span className={i === crumbs.length - 1 ? 'crumb-current' : ''}>{c}</span>
                {i < crumbs.length - 1 && <Icon name="chevronRight" size={13} />}
              </React.Fragment>
            ))}
          </div>
          <div className="topbar-tools">
            <Button variant="ghost" size="sm" icon="info" onClick={() => window.open('https://github.com/maxlainz/watchlistarr', '_blank')}>Docs</Button>
          </div>
        </header>

        {body}
      </main>

      <Toast msg={toastMsg} onDone={() => setToastMsg(null)} />

      <window.TweaksPanel title="Tweaks">
        <window.TweakSection title="Theme">
          <window.TweakColor
            label="Accent"
            value={tweaks.accent}
            options={ACCENT_OPTIONS}
            onChange={v => setTweak('accent', v)}
          />
          <window.TweakRadio
            label="Density"
            value={tweaks.density}
            options={['cozy', 'compact']}
            onChange={v => setTweak('density', v)}
          />
        </window.TweakSection>
      </window.TweaksPanel>
    </div>
  );
};

window.App = App;
