// Custom Lists CRUD page

const CustomListsPage = ({ navigate, customLists, refreshCustomLists, showToast }) => {
  const handleDelete = async (cl) => {
    if (!confirm(`Delete custom list "${cl.name}"?`)) return;
    try {
      await window.API.deleteCustomList(cl.slug);
      await refreshCustomLists();
      showToast('Custom list deleted');
    } catch (err) {
      showToast(err.message || 'Delete failed');
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Custom lists</h1>
          <div className="sub">Combine watchlists and lists from multiple users with filters and time rotation. Each one gets its own Radarr URL.</div>
        </div>
        <div className="actions">
          <Button variant="primary" icon="plus" onClick={() => navigate('custom-list-editor', 'new')}>
            New custom list
          </Button>
        </div>
      </div>

      {customLists.length === 0 ? (
        <div className="empty" style={{ background: 'var(--surface)', borderRadius: 'var(--radius)', border: '1px solid var(--border-subtle)' }}>
          <div className="empty-icon"><Icon name="layers" /></div>
          <h3>No custom lists yet</h3>
          <div>Compose union, intersection, or curated pools across all your users.</div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: 14 }}>
          {customLists.map(cl => (
            <div key={cl.id} className="card" style={{ cursor: 'pointer' }} onClick={() => navigate('custom-list-editor', cl.slug)}>
              <div style={{ padding: '16px 18px 12px', display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                <div style={{
                  width: 34, height: 34, borderRadius: 9, flexShrink: 0,
                  background: cl.op === 'intersection' ? 'var(--blue-soft)' : 'var(--accent-soft)',
                  color: cl.op === 'intersection' ? 'var(--blue)' : 'var(--accent)',
                  display: 'grid', placeItems: 'center',
                  border: '1px solid ' + (cl.op === 'intersection' ? 'oklch(0.55 0.13 245 / 0.35)' : 'oklch(0.55 0.14 60 / 0.35)'),
                }}>
                  <Icon name={cl.op === 'intersection' ? 'sparkle' : 'layers'} size={17} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 14.5, letterSpacing: '-0.01em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {cl.name}
                  </div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--text-faint)', marginTop: 2 }}>
                    /lists/{cl.slug}/
                  </div>
                </div>
                <div onClick={e => e.stopPropagation()} style={{ display: 'flex', gap: 2 }}>
                  <Button variant="ghost" size="sm" icon="edit" iconOnly onClick={() => navigate('custom-list-editor', cl.slug)} />
                  <Button variant="ghost" size="sm" icon="trash" iconOnly onClick={() => handleDelete(cl)} />
                </div>
              </div>

              <div style={{ padding: '0 18px 14px', display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                <Badge tone={cl.op === 'intersection' ? 'blue' : 'amber'}>{cl.op}</Badge>
                <Badge>{cl.sources.filter(s=>s.role==='include').length} sources</Badge>
                {cl.excludedWatchers.length > 0 && <Badge>− {cl.excludedWatchers.length} watched</Badge>}
                {cl.rotationEnabled && <Badge tone="green" dot>rotation on</Badge>}
              </div>

              <div style={{ padding: '12px 18px', background: 'var(--bg)', borderTop: '1px solid var(--border-subtle)', fontSize: 12, color: 'var(--text-dim)' }}>
                {cl.summary || '—'}
              </div>

              <div style={{ padding: '12px 18px', display: 'flex', alignItems: 'center', gap: 12, borderTop: '1px solid var(--border-subtle)' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 11, color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>Items served</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 500 }}>
                    <span style={{ color: 'var(--accent)' }}>{cl.itemsServed}</span>
                    {cl.maxItems && <span style={{ color: 'var(--text-faint)' }}> / {cl.maxItems}</span>}
                  </div>
                </div>
                <div onClick={e => e.stopPropagation()} style={{ minWidth: 0, flex: 1.4 }}>
                  <CodeLine url={`${window.location.origin}/lists/${cl.slug}/`} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

window.CustomListsPage = CustomListsPage;
