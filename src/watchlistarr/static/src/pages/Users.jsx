// Users page

const UsersPage = ({ navigate, users, refreshUsers, showToast }) => {
  const [newUsername, setNewUsername] = React.useState('');
  const [adding, setAdding] = React.useState(false);
  const [search, setSearch] = React.useState('');
  const { formatDateShort, formatRelative } = window.MOCK;

  const filtered = users.filter(u => u.username.toLowerCase().includes(search.toLowerCase()));

  const handleAdd = async (e) => {
    e.preventDefault();
    if (!newUsername.trim()) return;
    setAdding(true);
    try {
      const created = await window.API.addUser(newUsername.trim());
      await refreshUsers();
      setNewUsername('');
      showToast(`Validated @${created.username} on Letterboxd. Discovery running…`);
    } catch (err) {
      showToast(err.message || 'Could not add user');
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (u) => {
    if (!confirm(`Delete @${u.username}? This removes their lists, watch history and any custom-list links.`)) return;
    try {
      await window.API.deleteUser(u.username);
      await refreshUsers();
      showToast('User removed');
    } catch (err) {
      showToast(err.message || 'Delete failed');
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Users</h1>
          <div className="sub">Letterboxd profiles to monitor. Adding a user discovers their watchlist and public lists — nothing is enabled until you toggle it.</div>
        </div>
      </div>

      <Card padded={false}>
        <div style={{ padding: '14px 16px', display: 'flex', gap: 10, alignItems: 'center', borderBottom: '1px solid var(--border-subtle)' }}>
          <form onSubmit={handleAdd} style={{ display: 'flex', gap: 8, flex: 1, maxWidth: 480 }}>
            <div className="input-prefix" style={{ flex: 1 }}>
              <span className="prefix">letterboxd.com/</span>
              <input
                placeholder="username"
                value={newUsername}
                onChange={e => setNewUsername(e.target.value)}
                disabled={adding}
              />
            </div>
            <Button type="submit" variant="primary" icon={adding ? 'refresh' : 'plus'} disabled={adding || !newUsername.trim()}>
              {adding ? 'Validating…' : 'Add user'}
            </Button>
          </form>
          <div className="search" style={{ marginLeft: 'auto' }}>
            <Icon name="search" />
            <input className="input" placeholder="Search users" value={search} onChange={e => setSearch(e.target.value)} />
          </div>
        </div>

        {filtered.length === 0 ? (
          <div className="empty">
            <div className="empty-icon"><Icon name="users" /></div>
            <h3>No users yet</h3>
            <div>Add a Letterboxd username above to get started.</div>
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Lists enabled</th>
                <th>Total discovered</th>
                <th>Added</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(u => (
                <tr key={u.id} style={{ cursor: 'pointer' }} onClick={() => navigate('user-detail', u.id)}>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div className="user-avatar">{u.username.slice(0,2).toUpperCase()}</div>
                      <div>
                        <div style={{ fontWeight: 500 }}>@{u.username}</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-faint)' }}>letterboxd.com/{u.username}/</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <Badge tone={u.enabledCount > 0 ? 'amber' : 'default'}>
                      {u.enabledCount} of {u.totalLists}
                    </Badge>
                  </td>
                  <td className="num">{u.totalLists}</td>
                  <td style={{ color: 'var(--text-dim)' }} title={formatDateShort(u.addedAt)}>{formatRelative(u.addedAt)}</td>
                  <td className="actions-cell" onClick={e => e.stopPropagation()}>
                    <Button variant="ghost" size="sm" icon="settings" iconOnly onClick={() => navigate('user-detail', u.id)} title="Configure lists" />
                    <Button variant="ghost" size="sm" icon="trash" iconOnly className="danger" onClick={() => handleDelete(u)} title="Delete user" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <div style={{ marginTop: 14, fontSize: 12, color: 'var(--text-faint)', display: 'flex', alignItems: 'center', gap: 8 }}>
        <Icon name="info" size={13} />
        <span>Discovery runs in the background after a user is added. Lists are imported as <strong style={{ color: 'var(--text-2)' }}>disabled</strong> — enable the ones you want on each user&apos;s page.</span>
      </div>
    </div>
  );
};

window.UsersPage = UsersPage;


const UserDetailPage = ({ navigate, users, refreshUsers, userId, showToast }) => {
  const user = users.find(u => u.id === userId);
  const { formatRelative } = window.MOCK;
  if (!user) return <div className="page"><p>User not found.</p></div>;

  const [busy, setBusy] = React.useState(null);

  const toggleList = async (listId) => {
    setBusy(listId);
    try {
      await window.API.toggleList(user.username, listId);
      await refreshUsers();
    } catch (err) {
      showToast(err.message || 'Toggle failed');
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Delete @${user.username}? This removes their lists, watch history and any custom-list links.`)) return;
    try {
      await window.API.deleteUser(user.username);
      await refreshUsers();
      navigate('users');
    } catch (err) {
      showToast(err.message || 'Delete failed');
    }
  };

  // Watchlist first (the API already sorts, but be defensive on optimistic updates)
  const sortedLists = [...user.lists].sort((a, b) => {
    if (a.sourceType === 'watchlist') return -1;
    if (b.sourceType === 'watchlist') return 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <div className="page">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <Button variant="ghost" size="sm" icon="arrowLeft" onClick={() => navigate('users')}>All users</Button>
      </div>

      <div className="page-head">
        <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
          <div className="user-avatar" style={{ width: 48, height: 48, fontSize: 16, borderRadius: 12 }}>{user.username.slice(0,2).toUpperCase()}</div>
          <div>
            <h1>@{user.username}</h1>
            <div className="sub">
              Added {formatRelative(user.addedAt)} · <span style={{ fontFamily: 'var(--font-mono)' }}>letterboxd.com/{user.username}/</span>
            </div>
          </div>
        </div>
        <div className="actions">
          <Button variant="danger" icon="trash" onClick={handleDelete}>Delete user</Button>
        </div>
      </div>

      <Card padded={false}>
        <div className="card-head" style={{ background: 'var(--surface)' }}>
          <div>
            <div className="card-title">Discovered lists</div>
            <div className="card-sub">Toggle which lists watchlistarr should monitor. Disabled lists are ignored entirely.</div>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 14, fontSize: 12, color: 'var(--text-dim)' }}>
            <span><strong style={{ color: 'var(--text)' }}>{user.enabledCount}</strong> enabled</span>
            <span><strong style={{ color: 'var(--text)' }}>{user.totalLists - user.enabledCount}</strong> paused</span>
          </div>
        </div>

        {sortedLists.length === 0 ? (
          <div className="empty">
            <div className="empty-icon"><Icon name="list" /></div>
            <h3>Discovery in progress…</h3>
            <div>Letterboxd discovery is running in the background. Refresh in a minute to see public lists.</div>
          </div>
        ) : (
          <div>
            {sortedLists.map((l) => (
              <div key={l.id} className="list-row" style={{ gridTemplateColumns: 'auto 1fr 90px 130px 110px auto', opacity: busy === l.id ? 0.5 : 1 }}>
                <Switch on={l.enabled} onChange={() => toggleList(l.id)} />
                <div className="name">
                  <div className={`icon-bg ${l.sourceType === 'watchlist' ? 'watchlist' : ''}`}>
                    <Icon name={l.sourceType === 'watchlist' ? 'bookmark' : 'list'} />
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div className="label">{l.name}</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-faint)' }}>
                      /{user.username}/{l.slug}/
                    </div>
                  </div>
                </div>
                <div className="num">{l.filmCount.toLocaleString()} films</div>
                <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                  {l.lastSyncedAt ? formatRelative(l.lastSyncedAt) : <span style={{ color: 'var(--text-faint)' }}>never</span>}
                </div>
                <div><Status status={l.status} /></div>
                <div style={{ display: 'flex', gap: 4 }}>
                  <a href={`https://letterboxd.com/${user.username}/${l.sourceType === 'watchlist' ? 'watchlist' : 'list/' + l.slug}/`} target="_blank" rel="noreferrer">
                    <Button variant="ghost" size="sm" icon="arrowUpRight" iconOnly title="Open on Letterboxd" />
                  </a>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div style={{ marginTop: 14, fontSize: 12, color: 'var(--text-faint)', display: 'flex', alignItems: 'center', gap: 8 }}>
        <Icon name="info" size={13} />
        <span>Per-list scrape intervals are tuned in the <a href="#" onClick={e=>{e.preventDefault(); navigate('lists');}} style={{ color: 'var(--accent)' }}>Lists tab</a> under each row&apos;s Advanced panel.</span>
      </div>
    </div>
  );
};

window.UserDetailPage = UserDetailPage;
