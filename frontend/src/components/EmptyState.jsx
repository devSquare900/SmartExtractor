export default function EmptyState({ icon, title, children, action }) {
  return (
    <div className="empty-state">
      <div className="empty-art" aria-hidden="true">{icon}</div>
      <h3 className="display">{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}
