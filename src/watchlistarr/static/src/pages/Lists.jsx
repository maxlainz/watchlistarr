// Lists view (global, grouped by user)

const ListsPage = ({ users, refreshUsers, showToast }) => {
  const { formatRelative } = window.MOCK;
  const [openAdv, setOpenAdv] = React.useState({});

  const enabledByUser = users
    .map(u => ({ ...u, enabledLists: u.lists.filter(l => l.enabled) }))
    .filter(u => u.enabledLists.length > 0);

  const totalEnabled = enabledByUser.reduce((s, u) => s + u.enabledLists.length, 0);
  const totalFilms = enabledByUser.reduce((s, u) => s + u.enabledLists.reduce((ss, l) => ss + l.filmCount, 0), 0);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Lists</h1>
          <div className="sub">All enabled lists across users. Each row exposes its Radarr-ready URL and per-list sync settings.</div>
        </div>
        <div className="actions">
          <Badge tone="amber">{totalEnabled} lists</Badge>
          <Badge>{totalFilms.toLocaleString()} films total</Badge>
        </div>
      </div>

      {enabledByUser.length === 0 && (
        <div className="empty" style={{ background: 'var(--surface)', borderRadius: 'var(--radius)', border: '1px solid var(--border-subtle)' }}>
          <div className="empty-icon"><Icon name="list" /></div>
          <h3>No lists enabled yet</h3>
          <div>Open a user from the Users tab and toggle the lists you want to monitor.</div>
        </div>
      )}

      {enabledByUser.map(u => (
        <div key={u.id} className="user-block">
          <div className="user-block-head">
            <div className="user-avatar">{u.username.slice(0,2).toUpperCase()}</div>
            <div>
              <div className="username">@{u.username}</div>
              <div className="lists-count">{u.enabledLists.length} list{u.enabledLists.length === 1 ? '' : 's'} enabled · {u.enabledLists.reduce((s,l)=>s+l.filmCount,0).toLocaleString()} films</div>
            </div>
          </div>

          {u.enabledLists.map(l => {
            const key = `${u.id}-${l.id}`;
            const isOpen = openAdv[key];
            const path = l.sourceType === 'watchlist' ? 'watchlist' : l.slug;
            const radarrUrl = `${window.location.origin}/${u.username}/${path}/`;
            return (
              <React.Fragment key={l.id}>
                <div className="list-row">
                  <div className="name">
                    <div className={`icon-bg ${l.sourceType === 'watchlist' ? 'watchlist' : ''}`}>
                      <Icon name={l.sourceType === 'watchlist' ? 'bookmark' : 'list'} />
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div className="label">{l.name}</div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-faint)' }}>
                        {l.sourceType === 'watchlist' ? 'watchlist' : `list • ${l.slug}`}
                      </div>
                    </div>
                  </div>
                  <div className="num">{l.filmCount.toLocaleString()}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>{l.lastSyncedAt ? formatRelative(l.lastSyncedAt) : '—'}</div>
                  <div><Status status={l.status} /></div>
                  <CodeLine url={radarrUrl} />
                  <Button
                    variant="ghost" size="sm"
                    icon={isOpen ? 'chevronDown' : 'settings'}
                    onClick={() => setOpenAdv({ ...openAdv, [key]: !isOpen })}
                  >
                    {isOpen ? 'Hide' : 'Advanced'}
                  </Button>
                </div>
                {isOpen && (
                  <AdvancedPanel
                    user={u}
                    list={l}
                    refreshUsers={refreshUsers}
                    showToast={showToast}
                  />
                )}
              </React.Fragment>
            );
          })}
        </div>
      ))}
    </div>
  );
};

const AdvancedPanel = ({ user, list, refreshUsers, showToast }) => {
  const isWatchlist = list.sourceType === 'watchlist';
  const adv = list.advanced || {};
  const [inc, setInc] = React.useState(adv.incrementalInterval ?? '');
  const [full, setFull] = React.useState(adv.fullInterval ?? '');
  const [flap, setFlap] = React.useState(adv.flapConfirmScrapes ?? '');
  const [saving, setSaving] = React.useState(false);

  const placeholder = (defaultVal) => `${defaultVal ?? ''} (default)`;

  const handleSave = async () => {
    setSaving(true);
    try {
      await window.API.saveListSettings(user.username, list.id, {
        incrementalInterval: inc === '' ? null : parseInt(inc, 10),
        fullInterval: full === '' ? null : parseInt(full, 10),
        flapConfirmScrapes: flap === '' ? null : parseInt(flap, 10),
      });
      await refreshUsers();
      showToast('Settings saved');
    } catch (err) {
      showToast(err.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="advanced-panel">
      <div className="field">
        <label>
          Incremental interval
          <Badge>hours</Badge>
        </label>
        <input className="input sm" type="number" min="1" value={inc}
               placeholder={placeholder(adv.defaultIncrementalInterval)}
               onChange={e => setInc(e.target.value)} />
        <div className="hint">How often we re-scrape just the latest additions. {isWatchlist ? 'Watchlists change often — keep this low.' : 'Static lists rarely change — every few hours is plenty.'}</div>
      </div>
      <div className="field">
        <label>
          Full re-scrape
          <Badge>hours</Badge>
        </label>
        <input className="input sm" type="number" min="1" value={full}
               placeholder={placeholder(adv.defaultFullInterval)}
               onChange={e => setFull(e.target.value)} />
        <div className="hint">Re-fetches every page. Catches removals and slug renames.</div>
      </div>
      <div className="field">
        <label>
          Anti-flap confirms
          <Badge>scrapes</Badge>
        </label>
        <input className="input sm" type="number" min="1" value={flap}
               placeholder={placeholder(adv.defaultFlapConfirmScrapes)}
               onChange={e => setFlap(e.target.value)} />
        <div className="hint">A film must be missing for this many consecutive scrapes before we remove it. Prevents Letterboxd hiccups from removing items in Radarr.</div>
      </div>
      <div className="field" style={{ justifyContent: 'flex-end' }}>
        <Button variant="primary" size="sm" icon="check" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save settings'}
        </Button>
        <div className="hint" style={{ marginTop: 8 }}>Defaults fall back to your environment variables ({isWatchlist ? 'WATCHLIST_*' : 'LISTS_*'}_INTERVAL).</div>
      </div>
    </div>
  );
};

window.ListsPage = ListsPage;
