import React from 'react';
import { FileText, ExternalLink, Sparkles } from 'lucide-react';
import './ArtifactCanvas.css';

export default function ArtifactCard({ artifact, onOpen, isActive }) {
  if (!artifact) return null;

  return (
    <div className={`artifact-chat-card ${isActive ? 'is-active-canvas' : ''}`}>
      <div className="artifact-chat-card-left">
        <div className="artifact-card-icon-box">
          <FileText size={18} className="artifact-card-icon" />
          <span className="artifact-sparkle-dot"><Sparkles size={8} /></span>
        </div>
        <div className="artifact-card-meta">
          <div className="artifact-card-label">Document Artifact</div>
          <div className="artifact-card-title">{artifact.title || 'Untitled Document'}</div>
        </div>
      </div>
      <button
        type="button"
        className="artifact-card-open-btn"
        onClick={() => onOpen(artifact)}
        title="Open interactive document canvas"
      >
        <span>{isActive ? 'Canvas Open' : 'Open in Canvas'}</span>
        <ExternalLink size={13} />
      </button>
    </div>
  );
}
