// Custom List editor - create/edit

const slugFromName = (n) => n.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

const CustomListEditor = ({ navigate, users, customLists, refreshCustomLists, editingSlug, showToast }) => {
  const isNew = editingSlug === 'new';
  const existing = !isNew ? customLists.find(c => c.slug === editingSlug) : null;

  const [name, setName] = React.useState(existing?.name || '');
  const [slug, setSlug] = React.useState(existing?.slug || '');
  const [op, setOp] = React.useState(existing?.op || 'union');
  const [includes, setIncludes] = React.useState(
    new Set((existing?.sources || []).filter(s => s.role === 'include').map(s => s.listId))
  );
  const [subtracts, setSubtracts] = React.useState(
    new Set((existing?.sources || []).filter(s => s.role === 'subtract').map(s => s.listId))
  );
  const [excludedWatchers, setExcludedWatchers] = React.useState(
    new Set(existing?.excludedWatchers || [])
  );
  const [maxItems, setMaxItems] = React.useState(existing?.maxItems ?? 100);
  const [sortOrder, setSortOrder] = React.useState(existing?.sortOrder || 'letterboxd');
  const [minRating, setMinRating] = React.useState(existing?.minRating ?? '');
  const [maxRating, setMaxRating] = React.useState(existing?.maxRating ?? '');
  const [minYear, setMinYear] = React.useState(existing?.minYear ?? '');
  const [maxYear, setMaxYear] = React.useState(existing?.maxYear ?? '');
  const [rotationEnabled, setRotationEnabled] = React.useState(existing?.rotationEnabled || false);
  const [rotationInterval, setRotationInterval] = React.useState(existing?.rotationInterval ?? 168);
  const [rotationBatchSize, setRotationBatchSize] = React.useState(existing?.rotationBatchSize ?? 10);
  const [showSubtract, setShowSubtract] = React.useState(subtracts.size > 0);
  const [showExclude, setShowExclude] = React.useState(excludedWatchers.size > 0);
  const [previewPool, setPreviewPool] = React.useState(existing ? existing.itemsServed : null);
  const [previewing, setPreviewing] = React.useState(false);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (isNew) setSlug(slugFromName(name));
  }, [name, isNew]);

  const toggleSet = (setFn, current, value) => {
    const next = new Set(current);
    next.has(value) ? next.delete(value) : next.add(value);
    setFn(next);
  };

  const buildSourcesPayload = () => {
    const out = [];
    for (const lid of includes) out.push({ listId: lid, role: 'include' });
    for (const lid of subtracts) if (!includes.has(lid)) out.push({ listId: lid, role: 'subtract' });
    return out;
  };

  const buildPayload = () => ({
    slug,
    name,
    op,
    sources: buildSourcesPayload(),
    excludedWatchers: [...excludedWatchers],
    maxItems: maxItems === '' ? null : parseInt(maxItems, 10),
    sortOrder,
    minRating: minRating === '' ? null : parseFloat(minRating),
    maxRating: maxRating === '' ? null : parseFloat(maxRating),
    minYear: minYear === '' ? null : parseInt(minYear, 10),
    maxYear: maxYear === '' ? null : parseInt(maxYear, 10),
    rotationEnabled,
    rotationInterval: rotationEnabled ? parseInt(rotationInterval, 10) || null : null,
    rotationBatchSize: rotationEnabled ? parseInt(rotationBatchSize, 10) || 1 : 1,
  });

  const refreshPreview = async () => {
    setPreviewing(true);
    try {
      const resp = await window.API.previewCustomList(buildPayload());
      setPreviewPool(resp.pool);
    } catch (err) {
      showToast(err.message || 'Preview failed');
    } finally {
      setPreviewing(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      if (isNew) {
        await window.API.createCustomList(buildPayload());
      } else {
        await window.API.updateCustomList(existing.slug, buildPayload());
      }
      await refreshCustomLists();
      showToast(isNew ? 'Custom list created' : 'Custom list saved');
      navigate('custom-lists');
    } catch (err) {
      showToast(err.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <Button variant="ghost" size="sm" icon="arrowLeft" onClick={() => navigate('custom-lists')}>All custom lists</Button>
      </div>

      <div className="page-head">
        <div>
          <h1>{isNew ? 'New custom list' : `Edit “${existing.name}”`}</h1>
          <div className="sub">Combine, filter and rotate films from any of your users&apos; lists. Saved as <span style={{ fontFamily: 'var(--font-mono)' }}>/lists/{slug || 'your-slug'}/</span></div>
        </div>
        <div className="actions">
          <Button variant="ghost" onClick={() => navigate('custom-lists')}>Cancel</Button>
          <Button variant="primary" icon="check" onClick={handleSave} disabled={saving || !name || !slug || includes.size === 0}>
            {saving ? 'Saving…' : (isNew ? 'Create list' : 'Save changes')}
          </Button>
        </div>
      </div>

      <div className="card" style={{ padding: '8px 32px' }}>
        {/* Basics */}
        <div className="form-section">
          <div>
            <div className="form-section-title">Basics</div>
            <div className="form-section-sub">A human-readable name and the URL slug used in the Radarr endpoint.</div>
          </div>
          <div className="form-rows">
            <div className="field">
              <label>Name</label>
              <input className="input" placeholder="House watchlist (unwatched)" value={name} onChange={e => setName(e.target.value)} />
            </div>
            <div className="field">
              <label>Slug {!isNew && <Badge>read-only</Badge>}</label>
              <div className="input-prefix">
                <span className="prefix">/lists/</span>
                <input value={slug} onChange={e => setSlug(slugFromName(e.target.value))} disabled={!isNew} placeholder="house-watchlist" />
                <span className="prefix" style={{ borderRight: 'none', borderLeft: '1px solid var(--border)' }}>/</span>
              </div>
              <div className="hint">Lowercase letters, numbers and dashes only. Cannot be changed after creation.</div>
            </div>
          </div>
        </div>

        {/* Sources to include */}
        <div className="form-section">
          <div>
            <div className="form-section-title">Sources to include</div>
            <div className="form-section-sub">Pick any number of watchlists and lists from your users. They&apos;ll be combined using the operator below.</div>
          </div>
          <div>
            <SourcePicker users={users} selected={includes} onToggle={(id) => toggleSet(setIncludes, includes, id)} />
            <div className="radio-group" style={{ marginTop: 14 }}>
              <div className={`radio-card ${op === 'union' ? 'selected' : ''}`} onClick={() => setOp('union')}>
                <div className="title">Union <Badge tone={op==='union' ? 'amber' : 'default'} style={{marginLeft: 4}}>any of</Badge></div>
                <div className="desc">A film appears if it&apos;s in <strong>any</strong> selected source. Great for combined watchlists.</div>
              </div>
              <div className={`radio-card ${op === 'intersection' ? 'selected' : ''}`} onClick={() => setOp('intersection')}>
                <div className="title">Intersection <Badge tone={op==='intersection' ? 'blue' : 'default'} style={{marginLeft: 4}}>all of</Badge></div>
                <div className="desc">A film appears only if it&apos;s in <strong>every</strong> selected source. Date-night picks.</div>
              </div>
            </div>
          </div>
        </div>

        {/* Subtract */}
        <div className="form-section">
          <div>
            <div className="form-section-title">Subtract sources<br/><span style={{ fontWeight: 400, fontSize: 12, color: 'var(--text-faint)' }}>Optional</span></div>
            <div className="form-section-sub">Films in these lists are removed from the result, regardless of the operator above.</div>
          </div>
          <div>
            {!showSubtract ? (
              <Button variant="ghost" icon="plus" onClick={() => setShowSubtract(true)}>Add subtract sources</Button>
            ) : (
              <>
                <SourcePicker users={users} selected={subtracts} onToggle={(id) => toggleSet(setSubtracts, subtracts, id)} />
                <Button variant="ghost" size="sm" style={{ marginTop: 8 }} onClick={() => { setSubtracts(new Set()); setShowSubtract(false); }}>Remove subtract section</Button>
              </>
            )}
          </div>
        </div>

        {/* Excluded watchers */}
        <div className="form-section">
          <div>
            <div className="form-section-title">Exclude already-watched<br/><span style={{ fontWeight: 400, fontSize: 12, color: 'var(--text-faint)' }}>Optional</span></div>
            <div className="form-section-sub">Films watched by these users (per their Letterboxd RSS) are removed from the result.</div>
          </div>
          <div>
            {!showExclude ? (
              <Button variant="ghost" icon="plus" onClick={() => setShowExclude(true)}>Pick users</Button>
            ) : (
              <>
                <div className="checkbox-group">
                  {users.map(u => (
                    <Check key={u.id} checked={excludedWatchers.has(u.username)} onChange={() => toggleSet(setExcludedWatchers, excludedWatchers, u.username)}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                        <Icon name="eye" size={13} /> @{u.username}
                      </span>
                    </Check>
                  ))}
                </div>
                <Button variant="ghost" size="sm" style={{ marginTop: 8 }} onClick={() => { setExcludedWatchers(new Set()); setShowExclude(false); }}>Remove exclude section</Button>
              </>
            )}
          </div>
        </div>

        {/* Preview */}
        <div className="form-section">
          <div>
            <div className="form-section-title">Preview pool</div>
            <div className="form-section-sub">How many films would qualify with the current sources, subtracts, watched and filters. Nothing is persisted.</div>
          </div>
          <div>
            <div className="preview-box">
              <div className="preview-num">{previewing ? '…' : (previewPool !== null ? previewPool.toLocaleString() : '?')}</div>
              <div className="preview-lbl">
                {previewing
                  ? 'Computing eligible pool…'
                  : previewPool !== null
                    ? `films eligible · ${maxItems ? `serving up to ${maxItems}` : 'no cap'}`
                    : 'Run preview to see eligible pool size.'}
              </div>
              <Button variant="ghost" icon="refresh" onClick={refreshPreview} disabled={previewing || includes.size === 0}>
                {previewing ? 'Computing…' : 'Refresh preview'}
              </Button>
            </div>
          </div>
        </div>

        {/* Serving */}
        <div className="form-section">
          <div>
            <div className="form-section-title">Serving</div>
            <div className="form-section-sub">How many films Radarr sees and in what order.</div>
          </div>
          <div className="form-rows">
            <div className="row-2">
              <div className="field">
                <label>Max items <Badge>integer</Badge></label>
                <input className="input" type="number" min="1" value={maxItems} onChange={e => setMaxItems(e.target.value)} />
                <div className="hint">Leave blank to serve the full pool.</div>
              </div>
              <div className="field">
                <label>Sort order</label>
                <select className="select" value={sortOrder} onChange={e => setSortOrder(e.target.value)}>
                  <option value="letterboxd">Letterboxd order (recommended)</option>
                  <option value="random">Random</option>
                  <option value="reverse">Reverse</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        {/* Filters */}
        <div className="form-section">
          <div>
            <div className="form-section-title">Static filters<br/><span style={{ fontWeight: 400, fontSize: 12, color: 'var(--text-faint)' }}>Optional</span></div>
            <div className="form-section-sub">Drop films outside these ranges from the eligible pool.</div>
          </div>
          <div className="form-rows">
            <div className="row-2">
              <div className="field">
                <label><Icon name="star" size={13} /> Min Letterboxd rating</label>
                <input className="input" type="number" step="0.1" min="0" max="5" placeholder="e.g. 3.5" value={minRating} onChange={e => setMinRating(e.target.value)} />
              </div>
              <div className="field">
                <label><Icon name="star" size={13} /> Max Letterboxd rating</label>
                <input className="input" type="number" step="0.1" min="0" max="5" placeholder="e.g. 5.0" value={maxRating} onChange={e => setMaxRating(e.target.value)} />
              </div>
            </div>
            <div className="row-2">
              <div className="field">
                <label><Icon name="clock" size={13} /> Min year</label>
                <input className="input" type="number" placeholder="e.g. 1990" value={minYear} onChange={e => setMinYear(e.target.value)} />
              </div>
              <div className="field">
                <label><Icon name="clock" size={13} /> Max year</label>
                <input className="input" type="number" placeholder="e.g. 2025" value={maxYear} onChange={e => setMaxYear(e.target.value)} />
              </div>
            </div>
          </div>
        </div>

        {/* Rotation */}
        <div className="form-section">
          <div>
            <div className="form-section-title">Time rotation<br/><span style={{ fontWeight: 400, fontSize: 12, color: 'var(--text-faint)' }}>Optional</span></div>
            <div className="form-section-sub">Cycle films out of the served set on a schedule. Useful when the pool is much larger than max items.</div>
          </div>
          <div>
            <label className="check-row" style={{ borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', background: 'var(--bg)' }} onClick={(e) => { e.preventDefault(); setRotationEnabled(!rotationEnabled); }}>
              <div className={`check-box ${rotationEnabled ? 'checked' : ''}`}>
                <Icon name="check" size={11} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 500, fontSize: 13 }}>Enable rotation</div>
                <div style={{ fontSize: 11.5, color: 'var(--text-dim)', marginTop: 2 }}>
                  Every interval, drop the oldest <em>batch size</em> served films and pull fresh ones from the pool (FIFO).
                </div>
              </div>
              <Icon name="rotation" size={16} />
            </label>
            {rotationEnabled && (
              <div className="row-2" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Rotation interval <Badge>hours</Badge></label>
                  <input className="input" type="number" min="1" value={rotationInterval} onChange={e => setRotationInterval(e.target.value)} />
                  <div className="hint">e.g. 168 = once a week.</div>
                </div>
                <div className="field">
                  <label>Batch size <Badge>films</Badge></label>
                  <input className="input" type="number" min="1" value={rotationBatchSize} onChange={e => setRotationBatchSize(e.target.value)} />
                  <div className="hint">How many films cycle in & out each tick.</div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 18 }}>
        <Button variant="ghost" onClick={() => navigate('custom-lists')}>Cancel</Button>
        <Button variant="primary" icon="check" onClick={handleSave} disabled={saving || !name || !slug || includes.size === 0}>
          {saving ? 'Saving…' : (isNew ? 'Create list' : 'Save changes')}
        </Button>
      </div>
    </div>
  );
};

const SourcePicker = ({ users, selected, onToggle }) => {
  const [open, setOpen] = React.useState({});
  React.useEffect(() => {
    setOpen(prev => {
      const next = { ...prev };
      users.forEach(u => {
        if (u.lists.some(l => selected.has(l.id)) && next[u.id] === undefined) next[u.id] = true;
      });
      return next;
    });
  }, []); // eslint-disable-line

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {users.map(u => {
        const selectedCount = u.lists.filter(l => selected.has(l.id)).length;
        const isOpen = !!open[u.id];
        return (
          <div key={u.id} className="checkbox-group">
            <div
              className="checkbox-group-head"
              style={{ cursor: 'pointer', userSelect: 'none', borderBottom: isOpen ? '1px solid var(--border-subtle)' : 'none' }}
              onClick={() => setOpen({ ...open, [u.id]: !isOpen })}
            >
              <div style={{ width: 18, display: 'grid', placeItems: 'center', color: 'var(--text-dim)', transition: 'transform 0.15s', transform: isOpen ? 'rotate(90deg)' : 'none' }}>
                <Icon name="chevronRight" size={13} />
              </div>
              <div className="user-avatar" style={{ width: 20, height: 20, fontSize: 9, borderRadius: 5 }}>{u.username.slice(0,2).toUpperCase()}</div>
              @{u.username}
              {selectedCount > 0 && (
                <Badge tone="amber" style={{ marginLeft: 6 }}>{selectedCount} selected</Badge>
              )}
              <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-faint)' }}>
                {selectedCount} / {u.lists.length}
              </span>
            </div>
            {isOpen && [...u.lists].sort((a,b) => (a.sourceType === 'watchlist' ? -1 : b.sourceType === 'watchlist' ? 1 : 0)).map(l => (
              <Check key={l.id} checked={selected.has(l.id)} onChange={() => onToggle(l.id)} meta={`${l.filmCount.toLocaleString()} films`}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <Icon name={l.sourceType === 'watchlist' ? 'bookmark' : 'list'} size={13} />
                  {l.name}
                  {l.sourceType === 'watchlist' && <Badge tone="amber">watchlist</Badge>}
                </span>
              </Check>
            ))}
          </div>
        );
      })}
    </div>
  );
};

window.CustomListEditor = CustomListEditor;
