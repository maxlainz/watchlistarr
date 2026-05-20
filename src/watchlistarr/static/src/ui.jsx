// Shared UI primitives

const Button = ({ variant = 'default', size, icon, iconOnly, className, children, ...props }) => {
  const classes = ['btn'];
  if (variant === 'primary') classes.push('primary');
  if (variant === 'ghost') classes.push('ghost');
  if (variant === 'danger') classes.push('danger');
  if (iconOnly) classes.push('icon');
  if (size === 'sm') classes.push('sm');
  if (className) classes.push(className);
  return (
    <button className={classes.join(' ')} {...props}>
      {icon && <Icon name={icon} />}
      {children}
    </button>
  );
};

const Switch = ({ on, onChange, ...props }) => (
  <div className={`switch ${on ? 'on' : ''}`} onClick={() => onChange && onChange(!on)} role="switch" aria-checked={on} {...props} />
);

const Badge = ({ tone = 'default', dot, children }) => (
  <span className={`badge ${tone !== 'default' ? tone : ''}`}>
    {dot && <span className="dot" />}
    {children}
  </span>
);

const Card = ({ title, sub, actions, padded = true, children }) => (
  <div className="card">
    {title && (
      <div className="card-head">
        <div>
          <div className="card-title">{title}</div>
          {sub && <div className="card-sub">{sub}</div>}
        </div>
        {actions && <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>{actions}</div>}
      </div>
    )}
    <div className={padded ? 'card-body' : ''} style={padded ? {} : { padding: 0 }}>
      {children}
    </div>
  </div>
);

const CodeLine = ({ url }) => {
  const [copied, setCopied] = React.useState(false);
  const handleCopy = (e) => {
    e.stopPropagation();
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  };
  return (
    <div className={`code-line ${copied ? 'copied' : ''}`} title={url}>
      <span className="url">{url}</span>
      <button className="copy-btn" onClick={handleCopy} title={copied ? 'Copied!' : 'Copy URL'}>
        <Icon name={copied ? 'check' : 'copy'} />
      </button>
    </div>
  );
};

const Status = ({ status }) => {
  if (status === 'success') return <Badge tone="green" dot>synced</Badge>;
  if (status === 'error') return <Badge tone="red" dot>error</Badge>;
  if (status === 'pending') return <Badge tone="yellow" dot>pending</Badge>;
  return <Badge tone="default">—</Badge>;
};

const Toast = ({ msg, onDone }) => {
  React.useEffect(() => {
    if (!msg) return;
    const t = setTimeout(onDone, 2000);
    return () => clearTimeout(t);
  }, [msg, onDone]);
  if (!msg) return null;
  return (
    <div className="toast">
      <Icon name="check" />
      {msg}
    </div>
  );
};

// Mini sparkline
const Sparkline = ({ data, accent = true }) => {
  const w = 200, h = 50;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const step = w / (data.length - 1);
  const points = data.map((v, i) => [i * step, h - ((v - min) / range) * (h - 6) - 3]);
  const line = points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const fill = `${line} L${w},${h} L0,${h} Z`;
  return (
    <svg className="stat-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <path d={fill} className="spark-fill" />
      <path d={line} className="spark-line" />
    </svg>
  );
};

const Check = ({ checked, onChange, children, meta }) => (
  <label className="check-row" onClick={(e) => { e.preventDefault(); onChange(!checked); }}>
    <div className={`check-box ${checked ? 'checked' : ''}`}>
      <Icon name="check" size={11} />
    </div>
    <div className="name">{children}</div>
    {meta && <div className="meta">{meta}</div>}
  </label>
);

const Spinner = ({ size = 16 }) => (
  <span
    className="spinner"
    style={{ width: size, height: size, borderWidth: Math.max(2, Math.round(size / 8)) }}
    role="status"
    aria-label="Loading"
  />
);

Object.assign(window, { Button, Switch, Badge, Card, CodeLine, Status, Toast, Sparkline, Check, Spinner });
